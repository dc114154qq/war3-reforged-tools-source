"""The exact new adapter does not change old profile selection or policies."""
import importlib.util
import ast
from itertools import permutations
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from war3_hotkey_adapters import load_profiles, select_profile, resolve_command_bar
from test_hotkey_adapters import Memory
from war3_hotkey_native import (NativeFrameBridge, NativeHandler, CommandBarInternals,
                               OP_STRUCT, NATIVE_NAMES)
from war3_hotkey_model import BindingConfig, SLOT_GROUP_SPECS, default_profile
from war3_hotkey_engine import BindingAction, GameWindowSnapshot, HotkeyEngine
from war3_hotkey_adapters import HotkeySessionIdentity

ROOT = Path(__file__).resolve().parent


def profile():
    return select_profile((0x8664, 1792442231, 236904448), 3, load_profiles())


def test_new_exact_build_uses_its_own_bridge_and_context():
    p = profile()
    assert p['game_version'] == '3.0.1.24371'
    assert p['bridge_file'] == 'war3_hotkey_bridge_24371.dll'
    assert p['native_context']['tls_index_rva'] == 50283576
    assert p['native_context']['native_slot'] == 64
    assert p['native_context']['mode_context'] == 128
    assert p['command_bar']['functions']['set_hotkey'] == 0xfb7730
    assert p['command_bar']['get_hotkey_rva'] == 0xfb4600
    assert p['command_bar']['guarded_call']['return_rva'] == 0x16eac0


@pytest.mark.parametrize('version', ['3.0.0.24268', '3.0.1.24323'])
def test_old_profile_bytes_remain_equal_to_release_snapshot(version):
    path = Path('hotkey_profiles') / (version + '.json')
    assert (ROOT/path).read_bytes() == (ROOT/'versions/hotkeys-v2.0.0'/path).read_bytes()
    p = json.loads((ROOT/path).read_text(encoding='utf-8'))
    fp = tuple(p['fingerprint'][k] for k in ('machine', 'timestamp', 'image_size'))
    assert select_profile(fp, 3, load_profiles()) == p


def test_protected_new_build_defers_only_with_explicit_runtime_validation():
    p = profile()
    identity = type('Identity', (), {'profile': p, 'base': 0x140000000})()
    memory = Memory()
    enabled = lambda *args: pytest.fail('Protected-page path must not guess the override flag')
    result = resolve_command_bar(memory, identity, enabled)
    assert result['validation_deferred'] is True
    assert result['game_ui_get'] == identity.base + 0xf86790
    assert result['overriding_hotkey_enabled'] is None
    p['command_bar']['runtime_code_validation'] = False
    with pytest.raises(RuntimeError, match='校验读取失败'):
        resolve_command_bar(memory, identity, enabled)


def test_readable_new_build_rejects_changed_code_instead_of_deferring():
    p = profile()
    identity = type('Identity', (), {'profile': p, 'base': 0x140000000})()
    memory = Memory()
    for check in p['command_bar']['checks']:
        memory.put(identity.base + check['rva'], bytes.fromhex(check['bytes']))
    assert resolve_command_bar(memory, identity, lambda *_: None)['validation_deferred'] is False
    memory.put(identity.base + p['command_bar']['checks'][0]['rva'], b'\x90')
    with pytest.raises(RuntimeError, match='代码校验失败'):
        resolve_command_bar(memory, identity, lambda *_: None)


def test_new_header_is_generated_from_profile_without_replacing_old_headers():
    spec = importlib.util.spec_from_file_location('hotkey_builder_test', ROOT/'tools/build_war3_hotkey_bridge.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (ROOT/'tools/war3_hotkey_profiles_24371.h').read_text(encoding='utf-8') == module.header_text(profile())
    assert 'war3_hotkey_bridge_24371.dll' in (ROOT/'War3ReforgedHotkeys.spec').read_text(encoding='utf-8')


def test_adjacent_unknown_build_does_not_reuse_the_new_profile():
    with pytest.raises(RuntimeError, match='不会沿用'):
        select_profile((0x8664, 1792442232, 236904448), 3, load_profiles())


VERSIONS = ['3.0.0.24268', '3.0.1.24323', '3.0.1.24371']
SLOTS = [(group, index) for group, (width, height) in SLOT_GROUP_SPECS.items()
         for index in range(width * height)]


@pytest.fixture(params=VERSIONS)
def adapted_bridge(request):
    p = next(p for p in load_profiles() if p['game_version'] == request.param)
    base = 0x7ff100000000
    bridge = NativeFrameBridge(helper_path=ROOT/'tools/war3_hotkey_native_helper.dll')
    bridge.connect = Mock()
    bridge._handlers = {name: NativeHandler(name, 0x100000 + index * 128, base + rva)
                        for index, (name, rva) in enumerate(p['protected_native_rvas'].items())}
    bridge._command_bar = CommandBarInternals(
        command_bar_offset=p['command_bar']['command_bar_offset'],
        submenu_link_offset=p['command_bar']['submenu_link_offset'],
        **{name: base + rva for name, rva in p['command_bar']['functions'].items()})
    bridge._dispatch = Mock(return_value=1)
    return bridge, p, base


@pytest.mark.parametrize('group,index', SLOTS)
def test_every_slot_uses_the_selected_build_native_addresses(adapted_bridge, group, index):
    bridge, p, base = adapted_bridge
    assert bridge.click_slot(10, 20, group, index) == 1
    args = bridge._dispatch.call_args.args
    kind, slot, convert, get_frame, click, _, _, _ = OP_STRUCT.unpack(args[2])
    assert (kind, slot) == (1, (index << 16) | (7 if group == 'item' else 1))
    assert convert == base + p['protected_native_rvas']['ConvertOriginFrameType']
    assert get_frame == base + p['protected_native_rvas']['BlzGetOriginFrame']
    assert click == base + p['protected_native_rvas']['BlzFrameClick']


@pytest.mark.parametrize('group', list(SLOT_GROUP_SPECS))
def test_bad_slot_never_dispatches_in_any_build(adapted_bridge, group):
    bridge, _, _ = adapted_bridge
    width, height = SLOT_GROUP_SPECS[group]
    with pytest.raises(ValueError):
        bridge.click_slot(10, 20, group, width * height)
    bridge._dispatch.assert_not_called()


def test_whole_key_table_save_refresh_and_disable_use_selected_profile(adapted_bridge):
    bridge, p, base = adapted_bridge
    keys = tuple((r, c, 0x41 + r * 4 + c, 0) for r in range(3) for c in range(4))
    bridge.override_command_hotkeys(10, 20, keys)
    call = bridge._dispatch.call_args
    operations = call.args[2]
    assert len(operations) == 13
    for i, operation in enumerate(operations[:12]):
        kind, slot, setter, quick, hero, _, _, flags = OP_STRUCT.unpack(operation)
        r, c, key, meta = keys[i]
        assert kind == 4 and slot == r | (c << 8) | (key << 16) | (meta << 24)
        assert (setter, quick, hero) == tuple(base + p['command_bar']['functions'][name]
            for name in ['set_hotkey', 'set_hotkey_quick_cast', 'set_hotkey_hero_only'])
        assert flags == (4 if i == 11 else 0)
    refresh = OP_STRUCT.unpack(operations[-1])
    assert refresh[0] == 5
    assert refresh[2] == base + p['command_bar']['functions']['game_ui_get']
    assert refresh[3] == base + p['command_bar']['functions']['refresh_command_bar']
    assert call.kwargs['reserved_handle'] == base + p['command_bar']['functions']['save_hotkeys']
    bridge.set_command_hotkey_override_enabled(10, 20, False)
    assert OP_STRUCT.unpack(bridge._dispatch.call_args.args[2])[7] == 0


@pytest.mark.parametrize('group', list(SLOT_GROUP_SPECS))
@pytest.mark.parametrize('mode', ['normal', 'smartcast', 'self_cast'])
def test_action_modes_reach_version_selected_frames_without_real_input(adapted_bridge, group, mode):
    bridge, _, _ = adapted_bridge
    window = GameWindowSnapshot(hwnd=10, pid=20, foreground=True)
    guard = Mock()
    guard.snapshot.return_value = window
    engine = HotkeyEngine(default_profile(), guard=guard)
    engine.frame_bridge = bridge
    engine.sender = Mock()
    engine.sender.send_click.return_value = True
    engine._game_ready.set()
    binding = SimpleNamespace(config=BindingConfig('fixture', 'F1', 'Q', slot_index=0, group=group))
    action = BindingAction(binding=binding, modifiers=frozenset(), send_target=True,
                           smartcast=mode == 'smartcast', self_cast=mode == 'self_cast',
                           autocast_toggle=False)
    with patch('war3_hotkey_engine.time.sleep'):
        assert engine._execute_binding(action)
    calls = bridge._dispatch.call_args_list
    assert len(calls) == (2 if mode == 'self_cast' else 1)
    if mode == 'self_cast':
        assert OP_STRUCT.unpack(calls[-1].args[2])[1] == 16  # portrait, index 0
    elif mode == 'smartcast':
        engine.sender.send_click.assert_called_once_with('left')
    else:
        engine.sender.send_click.assert_not_called()


def test_autocast_releases_modifier_and_uses_mouse_sender_not_a_stale_native(adapted_bridge):
    bridge, _, _ = adapted_bridge
    guard = Mock()
    guard.snapshot.return_value = GameWindowSnapshot(hwnd=10, pid=20, foreground=True)
    guard.point_from_normalized.return_value = (800, 600)
    engine = HotkeyEngine(default_profile(), guard=guard)
    engine.frame_bridge = bridge
    engine.sender = Mock()
    engine.sender.send_click.return_value = True
    engine._game_ready.set()
    binding = SimpleNamespace(config=BindingConfig('fixture', 'F1', 'Q', slot_index=0, group='ability'))
    action = BindingAction(binding=binding, modifiers=frozenset({'SHIFT'}), send_target=False,
                           smartcast=False, self_cast=False, autocast_toggle=True)
    assert engine._execute_binding(action)
    engine.sender.send_click.assert_called_once_with('right', point=(800, 600), release_modifiers=frozenset({'SHIFT'}))
    bridge._dispatch.assert_not_called()


@pytest.mark.parametrize('old_version,new_version', list(permutations(VERSIONS, 2)))
def test_all_version_switches_replace_the_bridge_and_session(tmp_path, old_version, new_version):
    profiles = {p['game_version']: p for p in load_profiles()}
    for p in profiles.values():
        (tmp_path/p.get('bridge_file', 'war3_hotkey_bridge.dll')).touch()
    bridge = NativeFrameBridge(helper_path=tmp_path/'war3_hotkey_native_helper.dll')
    bridge.resolver.resolve = Mock(return_value={'ConvertOriginFrameType': NativeHandler('ConvertOriginFrameType', 1, 0x100000)})
    bridge.command_bar_resolver.resolve = Mock(return_value=CommandBarInternals(0x100000, 0x6c0, 0x2e8))
    def identity(version, created):
        p = profiles[version]
        fp = tuple(p['fingerprint'][k] for k in ('machine', 'timestamp', 'image_size'))
        return HotkeySessionIdentity(7, created, 0x140000000, fp, version, p)
    def window_thread(hwnd, owner):
        owner._obj.value = 7
        return 9
    with patch('war3_hotkey_native.ProcessMemory', return_value=Memory()), \
         patch('war3_hotkey_adapters.identify_process', return_value=identity(old_version, 1)) as current, \
         patch('war3_hotkey_native.user32.GetWindowThreadProcessId', side_effect=window_thread):
        bridge.connect(1, 7)
        assert bridge.shared_helper_path.name == profiles[old_version].get('bridge_file', 'war3_hotkey_bridge.dll')
        current.return_value = identity(new_version, 2)
        bridge.connect(1, 7)
        assert bridge.shared_helper_path.name == profiles[new_version].get('bridge_file', 'war3_hotkey_bridge.dll')
        assert bridge._session_identity.version == new_version
    bridge.close()


def test_all_profiles_keep_the_complete_native_contract():
    for p in load_profiles():
        assert set(p['natives']) == set(NATIVE_NAMES) == set(p['protected_native_rvas'])


def test_production_entrypoints_never_emit_historical_probe_operations():
    source = (ROOT/'war3_hotkey_native.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    bridge_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'NativeFrameBridge')
    import war3_hotkey_native as native
    kinds = set()
    for n in ast.walk(bridge_class):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == '_dispatch':
            kind = next((k.value for k in n.keywords if k.arg == 'expected_kind'), None)
            assert kind is not None
            kinds.add(kind.value if isinstance(kind, ast.Constant) else getattr(native, kind.id))
    assert kinds == {1, 2, 3, 4, 5, 6, 8}

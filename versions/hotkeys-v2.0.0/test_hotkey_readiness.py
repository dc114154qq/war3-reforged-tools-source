from unittest.mock import patch

from war3_hotkey_engine import HotkeyEngine, GameWindowSnapshot
from war3_hotkey_native import CommandContext, SelectionContext
from war3_hotkey_model import default_profile
from types import SimpleNamespace
from pathlib import Path
import json
import pytest


def run_initialization(foreground=False, ready=True, fail_write=False, change_profile=False):
    calls = []

    class Guard:
        def snapshot(self):
            return GameWindowSnapshot(hwnd=10, pid=20, foreground=foreground)

    class Bridge:
        ready = True

        def connect(self, *_):
            calls.append("connect")

        def query_game_ready(self, *_):
            calls.append("ready")
            if not ready:
                engine._stop_event.set()
            return ready

        def query_command_context(self, *_):
            calls.append("context")
            return CommandContext(False)

        def override_command_hotkeys(self, *_):
            calls.append("apply")
            if fail_write:
                engine._stop_event.set()
                raise RuntimeError("write rejected")
            if change_profile:
                engine.apply_profile(default_profile())

        def query_selection_context(self, *_):
            calls.append("selection")
            engine._stop_event.set()
            return SelectionContext(True, False, 0)

        def close(self):
            calls.append("close")

    engine = HotkeyEngine(default_profile(), guard=Guard(), frame_bridge=Bridge())
    engine._native_loop()
    return engine, calls


def test_background_match_runs_full_product_initialization():
    engine, calls = run_initialization()
    assert calls == ["connect", "ready", "context", "apply", "selection"]
    assert engine.game_ready
    states = []
    engine.on_state = states.append
    engine._publish_state()
    assert states == ["game_ready_background"]


def test_background_menu_does_not_write_hotkeys():
    engine, calls = run_initialization(ready=False)
    assert calls == ["connect", "ready", "close"]
    assert not engine.game_ready


def test_write_failure_is_error_not_match_waiting():
    engine, calls = run_initialization(fail_write=True)
    states = []
    engine.on_state = states.append
    engine._publish_state()
    assert states == ["game_error"]
    assert "write rejected" in engine.status_snapshot()["native_error"]
    assert not engine.game_ready
    assert calls[-1] == "close"


def test_profile_update_invalidates_previous_application():
    engine, _ = run_initialization()
    assert engine.game_ready
    engine.apply_profile(default_profile())
    assert not engine.game_ready


def test_profile_update_during_write_cannot_confirm_old_profile():
    engine, _ = run_initialization(change_profile=True)
    assert not engine.game_ready


def test_switching_to_tool_keeps_initialized_match_and_bridge():
    calls = []

    class Guard:
        reads = 0

        def snapshot(self):
            self.reads += 1
            if self.reads == 2:
                engine._stop_event.set()
            return GameWindowSnapshot(hwnd=10, pid=20, foreground=self.reads == 1)

    class Bridge:
        ready = True

        def connect(self, *_):
            calls.append("connect")

        def query_game_ready(self, *_):
            return True

        def query_command_context(self, *_):
            return CommandContext(False)

        def override_command_hotkeys(self, *_):
            calls.append("apply")

        def query_selection_context(self, *_):
            return SelectionContext(True, False, 0)

        def close(self):
            calls.append("close")

    engine = HotkeyEngine(default_profile(), guard=Guard(), frame_bridge=Bridge())
    engine._native_loop()
    assert engine.game_ready
    assert calls.count("apply") == 1
    assert "close" not in calls


def test_background_keyboard_input_still_passes_through():
    engine, _ = run_initialization()
    from war3_hotkey_engine import KBDLLHOOKSTRUCT, WM_KEYDOWN
    import ctypes
    engine.guard.is_foreground = lambda: False
    event = KBDLLHOOKSTRUCT(90, 0, 0, 0, 0)
    with patch("war3_hotkey_engine.user32.CallNextHookEx", return_value=777):
        assert engine._keyboard_callback(0, WM_KEYDOWN, ctypes.addressof(event)) == 777
    assert engine._actions.empty()


def test_diagnostic_window_selection_is_bound_to_requested_pid():
    from war3_hotkey_engine import WarcraftWindowGuard

    class User32:
        def EnumWindows(self, callback, _):
            callback(100, 0)
            callback(200, 0)

        def IsWindowVisible(self, _):
            return True

        def GetWindowThreadProcessId(self, hwnd, pointer):
            pointer._obj.value = 10 if hwnd == 100 else 20
            return 1

        def GetForegroundWindow(self):
            return 200

    guard = WarcraftWindowGuard(target_pid=10)
    guard._process_path = lambda _: r"C:\Games\Warcraft III.exe"
    guard._client_screen_rect = lambda _: (0, 0, 1920, 1080)
    with patch("war3_hotkey_engine.user32", User32()):
        assert guard._scan().pid == 10


@pytest.mark.parametrize("identity_pid", [20, 30])
def test_runtime_log_does_not_attribute_old_build_to_current_process(tmp_path, identity_pid):
    from war3_hotkey_tool import HotkeyToolApp
    bridge = SimpleNamespace(
        _session_identity=SimpleNamespace(pid=identity_pid, version="3.0.1.24323", created=123),
        _transport_report={"pid": identity_pid, "callback_verified": True, "safe_to_release": True},
        shared_helper_path=Path("war3_hotkey_bridge_301.dll"), _shared_transport=True,
    )
    app = SimpleNamespace(engine=SimpleNamespace(frame_bridge=bridge),
                          store=SimpleNamespace(path=tmp_path / "config.json"), _last_runtime_status="")
    state = {"game": GameWindowSnapshot(hwnd=10, pid=20), "game_ready": True,
             "running": True, "native_error": ""}
    HotkeyToolApp._write_runtime_status(app, state)
    record = json.loads((tmp_path / "runtime-status.json").read_text(encoding="utf-8"))
    assert record["game_pid"] == 20
    assert record["game_version"] == ("3.0.1.24323" if identity_pid == 20 else None)
    assert record["transport_matches_current_game"] == (identity_pid == 20)
    assert not (tmp_path / "runtime-status.json.tmp").exists()


def test_diagnostic_write_failure_does_not_stop_application(tmp_path):
    from war3_hotkey_tool import HotkeyToolApp
    bridge = SimpleNamespace(_session_identity=None, _transport_report=None,
                             _shared_transport=False, shared_helper_path=Path("bridge.dll"))
    app = SimpleNamespace(engine=SimpleNamespace(frame_bridge=bridge),
                          store=SimpleNamespace(path=tmp_path / "config.json"), _last_runtime_status="")
    state = {"game": GameWindowSnapshot(), "game_ready": False, "running": True, "native_error": ""}
    with patch.object(Path, "write_text", side_effect=PermissionError("read only")):
        HotkeyToolApp._write_runtime_status(app, state)
    assert app._last_runtime_status == ""


def test_duplicate_instance_exits_without_creating_a_second_tk_root():
    import ast
    source = Path("war3_hotkey_tool.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    duplicate = [node for node in ast.walk(main)
                 if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                 and any(isinstance(part, ast.Name) and part.id == "mutex" for part in ast.walk(node.test))]
    assert duplicate
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in {"Tk", "showinfo"}
                   for node in ast.walk(duplicate[0]))


def test_release_spec_collects_capstone_native_library():
    spec = Path(__file__).with_name("War3ReforgedHotkeys.spec").read_text(encoding="utf-8")
    assert "from PyInstaller.utils.hooks import collect_dynamic_libs" in spec
    assert "collect_dynamic_libs('capstone')" in spec


def test_missing_capstone_has_explicit_diagnostic_before_native_call():
    import builtins
    from war3_hotkey_adapters import game_native_context
    original_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "capstone":
            raise ImportError("ERROR: fail to load the dynamic library.")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=unavailable):
        with pytest.raises(RuntimeError, match="capstone.dll"):
            game_native_context(None, None, 0)


def test_hotkey_readback_uses_current_profile_getter_and_each_slot():
    import struct
    from war3_hotkey_native import NativeFrameBridge, HEADER_STRUCT, OP_STRUCT
    bridge = NativeFrameBridge()
    bridge._shared_transport = True
    bridge._session_identity = SimpleNamespace(base=0x100000, profile={"command_bar": {"get_hotkey_rva": 0x4321}})
    bridge.connect = lambda *_: None
    slots = tuple((row, column, 65 + row * 4 + column, column) for row in range(3) for column in range(4))
    data = HEADER_STRUCT.pack(0x4b485257, 4, 2, 12, 0, 0, 0)
    for row, column, key, meta in slots:
        result = int.from_bytes(bytes([key, meta, 0, 0, 0, 0, 0, 0]), "little")
        data += OP_STRUCT.pack(8, row | (column << 8), 0x104321, 0, 0, result, 0, 0)
    data += bytes(192)
    bridge._transport_report = {"work_result_hex": data.hex()}
    with patch.object(bridge, "_dispatch") as dispatch:
        assert bridge.read_command_hotkeys(1, 2) == slots
    operations = dispatch.call_args.args[2]
    assert len(operations) == 12
    assert all(OP_STRUCT.unpack(op)[2] == 0x104321 for op in operations)

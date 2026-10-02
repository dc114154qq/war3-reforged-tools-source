"""Profile relocation, typed registration and lifecycle regression coverage."""
import ctypes
from pathlib import Path
from types import SimpleNamespace
import struct
from unittest.mock import Mock, patch

import pytest

from war3_hotkey_adapters import (HotkeySessionIdentity, load_profiles, select_profile,
                                 resolve_native_list, validate_natives, resolve_command_bar)
from war3_hotkey_native import NativeHandler, NativeResolver, NativeFrameBridge, CommandBarInternals
from war3_hotkey_transport_context import prepare_operation, transport_scope, current_profile


class Memory:
    def __init__(self, base=0x140000000):
        self.base = base
        self.data = {}
        self.handle = 1
    def put(self, address, data):
        self.data.update({address+i:value for i,value in enumerate(data)})
    def read(self, address, size):
        try:
            return bytes(self.data[address+i] for i in range(size))
        except KeyError as exc:
            raise OSError('unmapped') from exc
    def read_u64(self,address):
        return struct.unpack('<Q',self.read(address,8))[0]
    def regions(self):
        return [SimpleNamespace(base=0x300000,size=4096,typ=0x20000,protect=4)]
    def __enter__(self): return self
    def __exit__(self,*args): pass


def fixture(base=0x140000000, handler_offset=48):
    profile = dict(schema_version=1, bridge_protocol=4, adapter_version=1,
        native_table=dict(table=40,head=24,terminal=16,next=32,name=40,handler=handler_offset,signature=64),
        metadata_sections=[dict(rva=0x2000,size=256)],
        natives={'GetLocalPlayer':'()Hplayer;','BlzFrameClick':'(Hframehandle;)V'})
    memory=Memory(base)
    memory.put(base+0x2000,b'\0'*256)
    memory.put(0x300000,b'\0'*4096)
    for index,(name,signature) in enumerate(profile['natives'].items()):
        address=base+0x2000+index*100
        memory.put(address,name.encode()+b'\0')
        memory.put(address+40,signature.encode()+b'\0')
        node=0x300080+index*128
        memory.put(node+32,struct.pack('<Q',node+128 if index==0 else 0x300039))
        memory.put(node+40,struct.pack('<Q',address))
        memory.put(node+handler_offset,struct.pack('<Q',base+0x1000+index*32))
        memory.put(node+64,struct.pack('<Q',address+40))
    memory.put(0x300040,struct.pack('<Q',0x300080))
    identity=HotkeySessionIdentity(7,123,base,(0x8664,1,0x10000),'3.0.0.test',profile)
    return memory,identity


@pytest.mark.parametrize('base,offset',[(0x140000000,48),(0x7ff100000000,56)])
def test_registry_relocation_and_layout_are_profile_driven(base,offset):
    memory,identity=fixture(base,offset)
    found=resolve_native_list(memory,identity,0x300000,identity.profile['natives'],NativeHandler,
                                lambda address:base+0x1000<=address<base+0x2000)
    assert found['GetLocalPlayer'].handler_address==base+0x1000
    assert found['BlzFrameClick'].handler_address==base+0x1020


def test_native_signature_mismatch_is_not_a_callable_candidate():
    memory,identity=fixture()
    memory.put(identity.base+0x2000+40,b'()I\0')
    with pytest.raises(RuntimeError,match='签名不匹配'):
        resolve_native_list(memory,identity,0x300000,identity.profile['natives'],NativeHandler,lambda _:True)


def test_duplicate_name_with_different_handler_is_rejected():
    memory,identity=fixture()
    node=0x300800
    memory.put(0x300100+32,struct.pack('<Q',node))
    memory.put(node+32,struct.pack('<Q',0x300039))
    for offset,value in ((40,identity.base+0x2000),(48,identity.base+0x1100),(64,identity.base+0x2028)):
        memory.put(node+offset,struct.pack('<Q',value))
    with pytest.raises(RuntimeError,match='名称重复'):
        resolve_native_list(memory,identity,0x300000,identity.profile['natives'],NativeHandler,lambda _:True)


def test_retired_registration_is_detected_before_reuse():
    memory,identity=fixture()
    found=resolve_native_list(memory,identity,0x300000,identity.profile['natives'],NativeHandler,lambda _:True)
    memory.put(found['GetLocalPlayer'].record_address+48,struct.pack('<Q',identity.base+0x1100))
    with pytest.raises(RuntimeError,match='注册已变化'):
        validate_natives(memory,found,identity.profile,lambda _:True)


def test_supported_build_and_unknown_build_never_share_a_profile():
    profiles=load_profiles()
    profile=profiles[0]
    fp=tuple(profile['fingerprint'][k] for k in ('machine','timestamp','image_size'))
    assert select_profile(fp,3,profiles) is profile
    with pytest.raises(RuntimeError,match='不会沿用'):
        select_profile((fp[0],fp[1]+1,fp[2]),3,profiles)
    assert select_profile((fp[0],1,0x800000),2,profiles) is None


def test_public_301_build_selects_its_own_shared_bridge_profile():
    profiles=load_profiles()
    profile=select_profile((0x8664,1790661601,236408832),3,profiles)
    assert profile['game_version']=='3.0.1.24323'
    assert profile['bridge_file']=='war3_hotkey_bridge_301.dll'
    assert profile['command_bar']['functions']['set_hotkey']==0xf5b410
    assert profile['command_bar']['guarded_call']['return_rva']==0x160050


def test_300_profile_stays_on_shared_transport():
    profiles=load_profiles()
    profile=select_profile((0x8664,1789189744,236277760),3,profiles)
    assert profile['game_version']=='3.0.0.24268'
    assert profile.get('transport') is None


def test_301_native_addresses_are_independent_of_300():
    profiles=load_profiles()
    old=select_profile((0x8664,1789189744,236277760),3,profiles)
    new=select_profile((0x8664,1790661601,236408832),3,profiles)
    assert new['natives']==old['natives']
    assert new['native_context']['tls_index_rva']!=old['native_context']['tls_index_rva']
    assert set(new['protected_native_rvas'])==set(old['protected_native_rvas'])
    assert all(new['protected_native_rvas'][n]!=old['protected_native_rvas'][n]
               for n in new['protected_native_rvas'])
    with pytest.raises(RuntimeError,match='不会沿用'):
        select_profile((0x8664,1790661602,236408832),3,profiles)


def test_301_deferred_code_check_does_not_accept_mismatched_readable_code():
    memory,identity=fixture()
    profile=select_profile((0x8664,1790661601,236408832),3,load_profiles())
    identity=HotkeySessionIdentity(identity.pid,identity.created,identity.base,
                                  identity.fingerprint,'3.0.1.24323',profile)
    flag=Mock(return_value=None)
    for check in profile['command_bar']['checks']:
        memory.put(identity.base+check['rva'],bytes.fromhex(check['bytes']))
    result=resolve_command_bar(memory,identity,flag)
    assert result['set_hotkey']==identity.base+0xf5b410
    check=profile['command_bar']['checks'][0]
    memory.put(identity.base+check['rva'],bytes(len(bytes.fromhex(check['bytes']))))
    with pytest.raises(RuntimeError,match='代码校验失败'):
        resolve_command_bar(memory,identity,flag)


def test_switching_from_301_to_300_resets_the_bridge_module(tmp_path):
    profiles=load_profiles()
    _,base_identity=fixture()
    old=select_profile((0x8664,1789189744,236277760),3,profiles)
    new=select_profile((0x8664,1790661601,236408832),3,profiles)
    identity=HotkeySessionIdentity(7,123,base_identity.base,(0x8664,1790661601,236408832),'3.0.1.24323',new)
    (tmp_path/'war3_hotkey_bridge_301.dll').touch()
    (tmp_path/'war3_hotkey_bridge.dll').touch()
    bridge=NativeFrameBridge(helper_path=tmp_path/'war3_hotkey_native_helper.dll')
    bridge.resolver.resolve=Mock(return_value={'ConvertOriginFrameType':NativeHandler('ConvertOriginFrameType',1,0x100000)})
    bridge.command_bar_resolver.resolve=Mock(return_value=CommandBarInternals(0x100000,0x6c0,0x2e8))
    def window_thread(hwnd,owner):
        owner._obj.value=7
        return 9
    with patch('war3_hotkey_native.ProcessMemory',return_value=Memory(base_identity.base)), \
         patch('war3_hotkey_adapters.identify_process',return_value=identity) as identify, \
         patch('war3_hotkey_native.user32.GetWindowThreadProcessId',side_effect=window_thread):
        bridge.connect(1,7)
        assert bridge._shared_transport
        assert bridge.shared_helper_path.name=='war3_hotkey_bridge_301.dll'
        identify.return_value=HotkeySessionIdentity(7,124,base_identity.base,(0x8664,1789189744,236277760),'3.0.0.24268',old)
        bridge.connect(1,7)
        assert bridge._shared_transport
        assert bridge.shared_helper_path.name=='war3_hotkey_bridge.dll'
    bridge.close()


def test_pid_reuse_cannot_share_session_identity():
    _,identity=fixture()
    other=HotkeySessionIdentity(identity.pid,124,identity.base,identity.fingerprint,identity.version,identity.profile)
    assert other.key!=identity.key


def test_command_bar_checks_precede_exposing_write_dependencies():
    memory,identity=fixture()
    identity.profile['command_bar']=dict(functions={'game_ui_get':0x5000},
        command_bar_offset=0x6c0,submenu_link_offset=0x2e8,
        checks=[dict(rva=0x4000,bytes='488bc8')])
    memory.put(identity.base+0x4000,bytes.fromhex('488bc8'))
    flag=Mock(return_value=None)
    result=resolve_command_bar(memory,identity,flag)
    assert result['game_ui_get']==identity.base+0x5000
    assert result['overriding_hotkey_enabled'] is None
    memory.put(identity.base+0x4000,b'\0\0\0')
    flag.reset_mock()
    with pytest.raises(RuntimeError,match='代码校验失败'):
        resolve_command_bar(memory,identity,flag)
    flag.assert_not_called()


def test_unresolved_coverage_switch_does_not_block_native_table_dispatch():
    _,identity=fixture()
    bridge=NativeFrameBridge()
    bridge.connect=Mock()
    bridge._session_identity=identity
    bridge._command_bar=CommandBarInternals(0x100000,0x6c0,0x2e8,
        0x100010,0x100020,0x100030,0x100040,0x100050,None)
    bridge._dispatch=Mock()
    bridge.override_command_hotkeys(1,7,[(r,c,65,0) for r in range(3) for c in range(4)])
    bridge._dispatch.assert_called_once()


def test_packaging_includes_only_data_adapter_files():
    spec=Path('War3ReforgedHotkeys.spec').read_text(encoding='utf-8')
    assert "('hotkey_profiles/*.json', 'hotkey_profiles')" in spec
    assert '.py' not in str(load_profiles()[0]['command_bar'])


def command_payload(kind=6, count=1):
    return struct.pack('<4IQ2I',0x4b485257,4,1,count,0,0,0) + struct.pack('<II5Q',kind,0,0,0,0,0,0) + bytes(720)


def test_transport_context_does_not_leak_between_sessions():
    _, identity = fixture()
    with pytest.raises(RuntimeError,match='No verified'):
        current_profile()
    with transport_scope(identity):
        assert len(current_profile().bridge_bytes()) == 52
    with pytest.raises(RuntimeError,match='No verified'):
        current_profile()


@pytest.mark.parametrize('payload',[command_payload(3), command_payload(99), command_payload()[:-1]])
def test_malformed_transport_blocks_are_rejected_before_loading(payload):
    with pytest.raises(ValueError):
        prepare_operation('hotkey',payload)


def test_uncertain_dispatch_quarantines_process_incarnation_without_replay():
    _,identity=fixture()
    bridge=NativeFrameBridge()
    bridge._shared_transport=True
    bridge._session_identity=identity
    bridge._thread_id=9
    identity.profile['native_context']={'tls_index_rva':0x4000}
    memory=Memory(identity.base)
    memory.put(identity.base+0x4000,struct.pack('<I',1))
    operation=struct.pack('<II5Q',6,0,0x100000,0,0,0,0)
    transport=Mock(return_value={'safe_to_release':False,'callback_received':False})
    with patch('war3_hotkey_native.ProcessMemory',return_value=memory), \
         patch('war3_hotkey_adapters.identify_process',return_value=identity), \
         patch('war3_hotkey_transport.dispatch',transport):
        with pytest.raises(RuntimeError,match='隔离'):
            bridge._dispatch(1,7,operation,expected_kind=6,operation_name='test',timeout_ms=500)
        bridge.close()
        bridge._shared_transport=True
        bridge._session_identity=identity
        with pytest.raises(RuntimeError,match='隔离'):
            bridge._dispatch(1,7,operation,expected_kind=6,operation_name='test',timeout_ms=500)
    assert transport.call_count==1


def test_retry_never_replays_a_delivered_business_callback():
    import war3_hotkey_transport as transport
    first={'safe_to_release':True,'callback_received':True,
           'after_cleanup':{'callback_count':1,'query_stage':2,'exception_code':'0x0'}}
    with patch.object(transport,'_dispatch_once',return_value=first) as operation:
        assert transport.dispatch(7,1,9,Path('unused.dll'),1,bytes(800),'hotkey') is first
    assert operation.call_count==1

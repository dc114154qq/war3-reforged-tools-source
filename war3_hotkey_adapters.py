"""Build-selected hotkey link adapters; contains no UI or binding policy."""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import sys


@dataclass(frozen=True)
class HotkeySessionIdentity:
    pid: int
    created: int
    base: int
    fingerprint: tuple[int, int, int]
    version: str
    profile: dict | None

    @property
    def key(self):
        return self.pid, self.created, self.base, self.fingerprint


def read_exact(memory, address, size):
    chunks = []
    offset = 0
    while offset < size:
        chunk_size = min(size - offset, 0x1000 - ((address + offset) & 0xfff))
        try:
            data = memory.read(address + offset, chunk_size)
            if len(data) != chunk_size:
                raise OSError('partial read')
        except OSError:
            # Protected/transition pages can return ERROR_PARTIAL_COPY even
            # when the bytes used by a profile check are readable. Preserve
            # exactness while allowing the caller to distinguish a real gap.
            pieces = []
            for index in range(chunk_size):
                piece = memory.read(address + offset + index, 1)
                if len(piece) != 1:
                    raise RuntimeError('改键适配读取不完整')
                pieces.append(piece)
            data = b''.join(pieces)
        chunks.append(data)
        offset += chunk_size
    return b''.join(chunks)


def read_string(memory, address):
    if not 0x10000 <= address < 0x800000000000:
        raise RuntimeError('Native 字符串地址无效')
    out = bytearray()
    while len(out) < 256:
        current = address + len(out)
        size = min(64, 256-len(out), 0x1000-(current & 0xfff))
        try:
            block = read_exact(memory, current, size)
        except OSError:
            block = read_exact(memory, current, 1)
        end = block.find(b'\0')
        out.extend(block if end < 0 else block[:end])
        if end >= 0:
            return out.decode('ascii')
    raise RuntimeError('Native 字符串超过读取边界')


def load_profiles():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    profiles = []
    for path in sorted((root / 'hotkey_profiles').glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        if data['schema_version'] != 1 or data['bridge_protocol'] != 4:
            raise RuntimeError('改键适配数据或桥协议版本不匹配')
        fp = data['fingerprint']
        if set(fp) != {'machine', 'timestamp', 'image_size'}:
            raise RuntimeError('改键适配指纹不完整')
        profiles.append(data)
    return profiles


def select_profile(fingerprint, game_major, profiles):
    matches = [p for p in profiles if tuple(p['fingerprint'][k] for k in
               ('machine', 'timestamp', 'image_size')) == fingerprint]
    if len(matches) > 1:
        raise RuntimeError('同一游戏构建存在多个改键适配包')
    if matches:
        return matches[0]
    if fingerprint[0] != 0x8664 or game_major >= 3:
        raise RuntimeError('此游戏构建尚无改键适配包；不会沿用旧版地址执行')
    return None  # The existing pre-3.0 signature resolver remains unchanged.


_build_cache = {}


def identify_process(memory, pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetProcessTimes.argtypes = (ctypes.c_void_p,) + (ctypes.c_void_p,) * 4
    kernel.GetProcessTimes.restype = ctypes.c_int
    times = [ctypes.c_uint64() for _ in range(4)]
    if not kernel.GetProcessTimes(memory.handle, *(ctypes.byref(t) for t in times)):
        raise ctypes.WinError(ctypes.get_last_error())
    modules = (ctypes.c_void_p * 1024)()
    needed = ctypes.c_ulong()
    enum = kernel.K32EnumProcessModules
    enum.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p)
    enum.restype = ctypes.c_int
    if not enum(memory.handle, modules, ctypes.sizeof(modules), ctypes.byref(needed)) or not modules[0]:
        raise RuntimeError('无法识别游戏主模块')
    base = int(modules[0])
    header = read_exact(memory, base, 4096)
    nt = struct.unpack_from('<I', header, 60)[0]
    if header[:2] != b'MZ' or nt > len(header) - 88 or header[nt:nt+4] != b'PE\0\0':
        raise RuntimeError('游戏 PE 构建身份无效')
    fp = (struct.unpack_from('<H', header, nt+4)[0],
          struct.unpack_from('<I', header, nt+8)[0],
          struct.unpack_from('<I', header, nt+80)[0])
    key = (int(pid), times[0].value, base, fp)
    cached = _build_cache.get(key)
    if cached is not None:
        return cached
    filename = ctypes.create_unicode_buffer(32768)
    length = ctypes.c_ulong(len(filename))
    kernel.QueryFullProcessImageNameW.argtypes = (ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.c_void_p)
    kernel.QueryFullProcessImageNameW.restype = ctypes.c_int
    if not kernel.QueryFullProcessImageNameW(memory.handle, 0, filename, ctypes.byref(length)):
        raise ctypes.WinError(ctypes.get_last_error())
    import pefile
    disk = pefile.PE(filename.value, fast_load=True)
    if (disk.FILE_HEADER.Machine, disk.FILE_HEADER.TimeDateStamp, disk.OPTIONAL_HEADER.SizeOfImage) != fp:
        raise RuntimeError('磁盘和进程中的游戏构建身份不一致')
    disk.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
    fixed = disk.VS_FIXEDFILEINFO[0]
    parts = (fixed.FileVersionMS >> 16, fixed.FileVersionMS & 65535,
             fixed.FileVersionLS >> 16, fixed.FileVersionLS & 65535)
    profile = select_profile(fp, parts[0], load_profiles())
    identity = HotkeySessionIdentity(int(pid), times[0].value, base, fp,
                                     '.'.join(map(str, parts)), profile)
    # Retain identities only for the current incarnation of this PID.
    for old in tuple(_build_cache):
        if old[0] == pid:
            _build_cache.pop(old)
    _build_cache[key] = identity
    return identity


def validate_natives(memory, handlers, profile, executable):
    layout = profile['native_table']
    for name, entry in handlers.items():
        pointer = memory.read_u64(entry.record_address + layout['handler'])
        name_ptr = memory.read_u64(entry.record_address + layout['name'])
        signature_ptr = memory.read_u64(entry.record_address + layout['signature'])
        protected=profile.get('protected_native_rvas',{}).get(name)
        guarded=protected is not None and pointer==getattr(memory,'game_base',0)+protected
        if (pointer != entry.handler_address or not (executable(pointer) or guarded)
                or read_string(memory, name_ptr) != name
                or read_string(memory, signature_ptr) != profile['natives'][name]):
            raise RuntimeError('Native 注册已变化，需要重新连接：' + name)


def game_native_context(memory, identity, hwnd=None):
    """Read the actual window-thread TLS registration root, without scanning heaps."""
    import time
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    from capstone.x86 import X86_OP_MEM, X86_OP_REG, X86_REG_GS, X86_REG_RCX
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.GetWindowThreadProcessId.argtypes=(ctypes.c_void_p,ctypes.c_void_p)
    user.GetWindowThreadProcessId.restype=ctypes.c_ulong
    if hwnd is None:
        windows=[]
        callback_type=ctypes.WINFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_ssize_t)
        def collect(window,_):
            owner=ctypes.c_ulong()
            tid=user.GetWindowThreadProcessId(window,ctypes.byref(owner))
            if owner.value==identity.pid and tid:
                windows.append((int(window),int(tid)))
            return 1
        user.EnumWindows.argtypes=(callback_type,ctypes.c_ssize_t)
        callback=callback_type(collect)
        user.EnumWindows(callback,0)
        if not windows:raise RuntimeError('游戏窗口尚未建立，无法读取 Native 上下文')
        hwnd=windows[0][0]
    owner=ctypes.c_ulong()
    tid=int(user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner)))
    if not tid or owner.value!=identity.pid:raise RuntimeError('Native 上下文窗口身份不匹配')
    kernel.OpenThread.argtypes=(ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong)
    kernel.OpenThread.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=(ctypes.c_void_p,)
    handle=kernel.OpenThread(0x40,False,tid)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    try:
        query=ctypes.WinDLL('ntdll').NtQueryInformationThread
        query.argtypes=(ctypes.c_void_p,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_void_p)
        query.restype=ctypes.c_long
        basic=(ctypes.c_uint64*6)()
        status=query(handle,0,ctypes.byref(basic),ctypes.sizeof(basic),None)
        if status<0 or (basic[2],basic[3])!=(identity.pid,tid):raise RuntimeError('游戏线程创建身份查询失败')
        teb=basic[1]
    finally:kernel.CloseHandle(handle)
    primary,expansion=set(),set()
    for library in (kernel,ctypes.WinDLL('kernelbase')):
        address=ctypes.cast(library.TlsGetValue,ctypes.c_void_p).value
        cs=Cs(CS_ARCH_X86,CS_MODE_64);cs.detail=True;teb_registers=set()
        primary.clear();expansion.clear()
        for ins in cs.disasm(ctypes.string_at(address,128),0):
            if len(ins.operands)!=2 or ins.operands[1].type!=X86_OP_MEM:continue
            mem=ins.operands[1].mem
            direct=mem.segment==X86_REG_GS and mem.base==0
            indirect=mem.base in teb_registers and mem.segment==0
            if direct and not mem.index and mem.disp==0x30 and ins.operands[0].type==X86_OP_REG:
                teb_registers.add(ins.operands[0].reg)
            if not (direct or indirect) or not 0x1000<=mem.disp<=0x4000:continue
            if mem.index==X86_REG_RCX and mem.scale==8:primary.add(mem.disp)
            elif not mem.index:expansion.add(mem.disp)
        if len(primary)==len(expansion)==1:break
    if len(primary)!=1 or len(expansion)!=1:raise RuntimeError('当前 Windows TLS 访问布局尚未识别')
    layout=identity.profile['native_context']
    deadline=time.perf_counter()+0.3
    while True:
        index=struct.unpack('<I',read_exact(memory,identity.base+layout['tls_index_rva'],4))[0]
        if index>=1088:raise RuntimeError('游戏 TLS 索引超出 Windows 范围')
        table=teb+next(iter(primary)) if index<64 else memory.read_u64(teb+next(iter(expansion)))
        slot=table+(index if index<64 else index-64)*8 if table else 0
        tls=memory.read_u64(slot) if slot else 0
        context=memory.read_u64(tls+layout['native_slot']) if tls else 0
        if context and memory.read_u64(slot)==tls:
            return tid,tls,context
        if time.perf_counter()>=deadline:raise RuntimeError('游戏当前没有稳定的 Native 上下文；请进入地图后重试')
        time.sleep(0.005)


def resolve_native_list(memory,identity,context,names,handler_type,executable):
    layout=identity.profile['native_table']
    table=context+layout['table'];terminal=(table+layout['terminal'])|1
    head=memory.read_u64(table+layout['head'])
    node=head;visited=set();found={};wanted=set(names)
    for _ in range(8192):
        if node==terminal:break
        if node in visited or not 0x10000<=node<0x800000000000:
            raise RuntimeError('Native 注册链表失效或包含循环')
        visited.add(node)
        data=read_exact(memory,node,max(layout.values())+8)
        qword=lambda field:struct.unpack_from('<Q',data,layout[field])[0]
        name=read_string(memory,qword('name'))
        if name in wanted:
            handler=qword('handler')
            protected=identity.profile.get('protected_native_rvas',{}).get(name)
            guarded=protected is not None and handler==identity.base+protected
            if not (executable(handler) or guarded) or read_string(memory,qword('signature'))!=identity.profile['natives'][name]:
                raise RuntimeError('Native 调用签名不匹配：'+name)
            if name in found:raise RuntimeError('Native 注册名称重复：'+name)
            found[name]=handler_type(name,node,handler)
        node=qword('next')
    else:raise RuntimeError('Native 注册链表超过读取边界')
    if memory.read_u64(table+layout['head'])!=head:raise RuntimeError('读取过程中 Native 注册上下文变化')
    if set(found)!=wanted:raise RuntimeError('Native 注册缺失：'+', '.join(sorted(wanted-set(found))))
    memory.game_base=identity.base
    validate_natives(memory,found,identity.profile,executable)
    return found


def resolve_command_bar(memory, identity, enabled_resolver):
    profile = identity.profile
    config = profile['command_bar']
    deferred = False
    for check in config['checks']:
        expected = bytes.fromhex(check['bytes'])
        try:
            actual = read_exact(memory, identity.base+check['rva'], len(expected))
        except (OSError, RuntimeError):
            # The current 3.0 protected image can deny an external read of a
            # code page even though the profile's exact build is confirmed.
            # The bridge still validates the callable in the game thread.
            if profile.get('game_version') != '3.0.0.24268':
                raise RuntimeError('3.0.0 命令栏代码校验读取失败；不会使用旧版偏移')
            deferred = True
            continue
        if actual != expected:
            raise RuntimeError('3.0.0 命令栏代码校验失败；不会使用旧版偏移')
    values = {name: identity.base+rva for name, rva in config['functions'].items()}
    values.update(command_bar_offset=config['command_bar_offset'],
                  submenu_link_offset=config['submenu_link_offset'])
    values['overriding_hotkey_enabled'] = None if deferred else enabled_resolver(memory, identity)
    values['validation_deferred'] = deferred
    return values

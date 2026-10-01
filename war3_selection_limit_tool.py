"""Standalone Warcraft III Reforged 24-unit selection limit patcher."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import BOTH, DISABLED, NORMAL, Button, Frame, Label, Tk, messagebox
from ctypes import wintypes


APP_TITLE = "Warcraft III 24 Unit Groups"
LIMIT = 24
WH_CALLWNDPROC = 4
WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DWORD_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t

MAGIC = 0x4C533357
PROTOCOL_VERSION = 27
STATUS_PENDING = 1
STATUS_OK = 2
ACTION_QUERY = 0
ACTION_ENABLE = 1
ACTION_DISABLE = 2
ACTION_DIAGNOSTIC = 3
STATE_UNKNOWN = 0
STATE_DISABLED = 1
STATE_ENABLED = 2
PATCH_COUNT = 14
UINT32_MAX = 0xFFFFFFFF

COMMAND_STRUCT = struct.Struct("<14I46Q")
PATCH_NAMES = (
    "本地选择上限",
    "选择命令上限",
    "选择剩余容量",
    "同步编队保存",
    "本地编队保存",
    "头像网格行数",
    "头像网格列数",
    "头像构造循环",
    "头像初始化循环",
    "头像析构循环",
    "头像刷新外层",
    "头像刷新内层",
    "选择命令输入上限",
    "拖框剩余选择容量",
)


if sys.platform != "win32":
    raise RuntimeError("This tool requires Windows")


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
)
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.LoadLibraryW.argtypes = (wintypes.LPCWSTR,)
kernel32.LoadLibraryW.restype = wintypes.HMODULE
kernel32.GetProcAddress.argtypes = (wintypes.HMODULE, ctypes.c_char_p)
kernel32.GetProcAddress.restype = ctypes.c_void_p
kernel32.FreeLibrary.argtypes = (wintypes.HMODULE,)
kernel32.FreeLibrary.restype = wintypes.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.SetWindowsHookExW.argtypes = (
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.HINSTANCE,
    wintypes.DWORD,
)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.SendMessageTimeoutW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(DWORD_PTR),
)
user32.SendMessageTimeoutW.restype = LRESULT


@dataclass(frozen=True)
class WarcraftWindow:
    hwnd: int
    pid: int
    path: str


@dataclass(frozen=True)
class PatchResult:
    state: int
    patch_count: int
    failed_patch: int
    patch_addresses: tuple[int, ...]
    breakpoint_addresses: tuple[int, ...]
    selected_count: int
    breakpoint_mode: int
    breakpoint_thread_id: int
    hit_counts: tuple[int, ...]
    diagnostic_hits: tuple[int, ...]
    diagnostic_context: tuple[int, ...]
    selection_manager: int

    @property
    def enabled(self) -> bool:
        return self.state == STATE_ENABLED


def _process_path(pid: int) -> str | None:
    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    try:
        capacity = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(capacity.value)
        if not kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(capacity)):
            return None
        return buffer.value
    finally:
        kernel32.CloseHandle(process)


def find_warcraft_window(*, include_hidden: bool = False) -> WarcraftWindow | None:
    candidates: list[WarcraftWindow] = []

    @WNDENUMPROC
    def callback(hwnd: int, _lparam: int) -> bool:
        if not include_hidden and not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        if not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
            return True
        path = _process_path(int(pid.value))
        if path and Path(path).name.casefold() == "warcraft iii.exe":
            candidates.append(WarcraftWindow(int(hwnd), int(pid.value), path))
        return True

    if not user32.EnumWindows(callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return candidates[0] if candidates else None


class SelectionLimitError(RuntimeError):
    def __init__(self, message: str, *, error_code: int = 0, failed_patch: int = UINT32_MAX):
        super().__init__(message)
        self.error_code = int(error_code)
        self.failed_patch = int(failed_patch)


class SelectionLimitBridge:
    def __init__(self, helper_path: Path | None = None):
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        self.helper_path = helper_path or root / "tools" / "war3_selection_limit_helper_v27.dll"
        self.hwnd = 0
        self.pid = 0
        self.module = 0
        self.hook = 0
        self.thread_id = 0
        self.configure_proc = 0
        self.configure_process_proc = 0
        self.configure_auxiliary_proc = 0
        self.breakpoint_addresses: tuple[int, ...] = ()
        self.auxiliary_breakpoint_addresses: tuple[int, int] = ()
        self.diagnostic_process_wide = False
        self._lock = threading.RLock()

    @property
    def ready(self) -> bool:
        return bool(self.hwnd and self.pid and self.module and self.hook)

    def _command_path(self) -> Path:
        return self.helper_path.resolve().parent / f"war3_selection_limit_{self.pid}.bin"

    def connect(self, target: WarcraftWindow) -> None:
        with self._lock:
            if self.ready and self.pid == target.pid and self.hwnd == target.hwnd:
                return
            self.close(restore=True)
            if not self.helper_path.exists():
                raise SelectionLimitError(f"缺少补丁组件：{self.helper_path}")
            module = int(kernel32.LoadLibraryW(str(self.helper_path)) or 0)
            if not module:
                raise ctypes.WinError(ctypes.get_last_error())
            hook = 0
            try:
                procedure = int(
                    kernel32.GetProcAddress(module, b"War3SelectionLimitHookProc") or 0
                )
                if not procedure:
                    raise ctypes.WinError(ctypes.get_last_error())
                configure_proc = int(
                    kernel32.GetProcAddress(
                        module, b"War3SelectionLimitConfigureBreakpoints"
                    )
                    or 0
                )
                if not configure_proc:
                    raise ctypes.WinError(ctypes.get_last_error())
                configure_process_proc = int(
                    kernel32.GetProcAddress(
                        module, b"War3SelectionLimitConfigureProcessBreakpoints"
                    )
                    or 0
                )
                if not configure_process_proc:
                    raise ctypes.WinError(ctypes.get_last_error())
                configure_auxiliary_proc = int(
                    kernel32.GetProcAddress(
                        module, b"War3SelectionLimitConfigureAuxiliaryBreakpoints"
                    )
                    or 0
                )
                if not configure_auxiliary_proc:
                    raise ctypes.WinError(ctypes.get_last_error())
                actual_pid = wintypes.DWORD()
                thread_id = int(
                    user32.GetWindowThreadProcessId(target.hwnd, ctypes.byref(actual_pid))
                )
                if not thread_id or int(actual_pid.value) != target.pid:
                    raise SelectionLimitError("Warcraft III 窗口已经失效")
                hook = int(
                    user32.SetWindowsHookExW(
                        WH_CALLWNDPROC,
                        procedure,
                        module,
                        thread_id,
                    )
                    or 0
                )
                if not hook:
                    raise ctypes.WinError(ctypes.get_last_error())
            except Exception:
                if hook:
                    user32.UnhookWindowsHookEx(hook)
                kernel32.FreeLibrary(module)
                raise
            self.hwnd = target.hwnd
            self.pid = target.pid
            self.module = module
            self.hook = hook
            self.thread_id = thread_id
            self.configure_proc = configure_proc
            self.configure_process_proc = configure_process_proc
            self.configure_auxiliary_proc = configure_auxiliary_proc

    def query(self) -> PatchResult:
        return self._dispatch(ACTION_QUERY)

    @classmethod
    def query_existing(cls, target: WarcraftWindow) -> PatchResult:
        bridge = cls()
        bridge.hwnd = target.hwnd
        bridge.pid = target.pid
        return bridge._dispatch(ACTION_QUERY, require_connected=False)

    def enable(self) -> PatchResult:
        result = self._dispatch(ACTION_ENABLE)
        if not any(result.breakpoint_addresses):
            self.breakpoint_addresses = ()
            return result
        try:
            self._configure_process_breakpoints(
                result.breakpoint_addresses,
                True,
            )
        except Exception:
            try:
                self._configure_process_breakpoints(
                    result.breakpoint_addresses,
                    False,
                )
            except Exception:
                pass
            try:
                self._dispatch(ACTION_DISABLE)
            except Exception:
                pass
            raise
        self.breakpoint_addresses = result.breakpoint_addresses
        self.diagnostic_process_wide = True
        return result

    def disable(self) -> PatchResult:
        try:
            if not self.breakpoint_addresses:
                pass
            elif self.diagnostic_process_wide:
                self._configure_process_breakpoints(self.breakpoint_addresses, False)
            else:
                self._configure_breakpoints(self.breakpoint_addresses, False)
        finally:
            result = self._dispatch(ACTION_DISABLE)
            self.breakpoint_addresses = ()
            self.diagnostic_process_wide = False
        return result

    def configure_diagnostics(self, addresses: tuple[int, ...]) -> PatchResult:
        if not 1 <= len(addresses) <= 4:
            raise ValueError("diagnostic breakpoint count must be between 1 and 4")
        padded = addresses + (0,) * (4 - len(addresses))
        result = self._dispatch(
            ACTION_DIAGNOSTIC,
            diagnostic_addresses=padded,
        )
        try:
            self._configure_process_breakpoints(padded, True)
        except Exception:
            try:
                self._configure_process_breakpoints(padded, False)
            finally:
                self._dispatch(ACTION_DISABLE)
            raise
        self.breakpoint_addresses = padded
        self.diagnostic_process_wide = True
        return result

    def _configure_breakpoints(self, addresses: tuple[int, ...], enable: bool) -> None:
        if not self.ready or not self.configure_proc or not self.thread_id:
            return
        function_type = ctypes.WINFUNCTYPE(
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_uint32,
            ctypes.c_int,
        )
        configure = function_type(self.configure_proc)
        values = (ctypes.c_uint64 * 4)(*(addresses if enable else (0, 0, 0, 0)))
        error = int(configure(self.thread_id, values, 4 if enable else 0, int(enable)))
        if error:
            raise ctypes.WinError(error)

    def _configure_process_breakpoints(
        self,
        addresses: tuple[int, ...],
        enable: bool,
    ) -> None:
        if not self.ready or not self.configure_process_proc or not self.pid:
            return
        function_type = ctypes.WINFUNCTYPE(
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_uint32,
            ctypes.c_int,
        )
        configure = function_type(self.configure_process_proc)
        values = (ctypes.c_uint64 * 4)(*(addresses if enable else (0, 0, 0, 0)))
        error = int(configure(self.pid, values, 4 if enable else 0, int(enable)))
        if error:
            raise ctypes.WinError(error)

    def _configure_auxiliary_breakpoints(
        self,
        frame_address: int,
        input_address: int,
        enable: bool,
    ) -> None:
        if not self.ready or not self.configure_auxiliary_proc or not self.thread_id:
            return
        function_type = ctypes.WINFUNCTYPE(
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint64,
            ctypes.c_uint64,
            ctypes.c_int,
        )
        configure = function_type(self.configure_auxiliary_proc)
        error = int(
            configure(
                self.pid,
                self.thread_id,
                frame_address,
                input_address,
                int(enable),
            )
        )
        if error:
            raise ctypes.WinError(error)

    def _dispatch(
        self,
        action: int,
        *,
        timeout_ms: int = 8000,
        require_connected: bool = True,
        diagnostic_addresses: tuple[int, ...] = (),
    ) -> PatchResult:
        with self._lock:
            if not self.hwnd or not self.pid or (require_connected and not self.ready):
                raise SelectionLimitError("尚未连接 Warcraft III")
            command_path = self._command_path()
            qwords = [0] * 46
            for index, address in enumerate(diagnostic_addresses[:4]):
                qwords[36 + index] = int(address)
            values = (
                MAGIC,
                PROTOCOL_VERSION,
                STATUS_PENDING,
                int(action),
                LIMIT,
                STATE_UNKNOWN,
                0,
                0,
                UINT32_MAX,
                0,
                0,
                0,
                0,
                0,
                *qwords,
            )
            payload = COMMAND_STRUCT.pack(*values)
            with command_path.open("wb") as command_file:
                command_file.write(payload)
                command_file.flush()
                os.fsync(command_file.fileno())
            message_result = DWORD_PTR()
            if not user32.SendMessageTimeoutW(
                self.hwnd,
                WM_NULL,
                0,
                0,
                SMTO_ABORTIFHUNG,
                timeout_ms,
                ctypes.byref(message_result),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            read_deadline = time.monotonic() + 2.0
            while True:
                try:
                    response = command_path.read_bytes()
                    break
                except PermissionError:
                    if time.monotonic() >= read_deadline:
                        raise
                    time.sleep(0.01)
            if len(response) != COMMAND_STRUCT.size:
                raise SelectionLimitError("补丁组件返回了无效数据")
            unpacked = COMMAND_STRUCT.unpack(response)
            (
                magic,
                version,
                status,
                _action,
                limit,
                state,
                patch_count,
                error,
                failed,
                _,
                selected_count,
                breakpoint_mode,
                breakpoint_thread_id,
                _,
            ) = unpacked[:14]
            if magic != MAGIC or version != PROTOCOL_VERSION or limit != LIMIT:
                raise SelectionLimitError("补丁组件协议不匹配")
            if status != STATUS_OK:
                patch_name = (
                    PATCH_NAMES[failed]
                    if 0 <= failed < len(PATCH_NAMES)
                    else "模块或代码段"
                )
                detail = ctypes.WinError(error).strerror if error else "未知错误"
                raise SelectionLimitError(
                    f"补丁验证失败：{patch_name}，{detail} (WinError {error})",
                    error_code=error,
                    failed_patch=failed,
                )
            return PatchResult(
                state=int(state),
                patch_count=int(patch_count),
                failed_patch=int(failed),
                patch_addresses=tuple(int(value) for value in unpacked[14:28]),
                breakpoint_addresses=tuple(int(value) for value in unpacked[28:32]),
                selected_count=int(selected_count),
                breakpoint_mode=int(breakpoint_mode),
                breakpoint_thread_id=int(breakpoint_thread_id),
                hit_counts=tuple(int(value) for value in unpacked[32:46]),
                diagnostic_hits=tuple(int(value) for value in unpacked[46:50]),
                diagnostic_context=tuple(int(value) for value in unpacked[50:59]),
                selection_manager=int(unpacked[59]),
            )

    def close(self, *, restore: bool = True) -> None:
        with self._lock:
            if restore and self.ready:
                try:
                    self.disable()
                except Exception:
                    pass
            if self.hook:
                user32.UnhookWindowsHookEx(self.hook)
                time.sleep(0.1)
            if self.module:
                kernel32.FreeLibrary(self.module)
            if self.pid:
                command_path = self._command_path()
                try:
                    command_path.unlink()
                except FileNotFoundError:
                    pass
            self.hwnd = 0
            self.pid = 0
            self.module = 0
            self.hook = 0
            self.thread_id = 0
            self.configure_proc = 0
            self.configure_process_proc = 0
            self.configure_auxiliary_proc = 0
            self.breakpoint_addresses = ()
            self.auxiliary_breakpoint_addresses = ()
            self.diagnostic_process_wide = False


class SelectionLimitApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("520x260")
        self.root.minsize(480, 240)
        self.root.configure(bg="#f3f4f6")
        self.bridge = SelectionLimitBridge()
        self.busy = False
        self.target: WarcraftWindow | None = None

        content = Frame(self.root, bg="#f3f4f6", padx=24, pady=22)
        content.pack(fill=BOTH, expand=True)
        Label(
            content,
            text="Warcraft III 24 单位编队",
            font=("Microsoft YaHei UI", 16, "bold"),
            fg="#111827",
            bg="#f3f4f6",
        ).pack(anchor="w")
        self.game_label = Label(
            content,
            text="正在查找 Warcraft III...",
            font=("Microsoft YaHei UI", 10),
            fg="#4b5563",
            bg="#f3f4f6",
            pady=10,
        )
        self.game_label.pack(anchor="w")
        self.status_label = Label(
            content,
            text="未启用，选择与编队上限为 12",
            font=("Microsoft YaHei UI", 11, "bold"),
            fg="#374151",
            bg="#f3f4f6",
            pady=8,
        )
        self.status_label.pack(anchor="w")

        actions = Frame(content, bg="#f3f4f6", pady=12)
        actions.pack(anchor="w")
        self.enable_button = Button(
            actions,
            text="启用 24 单位",
            command=lambda: self._run_action(ACTION_ENABLE),
            width=16,
            height=2,
            bg="#166534",
            fg="white",
            activebackground="#15803d",
            activeforeground="white",
            relief="flat",
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.enable_button.pack(side="left", padx=(0, 10))
        self.disable_button = Button(
            actions,
            text="恢复 12 单位",
            command=lambda: self._run_action(ACTION_DISABLE),
            width=16,
            height=2,
            bg="#d1d5db",
            fg="#111827",
            activebackground="#e5e7eb",
            relief="flat",
            font=("Microsoft YaHei UI", 10),
        )
        self.disable_button.pack(side="left")
        Label(
            content,
            text="头像栏按 4×6 初始化；在主菜单启用后再进入对局。",
            font=("Microsoft YaHei UI", 9),
            fg="#6b7280",
            bg="#f3f4f6",
        ).pack(anchor="w")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._refresh_target)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = DISABLED if busy else NORMAL
        self.enable_button.configure(state=state)
        self.disable_button.configure(state=state)

    def _refresh_target(self) -> None:
        if not self.busy:
            try:
                target = find_warcraft_window()
            except Exception as exc:
                self.game_label.configure(text=f"查找游戏失败：{exc}", fg="#b91c1c")
            else:
                if target is None:
                    self.target = None
                    self.game_label.configure(text="未找到 Warcraft III", fg="#b91c1c")
                else:
                    self.target = target
                    self.game_label.configure(
                        text=f"已找到 Warcraft III  |  PID {target.pid}",
                        fg="#166534",
                    )
        self.root.after(1000, self._refresh_target)

    def _run_action(self, action: int) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.status_label.configure(text="正在验证 12 个动态补丁点...", fg="#92400e")

        def worker() -> None:
            try:
                target = find_warcraft_window()
                if target is None:
                    raise SelectionLimitError("未找到 Warcraft III，请先启动游戏")
                self.bridge.connect(target)
                result = self.bridge.enable() if action == ACTION_ENABLE else self.bridge.disable()
            except Exception as exc:
                self.root.after(0, lambda: self._finish_error(exc))
                return
            self.root.after(0, lambda: self._finish_result(result))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_result(self, result: PatchResult) -> None:
        if result.enabled:
            self.status_label.configure(
                text=f"已启用：选择、编队和头像栏上限均为 {LIMIT}",
                fg="#166534",
            )
        else:
            self.status_label.configure(text="未启用，选择与编队上限为 12", fg="#374151")
        self._set_busy(False)

    def _finish_error(self, error: Exception) -> None:
        self.status_label.configure(text="补丁未应用", fg="#b91c1c")
        self._set_busy(False)
        messagebox.showerror(APP_TITLE, str(error), parent=self.root)

    def _on_close(self) -> None:
        self._set_busy(True)
        try:
            self.bridge.close(restore=True)
        finally:
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def run_self_test(helper_path: Path | None = None) -> None:
    helper = helper_path or Path(__file__).resolve().parent / "tools" / "war3_selection_limit_helper_v27.dll"
    library = ctypes.WinDLL(str(helper), use_last_error=True)
    test = library.War3SelectionLimitSelfTest
    test.argtypes = (ctypes.c_uint32,)
    test.restype = ctypes.c_uint32
    for scenario in range(7):
        error = int(test(scenario))
        if error:
            raise ctypes.WinError(error)


def result_payload(target: WarcraftWindow, result: PatchResult) -> dict[str, object]:
    return {
        "pid": target.pid,
        "state": result.state,
        "patch_count": result.patch_count,
        "patch_addresses": [hex(address) for address in result.patch_addresses],
        "breakpoint_addresses": [hex(address) for address in result.breakpoint_addresses],
        "selected_count": result.selected_count,
        "breakpoint_mode": result.breakpoint_mode,
        "breakpoint_thread_id": result.breakpoint_thread_id,
        "hit_counts": list(result.hit_counts),
        "diagnostic_hits": list(result.diagnostic_hits),
        "diagnostic_context": [hex(value) for value in result.diagnostic_context],
        "selection_manager": hex(result.selection_manager),
    }


def run_cli(action: int, hold_seconds: float) -> None:
    target = find_warcraft_window()
    if target is None:
        raise SelectionLimitError("未找到 Warcraft III")
    bridge = SelectionLimitBridge()
    bridge.connect(target)
    try:
        if action == ACTION_ENABLE:
            result = bridge.enable()
        elif action == ACTION_DISABLE:
            result = bridge.disable()
        else:
            result = bridge.query()
        print(json.dumps(result_payload(target, result), ensure_ascii=False))
        if action == ACTION_ENABLE and hold_seconds > 0:
            time.sleep(hold_seconds)
    finally:
        bridge.close(restore=action != ACTION_QUERY)


def run_live_query() -> None:
    target = find_warcraft_window(include_hidden=True)
    if target is None:
        raise SelectionLimitError("未找到 Warcraft III")
    result = SelectionLimitBridge.query_existing(target)
    print(json.dumps(result_payload(target, result), ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--query", action="store_true")
    group.add_argument("--query-live", action="store_true")
    group.add_argument("--enable", action="store_true")
    group.add_argument("--disable", action="store_true")
    group.add_argument("--self-test", action="store_true")
    parser.add_argument("--hold", type=float, default=0.0)
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
    elif args.query_live:
        run_live_query()
    elif args.query or args.enable or args.disable:
        action = ACTION_ENABLE if args.enable else ACTION_DISABLE if args.disable else ACTION_QUERY
        run_cli(action, max(0.0, args.hold))
    else:
        SelectionLimitApp().run()


if __name__ == "__main__":
    main()

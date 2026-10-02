"""Build native dependencies and package the standalone hotkey tool."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-only", action="store_true")
    args = parser.parse_args()
    compiler = shutil.which("clang")
    if compiler is None:
        raise RuntimeError("LLVM clang with Windows x64 build tools is required")
    for game_version in ("3.0.0.24268", "3.0.1.24323"):
        subprocess.run([sys.executable, str(ROOT / "tools/build_war3_hotkey_bridge.py"),
                        "--game-version", game_version], cwd=ROOT, check=True)
    output = ROOT / "tools/war3_hotkey_native_helper.dll"
    candidate = output.with_name("war3_hotkey_native_helper.candidate.dll")
    subprocess.run([
        compiler, "--target=x86_64-pc-windows-msvc", "-shared", "-O2",
        "-fexceptions", "-fasync-exceptions", "-fno-stack-protector", "-fno-builtin",
        "-nostdlib", str(ROOT / "tools/war3_hotkey_native_helper.c"), "-o", str(candidate),
        "-Wl,/entry:DllMain,/nodefaultlib,/alternatename:__C_specific_handler=HotkeySpecificHandler",
        "-luser32", "-lkernel32",
    ], cwd=ROOT, check=True)
    import pefile
    pe = pefile.PE(str(candidate), fast_load=False)
    try:
        exports = {item.name for item in pe.DIRECTORY_ENTRY_EXPORT.symbols}
        if b"War3HotkeyHookProc" not in exports:
            raise RuntimeError("Legacy native helper lacks hook entry")
    finally:
        pe.close()
    candidate.replace(output)
    if not args.native_only:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                        str(ROOT / "War3ReforgedHotkeys.spec")], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()

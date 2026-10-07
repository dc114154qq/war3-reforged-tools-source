"""Rebuild this historical hotkey helper and package its unchanged source."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['clang', '--target=x86_64-pc-windows-msvc', '-shared', '-O2',
                '-fexceptions', '-fasync-exceptions', str(ROOT/'tools/war3_hotkey_native_helper.c'),
                '-o', str(ROOT/'tools/war3_hotkey_native_helper.dll'), '-luser32', '-lkernel32'],
               cwd=ROOT, check=True)
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                str(ROOT/'War3ReforgedHotkeys.spec')], cwd=ROOT, check=True)

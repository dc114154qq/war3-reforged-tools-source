"""Build the version-selected hotkey bridge from the JSON adapter source."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def header_text(profile):
    fp = profile['fingerprint']
    command = profile['command_bar']
    entries = set(profile['protected_native_rvas'].values())
    entries.update(command['functions'].values())
    entries.add(command['get_hotkey_rva'])
    entries.update(command.get('diagnostic_virtual_entries', []))
    call = command['guarded_call']
    setter = next(c['bytes'] for c in command['checks']
                  if c['rva'] == command['functions']['set_hotkey'])
    def array(data):
        return ','.join(f'0x{value:02x}' for value in bytes.fromhex(data))
    return (
        '/* Generated from hotkey_profiles/3.0.0.24268.json; edit JSON only. */\n'
        f'#define HOTKEY_300_TIMESTAMP {fp["timestamp"]}u\n'
        f'#define HOTKEY_300_IMAGE_SIZE {fp["image_size"]}u\n'
        'static const uint32_t hotkey_300_entries[]={'
        + ','.join(f'0x{x:x}u' for x in sorted(entries)) + '};\n'
        f'#define HOTKEY_300_CALL_RETURN 0x{call["return_rva"]:x}u\n'
        f'#define HOTKEY_300_CALL_UNWIND 0x{call["unwind_rva"]:x}u\n'
        f'static const unsigned char hotkey_300_call_bytes[]={{{array(call["call_bytes"])}}};\n'
        f'static const unsigned char hotkey_300_setter_prefix[]={{{array(setter)}}};\n'
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'tools/war3_hotkey_bridge.dll')
    parser.add_argument('--check-header', action='store_true')
    args = parser.parse_args()
    from war3_hotkey_adapters import load_profiles
    profiles = [p for p in load_profiles() if p['game_version'] == '3.0.0.24268']
    if len(profiles) != 1:
        raise ValueError('Exactly one adapter for this bridge is required')
    text = header_text(profiles[0])
    header = ROOT/'tools/war3_hotkey_profiles.h'
    if args.check_header:
        if header.read_text(encoding='utf-8') != text:
            raise ValueError('Generated C profile differs from JSON adapter')
        print('C/Python adapter data agree')
        return
    temporary = header.with_suffix('.h.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(header)
    compiler = shutil.which('clang')
    if not compiler:
        raise RuntimeError('clang is required to build the native bridge')
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    candidate = output.with_name(output.stem+'.candidate.dll')
    subprocess.run([compiler, '--target=x86_64-pc-windows-msvc', '-shared', '-O2',
        '-fexceptions', '-fasync-exceptions', '-fno-stack-protector', '-fno-builtin',
        '-nostdlib', str(ROOT/'tools/war3_hotkey_bridge.c'), '-o', str(candidate),
        '-Wl,/entry:DllMain,/nodefaultlib,/alternatename:__C_specific_handler=BridgeSpecificHandler',
        '-luser32', '-lkernel32'], cwd=ROOT, check=True)
    import pefile
    pe = pefile.PE(str(candidate), fast_load=False)
    exports = {entry.name for entry in pe.DIRECTORY_ENTRY_EXPORT.symbols}
    required = {b'hotkey_bridge_abi', b'bridge_profile_abi', b'BridgeInstall',
                b'BridgeUninstall', b'HotkeyBridgeQuery', b'bridge_callback_lifecycle_abi'}
    if not required <= exports:
        pe.close()
        raise RuntimeError('Built bridge is missing required exports')
    pe.close()
    candidate.replace(output)
    print(output)


if __name__ == '__main__':
    main()

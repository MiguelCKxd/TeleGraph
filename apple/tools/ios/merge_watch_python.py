"""Merge BeeWare's watchOS release with a matching arm64 device build."""
import argparse
from pathlib import Path
import plistlib
import shutil
import subprocess
from tempfile import TemporaryDirectory


def combine(arm64_32, arm64, output):
    subprocess.run(['lipo', '-create', arm64_32, arm64, '-output', output], check=True)
    actual = subprocess.check_output(['lipo', '-archs', output], text=True).split()
    if set(actual) != {'arm64', 'arm64_32'}:
        raise ValueError(f'Unexpected architectures {actual} for {output}')


def merge(original, install, output, openssl_manifest):
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as staging:
        merged = Path(staging) / output.name
        shutil.copytree(original, merged, symlinks=True)
        old_id = 'watchos-arm64_32'
        new_id = 'watchos-arm64_arm64_32'
        device = merged / new_id
        (merged / old_id).rename(device)
        with (merged / 'Info.plist').open('rb') as source:
            info = plistlib.load(source)
        device_entry = next(item for item in info['AvailableLibraries']
                            if item['LibraryIdentifier'] == old_id)
        device_entry.update(LibraryIdentifier=new_id, SupportedArchitectures=['arm64', 'arm64_32'])
        with (merged / 'Info.plist').open('wb') as target:
            plistlib.dump(info, target)

        framework = device / 'Python.framework'
        arm64_framework = install / 'Python.framework'
        python = framework / 'Python'
        combine(python, arm64_framework / 'Python', python.with_suffix('.fat'))
        python.with_suffix('.fat').replace(python)
        headers = framework / 'Headers'
        shutil.copy2(arm64_framework / 'Headers' / 'pyconfig.h', headers / 'pyconfig-arm64.h')
        header = headers / 'pyconfig.h'
        old_include = '#include "pyconfig-arm64_32.h"'
        text = header.read_text()
        if old_include not in text:
            raise ValueError(f'Expected arm64_32 header in {header}')
        header.write_text(text.replace(old_include, '#if defined(__LP64__)\n#include "pyconfig-arm64.h"\n'
                                       f'#else\n{old_include}\n#endif'))

        stdlib = device / 'lib-device'
        (device / 'lib-arm64_32').rename(stdlib)
        stdlib = stdlib / 'python3.12'
        arm64_stdlib = install / 'lib' / 'python3.12'
        platform_module = merged / 'lib' / 'python3.12' / 'platform.py'
        original_code = platform_module.read_text()
        replacement = (arm64_stdlib / 'platform.py').read_text()
        if original_code != replacement:
            shutil.copy2(arm64_stdlib / 'platform.py', platform_module)
            for cache in (platform_module.parent / '__pycache__').glob('platform.*.pyc'):
                cache.unlink()
        arm64_configs = list(arm64_stdlib.glob('_sysconfigdata_*.py'))
        if not arm64_configs:
            raise ValueError(f'No arm64 sysconfig at {arm64_stdlib}')
        for config in arm64_configs:
            if (stdlib / config.name).exists():
                raise ValueError(f'Ambiguous sysconfig name {config.name}')
            shutil.copy2(config, stdlib)
        dynamic = stdlib / 'lib-dynload'
        arm64_dynamic = arm64_stdlib / 'lib-dynload'
        left = {module.name for module in dynamic.glob('*.so')}
        right = {module.name for module in arm64_dynamic.glob('*.so')}
        if not left or left != right:
            raise ValueError(f'Different watchOS modules. arm64_32 only: {left - right}; arm64 only: {right - left}')
        for module in sorted(left):
            binary = dynamic / module
            fat = binary.with_suffix('.fat')
            combine(binary, arm64_dynamic / module, fat)
            fat.replace(binary)
        for name in ['_ssl', '_hashlib']:
            shutil.copy2(openssl_manifest, dynamic / (name + '.xcprivacy'))

        utils = merged / 'build' / 'utils.sh'
        text = utils.read_text()
        device_line = 'SLICE_FOLDER="watchos-arm64"'
        lib_path = '$SLICE_FOLDER/lib-$ARCHS/'
        if device_line not in text or lib_path not in text:
            raise ValueError(f'Unexpected layout in {utils}')
        utils.write_text(text.replace(device_line, f'SLICE_FOLDER="{new_id}"\n        SLICE_LIB="lib-device"')
                         .replace(lib_path, '$SLICE_FOLDER/${SLICE_LIB:-lib-$ARCHS}/'))
        merged.rename(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('install', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('openssl_manifest', type=Path)
    args = parser.parse_args()
    merge(args.original, args.install, args.output, args.openssl_manifest)

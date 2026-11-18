"""Rebuild the Chaquopy image libraries for 16 KiB pages with Android NDK r28.

Run on macOS with the project's SDK installed:
    python3 tools/rebuild_android_image_wheels.py
"""
import base64
import csv
import hashlib
from io import StringIO
import os
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
from urllib.request import urlretrieve
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
NDK = ROOT.parent / 'android-sdk/ndk/28.1.13356709/toolchains/llvm/prebuilt/darwin-x86_64/bin'
PACKAGES = {
    'freetype': {
        'source': 'freetype-2.9.1',
        'url': 'https://download.savannah.gnu.org/releases/freetype/freetype-2.9.1.tar.gz',
        'sha': 'ec391504e55498adceb30baceebd147a6e963f636eb617424bcfc47a169898ce',
        'wheel_version': '2.9.1-2',
        'arm64_v8a': '7a8262dc69d1bbf7209b3b7576744743670bd5a8cba48c7d8f08c151943ccbc7',
        'x86_64': '831e0fd721d132b7b04946399d714de9945acc56dffa34f3c037592cb17c8de1',
        'options': ('--without-harfbuzz', '--without-png'),
        'file': 'objs/.libs/libfreetype.so',
        'soname': 'libfreetype.so',
    },
    'libjpeg': {
        'source': 'libjpeg-turbo-1.5.3',
        'url': 'https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/1.5.3/libjpeg-turbo-1.5.3.tar.gz',
        'sha': 'b24890e2bb46e12e72a79f7e965f409f4e16466d00e1dd15d93d73ee6b592523',
        'wheel_version': '1.5.3-1',
        'arm64_v8a': '5555be57a2633fb5a3c0c810e89c8b705c471e3dabd95aa596fc7fdd48322728',
        'x86_64': '0ae61fe258eb17a34e66fb6b1c233eb6c5e6a8854e0900a1806422e9f5625a86',
        'options': ('--without-turbojpeg', '--without-simd'),
        'file': '.libs/libjpeg.so',
        'soname': 'libjpeg_chaquopy.so',
    },
}


def download(url, path, sha):
    urlretrieve(url, path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError(f'SHA-256 mismatch for {path.name}')
    return path


def replace_library(wheel, output, soname, binary):
    member = f'chaquopy/lib/{soname}'
    with ZipFile(wheel) as original, ZipFile(output, 'w', ZIP_DEFLATED) as rebuilt:
        names = original.namelist()
        if member not in names:
            raise ValueError(f'Missing native library in {wheel.name}')
        record = next(name for name in names if name.endswith('.dist-info/RECORD'))
        tag = next(name for name in names if name.endswith('.dist-info/WHEEL'))
        entries = []
        for name in names:
            if name == record or name.endswith('/'):
                continue
            data = binary if name == member else original.read(name)
            if name == tag:
                lines = [line for line in data.decode().splitlines() if not line.startswith('Build:')]
                data = ('\n'.join([*lines, 'Build: 3']) + '\n').encode()
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
            rebuilt.writestr(name, data)
            entries.append((name, 'sha256=' + digest, len(data)))
        rows = StringIO()
        csv.writer(rows, lineterminator='\n').writerows([*entries, (record, '', '')])
        rebuilt.writestr(record, rows.getvalue())


def main():
    with TemporaryDirectory(prefix='telegraph-android-wheels-') as work:
        folder = Path(work)
        patch_url = ('https://raw.githubusercontent.com/chaquo/chaquopy/master/server/pypi/'
                     'packages/chaquopy-libjpeg/patches/soname.patch')
        jpeg_patch = download(patch_url, folder / 'jpeg.patch',
                              '1cd752e2d7083dbd27224cd2c3c350d4250387e9e3d650aec5fc3f7d28743480')
        for package, config in PACKAGES.items():
            archive = download(config['url'], folder / f'{package}.tar.gz', config['sha'])
            for abi, cpu in (('arm64_v8a', 'aarch64'), ('x86_64', 'x86_64')):
                target = folder / f'{package}-{abi}'
                target.mkdir()
                with tarfile.open(archive) as tar:
                    tar.extractall(target, filter='data')
                source = target / config['source']
                if package == 'libjpeg':
                    subprocess.run(['patch', 'configure', str(jpeg_patch)], cwd=source, check=True)
                env = dict(os.environ, CC=str(NDK / f'{cpu}-linux-android21-clang'), AR=str(NDK / 'llvm-ar'),
                           RANLIB=str(NDK / 'llvm-ranlib'), STRIP=str(NDK / 'llvm-strip'),
                           LDFLAGS='-Wl,-z,max-page-size=16384')
                subprocess.run(['./configure', f'--host={cpu}-linux-android', '--enable-shared', '--disable-static',
                                *config['options']], cwd=source, env=env, check=True)
                subprocess.run(['make', '-j', str(min(8, os.cpu_count() or 1))], cwd=source, env=env, check=True)
                library = source / config['file']
                subprocess.run([str(NDK / 'llvm-strip'), '--strip-unneeded', str(library)], check=True)
                version = config['wheel_version']
                tag = f'py3-none-android_21_{abi}.whl'
                template = f'chaquopy_{package}-{version}-{tag}'
                url = f'https://chaquo.com/pypi-13.1/chaquopy-{package}/{template}'
                wheel = download(url, target / template, config[abi])
                output = ROOT / 'wheels' / f"chaquopy_{package}-{version.rsplit('-', 1)[0]}-3-{tag}"
                replace_library(wheel, output, config['soname'], library.read_bytes())
                print(output, flush=True)


if __name__ == '__main__':
    main()

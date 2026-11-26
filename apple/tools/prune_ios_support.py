"""Remove regression fixtures and known host-only launchers from iOS staging."""
from pathlib import Path
import shutil


# pip's console launchers point to the Mac build interpreter. The app imports
# these libraries directly; none of these shell entry points runs on iOS.
CONSOLE_SCRIPTS = ('fonttools', 'pyftmerge', 'pyftsubset', 'ttx', 'qr',
                   'pyrsa-decrypt', 'pyrsa-encrypt', 'pyrsa-keygen',
                   'pyrsa-priv2pub', 'pyrsa-sign', 'pyrsa-verify')


def prune_console_scripts(project):
    removed = []
    for platform in ('iphoneos', 'iphonesimulator'):
        folder = project / 'TGASCII' / ('app_packages.' + platform) / 'bin'
        if not folder.exists():
            continue
        if folder.is_symlink() or not folder.resolve().is_relative_to(project):
            raise ValueError('Refusing to modify linked iOS console scripts')
        for name in CONSOLE_SCRIPTS:
            file = folder / name
            if file.is_symlink():
                raise ValueError('Refusing to remove a linked iOS console script')
            if file.is_file():
                if not file.read_bytes().startswith(b'#!'):
                    raise ValueError('An iOS console launcher has unexpected content')
                removed.append((file, file.stat().st_size))
    # Validate every candidate before removing anything from app_packages.
    for file, _size in removed:
        file.unlink()
    return len(removed), sum(size for _file, size in removed)


def prune_ios_support(project):
    project = Path(project).resolve()
    support = project / 'Support' / 'Python.xcframework' / 'lib'
    roots = list(support.glob('python3.*'))
    if not roots:
        raise ValueError('The staged iOS Python standard library is missing')
    count = size = 0
    for root in roots:
        if not root.resolve().is_relative_to(project):
            raise ValueError('Refusing to modify Python support outside the generated project')
        tests = root / 'test'
        if not tests.exists():
            continue
        if tests.is_symlink() or not tests.resolve().is_relative_to(project):
            raise ValueError('Refusing to remove linked CPython tests')
        for file in tests.rglob('*'):
            if file.is_file() and not file.is_symlink():
                count += 1
                size += file.stat().st_size
        shutil.rmtree(tests)
    scripts, script_size = prune_console_scripts(project)
    count += scripts
    size += script_size
    return {'removed_files': count, 'removed_bytes': size}

"""Remove CPython's own regression fixtures from the staged iPhone runtime."""
from pathlib import Path
import shutil


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
    return {'removed_files': count, 'removed_bytes': size}

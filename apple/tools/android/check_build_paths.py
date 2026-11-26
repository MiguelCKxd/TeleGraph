"""Read-only gate: fail if a package still contains the build machine's home path.

Opens APK/AAR/IPA archives without modifying them and reports the members whose
bytes contain the build user's home directory (for example __FILE__ log strings
of a native library compiled without -ffile-prefix-map). Debug symbols kept
privately next to a release are not packages and are not checked.

    python3 check_build_paths.py app.apk [other.aar ...]
"""
import argparse
import os
from pathlib import Path
import sys
from zipfile import ZipFile


def marker(home=None):
    value = os.fsencode(str(home or Path.home())).rstrip(b'/')
    if value.count(b'/') < 2:
        raise ValueError('Refusing to search for a home path that is too short')
    return value + b'/'


def leaks(path, home=None):
    """Archive members that contain the home path; the archive is only read."""
    needle = marker(home)
    with ZipFile(path) as archive:
        return [member.filename for member in archive.infolist()
                if not member.is_dir() and needle in archive.read(member)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('packages', type=Path, nargs='+')
    parser.add_argument('--home', default=None, help='home path to look for (default: current user)')
    args = parser.parse_args(argv)
    failed = False
    for package in args.packages:
        found = leaks(package, args.home)
        if found:
            failed = True
            print(f'{package.name}: build machine path in ' + ', '.join(found), file=sys.stderr)
        else:
            print(f'{package.name}: no build machine paths')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

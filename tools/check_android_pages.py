"""Check 16 KiB ELF load segments in an APK/AAB and its embedded Chaquopy wheels."""
import argparse
from io import BytesIO
import struct
from zipfile import ZipFile

PAGE_SIZE = 16 * 1024


def inspect_libraries(archive, prefix=''):
    for name in archive.namelist():
        if not name.endswith('.so'):
            continue
        with archive.open(name) as library:
            header = library.read(64)
            if not header.startswith(b'\x7fELF'):
                raise ValueError(f'{prefix}{name}: invalid ELF header')
            if header[4:6] != b'\x02\x01':
                continue  # Only Android's 64-bit ABIs need this check.
            address = struct.unpack_from('<Q', header, 32)[0]
            size, count = struct.unpack_from('<HH', header, 54)
            library.seek(address)
            bad = 0
            for _ in range(count):
                kind, _, offset, virtual, _, _, _, alignment = struct.unpack('<II6Q', library.read(size))
                if kind == 1 and (alignment < PAGE_SIZE or (virtual - offset) % PAGE_SIZE):
                    bad += 1
        yield prefix + name, bad


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk')
    path = parser.parse_args().apk
    with ZipFile(path) as apk:
        checks = list(inspect_libraries(apk))
        for name in apk.namelist():
            if name.startswith(('assets/chaquopy/', 'base/assets/chaquopy/')) and name.endswith('.imy'):
                with ZipFile(BytesIO(apk.read(name))) as embedded:
                    checks.extend(inspect_libraries(embedded, prefix=name + ':'))
    failures = [(name, bad) for name, bad in checks if bad]
    for name, bad in failures:
        print(f'{name}: {bad} misaligned PT_LOAD segment(s)')
    print(f'{len(checks)} 64-bit ELF libraries checked, {len(failures)} failed')
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()

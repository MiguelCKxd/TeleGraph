"""Match private NTgCalls debug symbols to packaged ELF binaries without mutation.

Only GNU build IDs and ELF machine types are read. Source paths in the private
companion are neither printed nor copied into the APK/AAB.
"""
import argparse
from pathlib import PurePosixPath
import struct
from zipfile import ZipFile

MACHINES = {'arm64-v8a': 183, 'x86_64': 62, 'armeabi-v7a': 40, 'x86': 3}


def identity(stream):
    header = stream.read(64)
    if len(header) < 52 or header[:4] != b'\x7fELF' or header[4] not in (1, 2) or header[5] not in (1, 2):
        raise ValueError('Invalid ELF header')
    endian = '<' if header[5] == 1 else '>'
    machine = struct.unpack_from(endian + 'H', header, 18)[0]
    if header[4] == 2:
        offset = struct.unpack_from(endian + 'Q', header, 40)[0]
        entry_size, count = struct.unpack_from(endian + 'HH', header, 58)
        section_format = endian + 'IIQQQQIIQQ'
    else:
        offset = struct.unpack_from(endian + 'I', header, 32)[0]
        entry_size, count = struct.unpack_from(endian + 'HH', header, 46)
        section_format = endian + 'IIIIIIIIII'
    required = struct.calcsize(section_format)
    if not count or entry_size < required:
        raise ValueError('Missing ELF section headers')
    notes = []
    for index in range(count):
        stream.seek(offset + index * entry_size)
        data = stream.read(required)
        if len(data) != required:
            raise ValueError('Truncated ELF section header')
        section = struct.unpack(section_format, data)
        if section[1] == 7:  # SHT_NOTE, usable in stripped runtime and .dbg.
            notes.append((section[4], section[5]))
    found = set()
    for start, length in notes:
        if length > 1024 * 1024:
            raise ValueError('Unexpectedly large ELF note')
        stream.seek(start)
        note = stream.read(length)
        if len(note) != length:
            raise ValueError('Truncated ELF note')
        cursor = 0
        while cursor + 12 <= len(note):
            namesz, descsz, kind = struct.unpack_from(endian + 'III', note, cursor)
            cursor += 12
            name_end = cursor + namesz
            desc_start = cursor + ((namesz + 3) & ~3)
            desc_end = desc_start + descsz
            if desc_end > len(note):
                raise ValueError('Invalid ELF note bounds')
            if kind == 3 and note[cursor:name_end].rstrip(b'\0') == b'GNU' and descsz:
                found.add(note[desc_start:desc_end].hex())
            cursor = desc_start + ((descsz + 3) & ~3)
    if len(found) != 1:
        raise ValueError('Missing or ambiguous GNU build ID')
    return machine, found.pop()


def verify(package, symbols):
    checked = []
    with ZipFile(package) as runtime, ZipFile(symbols) as debug:
        names = runtime.namelist()
        if len(names) != len(set(names)) or len(debug.namelist()) != len(set(debug.namelist())):
            raise ValueError('Duplicate archive member')
        for name in names:
            path = PurePosixPath(name)
            if path.name != 'libntgcalls.so':
                continue
            abi = path.parent.name
            if abi not in MACHINES:
                raise ValueError('Unrecognized NTgCalls ABI')
            companion = f'{abi}/libntgcalls.so.dbg'
            if companion not in debug.namelist():
                raise ValueError(f'Missing NTgCalls symbols for {abi}')
            with runtime.open(name) as source, debug.open(companion) as details:
                actual, expected = identity(source), identity(details)
            if actual != expected or actual[0] != MACHINES[abi]:
                raise ValueError(f'NTgCalls symbol identity mismatch for {abi}')
            checked.append((abi, actual[1]))
    if not checked:
        raise ValueError('Package has no NTgCalls runtime to match')
    return checked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('package')
    parser.add_argument('symbols')
    args = parser.parse_args(argv)
    for abi, build_id in verify(args.package, args.symbols):
        print(f'NTgCalls {abi}: private symbols match build ID {build_id}')


if __name__ == '__main__':
    main()

"""Assemble the local volume-enabled engine from native builds and the matching AAR."""
import argparse
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

BINDING = 'io/github/pytgcalls/NTgCalls.class'


def copy_archive(source, target, replacements, skip_prefix=None):
    for member in source.infolist():
        if member.filename not in replacements and (skip_prefix is None or not member.filename.startswith(skip_prefix)):
            target.writestr(member, source.read(member))
    for path, data in replacements.items():
        target.writestr(path, data)


def assemble(stock, java_class, webrtc, arm64, x86, output):
    with ZipFile(webrtc) as webrtc_classes:
        if 'org/webrtc/ContextUtils.class' not in webrtc_classes.namelist():
            raise ValueError('Expected the Android WebRTC JAR for the native build')
    replacements = {'libs/webrtc.jar': webrtc.read_bytes()}
    for abi, binary in [('arm64-v8a', arm64), ('x86_64', x86)]:
        data = binary.read_bytes()
        if not data.startswith(b'\x7fELF') or b'Java_io_github_pytgcalls_NTgCalls_setSourceVolume\x00' not in data:
            raise ValueError(f'Missing native volume entry point in {binary}')
        replacements[f'jni/{abi}/libntgcalls.so'] = data
    with ZipFile(stock) as original:
        updated = BytesIO()
        with ZipFile(BytesIO(original.read('classes.jar'))) as classes, ZipFile(updated, 'w', ZIP_DEFLATED) as patched:
            copy_archive(classes, patched, {BINDING: java_class.read_bytes()})
        replacements['classes.jar'] = updated.getvalue()
        with TemporaryDirectory(dir=output.parent) as folder:
            assembled = Path(folder) / output.name
            with ZipFile(assembled, 'w', ZIP_DEFLATED) as target:
                copy_archive(original, target, replacements, skip_prefix='jni/')
            assembled.replace(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('stock', 'java_class', 'webrtc', 'arm64', 'x86', 'output'):
        parser.add_argument(argument, type=Path)
    args = parser.parse_args()
    assemble(args.stock, args.java_class, args.webrtc, args.arm64, args.x86, args.output)

"""The private companion must belong to the packaged native binary."""
import io
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools' / 'android'))
from check_native_symbols import identity, verify


def elf(build_id=b'actual-build', machine=183, note=True):
    header = bytearray(64)
    header[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<H', header, 18, machine)
    struct.pack_into('<Q', header, 40, 64)
    struct.pack_into('<HH', header, 58, 64, 1)
    data = struct.pack('<III', 4, len(build_id), 3) + b'GNU\0' + build_id
    data += b'\0' * ((-len(data)) % 4)
    section = struct.pack('<IIQQQQIIQQ', 0, 7 if note else 1, 0, 0, 128, len(data), 0, 0, 4, 0)
    return bytes(header) + section + data


class NativeSymbolTests(unittest.TestCase):
    def pair(self, folder, actual=None, expected=None, member='arm64-v8a/libntgcalls.so.dbg'):
        package, symbols = Path(folder) / 'app.apk', Path(folder) / 'symbols.zip'
        with ZipFile(package, 'w') as archive:
            archive.writestr('lib/arm64-v8a/libntgcalls.so', actual or elf())
        with ZipFile(symbols, 'w') as archive:
            archive.writestr(member, expected or elf())
        return package, symbols

    def test_matching_identity_is_read_only(self):
        with TemporaryDirectory() as folder:
            pair = self.pair(folder)
            before = [p.read_bytes() for p in pair]
            self.assertEqual(verify(*pair), [('arm64-v8a', b'actual-build'.hex())])
            self.assertEqual(before, [p.read_bytes() for p in pair])

    def test_rejects_symbols_from_previous_release(self):
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                verify(*self.pair(folder, expected=elf(b'old-build')))

    def test_rejects_abi_mismatch_even_if_build_id_matches(self):
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                verify(*self.pair(folder, actual=elf(machine=62), expected=elf(machine=62)))

    def test_rejects_missing_abi_and_build_id(self):
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'Missing NTgCalls'):
                verify(*self.pair(folder, member='x86_64/libntgcalls.so.dbg'))
        with self.assertRaisesRegex(ValueError, 'build ID'):
            identity(io.BytesIO(elf(note=False)))

    def test_truncated_or_non_elf_is_rejected(self):
        for content in [b'not an ELF', elf()[:-5]]:
            with self.assertRaises(ValueError):
                identity(io.BytesIO(content))

    def test_packaging_checks_both_outputs_before_publication(self):
        script = (ROOT / 'tools' / 'package_android.sh').read_text()
        self.assertIn('TELEGRAPH_ANDROID_SYMBOLS', script)
        self.assertLess(script.index('check_native_symbols.py "$working/signed.apk"'), script.index('install -m 600'))
        self.assertLess(script.index('check_native_symbols.py "$unsigned_bundle"'), script.index('jarsigner -keystore'))
        self.assertIn('chmod 700 "$symbol_dir"', script)


if __name__ == '__main__':
    unittest.main()

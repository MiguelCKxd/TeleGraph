"""3.0.0.2: lighter Linux packages that keep working after an update."""
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))


class LinuxPackageTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == 'win32', 'Linux packages; Windows needs privileges for symbolic links')
    def test_duplicate_libraries_become_links_and_survive_zip_and_update(self):
        from build_release import slim_linux_bundle, zip_tree
        from tg_ascii import __version__
        from tg_ascii.updater import extract_archive, version_tuple
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder) / 'TG-ASCII'
            (app / '_internal' / 'av.libs').mkdir(parents=True)
            payload = b'\x7fELF' + b'x' * 300000
            (app / '_internal' / 'av.libs' / 'libavcodec.so.63').write_bytes(payload)
            (app / '_internal' / 'libavcodec.so.63').write_bytes(payload)
            (app / '_internal' / 'other.so').write_bytes(b'different')
            (app / 'TG-ASCII').write_bytes(b'#!/bin/sh\n')
            newer = '.'.join(str(part) for part in (*version_tuple(__version__)[:-1], version_tuple(__version__)[-1] + 1))
            (app / 'release.json').write_text('{"app": "TG-ASCII", "version": "%s", "target": "linux-x86_64"}' % newer, encoding='utf-8')
            self.assertGreaterEqual(slim_linux_bundle(app), len(payload))
            copy = app / '_internal' / 'libavcodec.so.63'
            self.assertTrue(copy.is_symlink())
            self.assertEqual(copy.read_bytes(), payload)
            self.assertFalse((app / '_internal' / 'other.so').is_symlink())
            archive = Path(folder) / 'TeleGraph-9-linux-x86_64.zip'
            zip_tree(app, archive, 'TeleGraph-9-linux-x86_64')
            with zipfile.ZipFile(archive) as bundle:
                sizes = {info.filename: info.file_size for info in bundle.infolist()}
            self.assertEqual(sizes['TeleGraph-9-linux-x86_64/_internal/libavcodec.so.63'], len('av.libs/libavcodec.so.63'))
            from unittest.mock import patch
            with patch('tg_ascii.updater.target_id', return_value='linux-x86_64'):
                root = extract_archive(archive, Path(folder) / 'installed')
            installed = root / '_internal' / 'libavcodec.so.63'
            self.assertTrue(installed.is_symlink())
            self.assertEqual(installed.read_bytes(), payload)


if __name__ == '__main__':
    unittest.main()

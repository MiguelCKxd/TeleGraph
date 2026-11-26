import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch, Mock
import zipfile

from tg_ascii import contact_sync, device_contacts, updater


class ImportBoundsTests(unittest.TestCase):
    def test_vcard_reads_at_most_its_existing_limit(self):
        raw = b'BEGIN:VCARD\nFN:Alice\nTEL:+34123456789\nEND:VCARD\n'
        stream = Mock(wraps=io.BytesIO(raw))
        with patch.object(Path, 'open') as opened:
            opened.return_value.__enter__.return_value = stream
            contacts = device_contacts.read_vcard('contacts.vcf')
        stream.read.assert_called_once_with(16 * 1024 * 1024)
        self.assertEqual(contacts[0].first, 'Alice')

    def test_symlink_is_rejected_before_decompressing_large_target(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'update.zip'
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                link = zipfile.ZipInfo('release/link')
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(link, 'x' * 4097)
            with patch.object(zipfile.ZipFile, 'read', side_effect=AssertionError('must not inflate')):
                with self.assertRaises(ValueError):
                    updater.validate_archive(path)

    def test_late_sync_result_preserves_new_disabled_preference(self):
        with tempfile.TemporaryDirectory() as folder:
            start = {'enabled': True, 'imported': {}, 'last': {}}
            contact_sync.save_state(folder, 'a', start)
            contact_sync.save_state(folder, 'a', {**start, 'enabled': False})
            result = {**start, 'imported': {'+34123456789': 'fingerprint'}}
            contact_sync.save_state(folder, 'a', result, preserve_enabled=True)
            saved = contact_sync.load_state(folder, 'a')
            self.assertFalse(saved['enabled'])
            self.assertEqual(saved['imported'], result['imported'])

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import Mock

from tg_ascii.secret_chats import secret_peer_id
from tg_ascii_mobile.siri_vocabulary import SiriVocabulary


class VocabularyTests(TestCase):
    def test_consent_revocation_lock_account_and_rename(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            core = NS(stage='ready', locked=False, account='a', chats=[
                NS(id=1, name='Amiga', kind='user'), NS(id=-3, name='Grupo', kind='group'),
                NS(id=secret_peer_id(4), name='Secreto', kind='user')])
            native = Mock()
            vocab = SiriVocabulary(root)
            vocab.attach(native, core)

            def current():
                return json.loads(native.replaceJSON_.call_args.args[0])

            self.assertEqual(current(), [])
            self.assertEqual([c['id'] for c in vocab.configure(core, 'a', None)], [1, -3])
            with self.assertRaises(ValueError):
                vocab.configure(core, 'a', [secret_peer_id(4)])
            vocab.configure(core, 'a', [-3])
            self.assertEqual(current(), [['["a",-3]', 'Grupo', True]])
            self.assertNotIn('Grupo', vocab.path.read_text())
            self.assertEqual(SiriVocabulary(root).accounts, {'a': [-3]})
            core.locked = True
            vocab.sync(core)
            self.assertEqual(current(), [])
            with self.assertRaises(PermissionError):
                vocab.configure(core, 'a', [1])
            core.locked = False
            core.chats[1].name = 'Otro nombre'
            vocab.sync(core)
            self.assertEqual(current()[0][1], 'Otro nombre')
            with vocab.changing_account(core):
                self.assertEqual(current(), [])
                core.account = 'b'
                vocab.sync(core)
                self.assertEqual(current(), [])
            self.assertEqual(current(), [])
            with self.assertRaises(PermissionError):
                vocab.configure(core, 'a', [1])
            core.account = 'a'
            vocab.configure(core, 'a', [])
            self.assertEqual(current(), [])
            vocab.configure(core, 'a', [1])
            vocab.forget('a')
            vocab.sync(core)
            self.assertEqual(current(), [])
            self.assertEqual(SiriVocabulary(root).accounts, {})

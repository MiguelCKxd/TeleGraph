import ast
from datetime import datetime, timedelta
import hashlib
import importlib.util
import os
import plistlib
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch
import zipfile

from tg_ascii.auth import get_credentials, SetupError
from tg_ascii.i18n import detect_language, set_language, tr

spec = importlib.util.spec_from_file_location('build_release', Path(__file__).resolve().parents[1] / 'tools' / 'build_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class DistributionTests(unittest.TestCase):
    def test_mac_push_profile_requires_matching_bundle_identity_and_environment(self):
        cert = b'test certificate'
        fingerprint = hashlib.sha1(cert).hexdigest().upper()
        privileges = {'com.apple.developer.aps-environment': 'development',
                      'com.apple.application-identifier': 'PREFIX.org.tgas.desktop',
                      'com.apple.developer.team-identifier': 'TEAM',
                      'keychain-access-groups': ['PREFIX.*']}
        profile = {'Entitlements': privileges, 'Platform': ['OSX'], 'TeamIdentifier': ['TEAM'],
                   'ApplicationIdentifierPrefix': ['PREFIX'], 'DeveloperCertificates': [cert],
                   'ExpirationDate': datetime.now() + timedelta(days=5)}
        identities = f'  1) {fingerprint} "Apple Development: Test"'
        def check(profile, identities):
            results = [SimpleNamespace(stdout=plistlib.dumps(profile)), SimpleNamespace(stdout=identities)]
            with patch.object(release.subprocess, 'run', side_effect=results):
                return release.mac_push_signing(Path('test.provisionprofile'))
        signing = check(profile, identities)
        self.assertEqual(signing.identity, fingerprint)
        self.assertNotIn('keychain-access-groups', signing.entitlements)
        with self.assertRaises(ValueError):
            check(profile, identities.replace(fingerprint, 'A' * 40))
        with self.assertRaises(ValueError):
            check(dict(profile, Platform=['iOS']), identities)
        privileges['com.apple.developer.aps-environment'] = 'production'
        with self.assertRaises(ValueError):
            check(profile, identities)
        self.assertEqual(check(profile, identities.replace('Apple Development', 'Developer ID Application')).identity,
                         fingerprint)

    def tearDown(self):
        set_language('es')

    def test_bundled_app_does_not_ask_friends_for_api_keys(self):
        module = ModuleType('tg_ascii._app_credentials')
        module.API_ID, module.API_HASH = 12345, 'a' * 32
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {module.__name__: module}):
            def unexpected(_):
                self.fail('A distributed app must not ask for developer keys')
            self.assertEqual(get_credentials(Path(folder), read=unexpected, secret=unexpected), ((12345, 'a' * 32), False))
            self.assertFalse((Path(folder) / 'config.json').exists())

    def test_incomplete_binary_does_not_ask_for_developer_keys(self):
        with patch.object(sys, 'frozen', True, create=True), patch('tg_ascii.auth.bundled_credentials', return_value=None):
            with self.assertRaises(SetupError):
                get_credentials(Path('unused'), read=lambda _: self.fail('Unexpected prompt'))

    def test_public_build_accepts_user_api_without_publisher_identity(self):
        credentials = ('43210', 'c' * 32)
        with tempfile.TemporaryDirectory() as directory, patch.object(sys, 'frozen', True, create=True), \
                patch('tg_ascii.auth.USER_API', True), patch.dict(os.environ, {'TG_API_ID': 'invalid'}, clear=True):
            answers = iter([credentials[0], 'n'])
            result = get_credentials(Path(directory), read=lambda _: next(answers), secret=lambda _: credentials[1], write=lambda _: None)
            self.assertEqual(result, ((43210, credentials[1]), False))
            self.assertFalse((Path(directory) / 'config.json').exists())

    def test_runtime_tls_policy_is_included_only_when_present(self):
        import ssl
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(ssl, '__file__', str(root / 'ssl.py')):
                self.assertEqual(release.runtime_tls_data(), [])
                (root / 'unrelated-private.pem').write_text('must not be packaged', encoding='utf-8')
                self.assertEqual(release.runtime_tls_data(), [])
                policy = root / 'codex-rejected-cas.pem'
                policy.write_text('synthetic public TLS policy', encoding='utf-8')
                self.assertEqual(release.runtime_tls_data(), ['--add-data', str(policy) + os.pathsep + '.'])

    def test_local_relative_imports_are_in_the_release(self):
        source = release.ROOT / 'tg_ascii'
        shipped = set(release.SOURCE_MODULES)
        for name in shipped:
            tree = ast.parse((source / name).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    modules = [node.module] if node.module else [entry.name for entry in node.names]
                    for module in modules:
                        filename = module.split('.')[0] + '.py'
                        if (source / filename).is_file() and filename not in ('_app_credentials.py', '_update_channel.py'):
                            self.assertIn(filename, shipped, f'{name} imports {filename}')

    def test_staging_excludes_account_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, staged = root / 'source', root / 'stage'
            (source / 'tg_ascii').mkdir(parents=True)
            for name in release.SOURCE_MODULES:
                (source / 'tg_ascii' / name).write_text('# fixture\n', encoding='utf-8')
            (source / 'run.py').write_text('# launcher\n', encoding='utf-8')
            (source / 'tg_ascii' / 'assets').mkdir()
            for asset in release.ASSETS:
                (source / 'tg_ascii' / 'assets' / asset).write_bytes(b'image fixture')
            (source / 'tg_ascii' / 'locales').mkdir()
            for name in release.LOCALE_FILES:
                (source / 'tg_ascii' / 'locales' / name).write_text('locale fixture', encoding='utf-8')
            for name in ['account.session', 'config.json', '.env', 'notes.txt']:
                (source / name).write_text('must not be copied', encoding='utf-8')
                (source / 'tg_ascii' / name).write_text('must not be copied', encoding='utf-8')
            with patch.object(release, 'ROOT', source):
                release.stage_source(staged, (12345, 'b' * 32))
            files = {p.name for p in staged.rglob('*') if p.is_file()}
            self.assertEqual(files, set(release.SOURCE_MODULES) | {'run.py', '_app_credentials.py'} | set(release.ASSETS) | set(release.LOCALE_FILES))

    def test_windows_emulated_x64_is_labelled_x64(self):
        with patch.object(release.sysconfig, 'get_platform', return_value='win-amd64'), patch.object(release.platform, 'machine', return_value='ARM64'):
            self.assertEqual(release.build_architecture(), 'x64')

    def test_windows_architectures_are_distinct(self):
        for target, label in [('win-amd64', 'x64'), ('win-arm64', 'arm64'), ('win32', 'x86')]:
            with self.subTest(target=target), patch.object(release.sysconfig, 'get_platform', return_value=target):
                self.assertEqual(release.build_architecture(), label)

    def test_english_and_explicit_language_preference(self):
        import os
        with patch.dict(os.environ, {'TG_ASCII_LANGUAGE': 'en'}):
            set_language(detect_language())
        self.assertEqual(tr('Enviado.'), 'Sent.')
        self.assertEqual(tr('Tu'), 'You')
        self.assertIn('country calling code', tr('Telefono con prefijo internacional (+34..., +56..., +1...): '))

    def exercise_locked_cleanup(self, compiler_fails):
        real_tempdir, real_unlink = tempfile.TemporaryDirectory, os.unlink
        with real_tempdir() as folder:
            base = Path(folder)

            def tempdir(*args, **kwargs):
                return real_tempdir(*args, dir=base, **kwargs)

            def locked_unlink(path, *args, **kwargs):
                if Path(path).name == '_wcwidth_c.pyd':
                    raise PermissionError('Simulated Windows file lock')
                return real_unlink(path, *args, **kwargs)

            def run(command, **kwargs):
                if '--distpath' in command:
                    self.assertIn('--windowed', command)
                    self.assertEqual(Path(kwargs['env']['PYINSTALLER_CONFIG_DIR']).parent, Path(kwargs['cwd']).parent)
                    self.assertNotIn('--console', command)
                    app = Path(command[command.index('--distpath') + 1]) / 'TG-ASCII'
                    (app / '_internal' / 'wcwidth').mkdir(parents=True)
                    (app / '_internal' / 'wcwidth' / '_wcwidth_c.pyd').write_bytes(b'locked fixture')
                    (app / 'TG-ASCII.exe').write_bytes(b'fake exe for archive test')
                    return SimpleNamespace(returncode=int(compiler_fails), stdout='original compiler error' if compiler_fails else '')
                report = Path(command[command.index('--self-test') + 1])
                import json
                report.write_text(json.dumps({'version': release.__version__, 'gui': True, 'demo_chats': 3, 'audio_codec': True, 'calls_available': True}), encoding='utf-8')
                return SimpleNamespace(returncode=0, stdout='', stderr='')

            with patch.object(release.tempfile, 'TemporaryDirectory', side_effect=tempdir), \
                    patch.object(release.platform, 'system', return_value='Windows'), \
                    patch.object(release, 'build_architecture', return_value='x64'), \
                    patch.object(release.importlib.util, 'find_spec', return_value=object()), \
                    patch.dict(sys.modules, {'PIL': SimpleNamespace(Image=MagicMock(open=Mock(return_value=MagicMock())))}), \
                    patch.object(release.subprocess, 'run', side_effect=run), \
                    patch.object(os, 'unlink', side_effect=locked_unlink):
                if compiler_fails:
                    with self.assertRaisesRegex(RuntimeError, 'original compiler error'):
                        release.build(base / 'output', demo_only=True)
                    self.assertEqual(list((base / 'output').glob('*.zip')), [])
                else:
                    archive = release.build(base / 'output', demo_only=True, keep_app=True)
                    self.assertTrue((archive.with_suffix('') / 'TG-ASCII.exe').exists())
                    with zipfile.ZipFile(archive) as bundle:
                        self.assertIsNone(bundle.testzip())
                        self.assertTrue(any(name.endswith('/TG-ASCII.exe') for name in bundle.namelist()))
                # The lock was actually exercised; cleanup removed everything
                # it could while leaving the locked extension for the OS.
                self.assertTrue(list(base.rglob('_wcwidth_c.pyd')))
                self.assertFalse(list(base.rglob('run.py')))

    def test_locked_extension_does_not_fail_completed_build(self):
        self.exercise_locked_cleanup(compiler_fails=False)

    def test_locked_extension_does_not_hide_compiler_error(self):
        self.exercise_locked_cleanup(compiler_fails=True)


if __name__ == '__main__':
    unittest.main()

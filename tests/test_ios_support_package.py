"""Release packaging removes only CPython regression data in its staging tree."""
from pathlib import Path
import importlib.util
from tempfile import TemporaryDirectory
from unittest import TestCase

spec = importlib.util.spec_from_file_location('prune_ios_support', Path(__file__).resolve().parents[1] / 'tools/prune_ios_support.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class IOSSupportPackagingTests(TestCase):
    def test_regression_data_removed_without_altering_runtime_or_app_tests(self):
        with TemporaryDirectory() as directory:
            project = Path(directory)
            lib = project / 'Support/Python.xcframework/lib/python3.12'
            (lib / 'test/wheeldata').mkdir(parents=True)
            (lib / 'test/wheeldata/unneeded.whl').write_bytes(b'wheel')
            (lib / 'unittest').mkdir()
            (lib / 'unittest/__init__.py').write_bytes(b'keep unittest')
            (lib / 'asyncio').mkdir()
            (lib / 'asyncio/__init__.py').write_bytes(b'keep asyncio')
            (project / 'TGASCII/app/test').mkdir(parents=True)
            (project / 'TGASCII/app/test/needed.json').write_bytes(b'app data')
            result = module.prune_ios_support(project)
            self.assertEqual(result, {'removed_files': 1, 'removed_bytes': 5})
            self.assertFalse((lib / 'test').exists())
            self.assertEqual((lib / 'unittest/__init__.py').read_bytes(), b'keep unittest')
            self.assertEqual((lib / 'asyncio/__init__.py').read_bytes(), b'keep asyncio')
            self.assertEqual((project / 'TGASCII/app/test/needed.json').read_bytes(), b'app data')
            self.assertEqual(module.prune_ios_support(project)['removed_files'], 0)

    def test_support_symlink_cannot_delete_global_runtime_files(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as external:
            project, global_lib = Path(directory), Path(external)
            support = project / 'Support/Python.xcframework/lib'
            support.mkdir(parents=True)
            (global_lib / 'test').mkdir()
            fixture = global_lib / 'test/fixture.bin'
            fixture.write_bytes(b'global')
            (support / 'python3.12').symlink_to(global_lib, target_is_directory=True)
            with self.assertRaises(ValueError):
                module.prune_ios_support(project)
            self.assertEqual(fixture.read_bytes(), b'global')

    def test_missing_staging_runtime_fails_before_archive(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                module.prune_ios_support(Path(directory))

    def test_known_mac_launchers_removed_but_imported_libraries_and_other_tools_survive(self):
        with TemporaryDirectory() as directory:
            project = Path(directory)
            (project / 'Support/Python.xcframework/lib/python3.12').mkdir(parents=True)
            for platform in ('iphoneos', 'iphonesimulator'):
                packages = project / 'TGASCII' / ('app_packages.' + platform)
                (packages / 'bin').mkdir(parents=True)
                for name in module.CONSOLE_SCRIPTS:
                    (packages / 'bin' / name).write_bytes(b'#!/bin/sh\n# host launcher\n')
                (packages / 'bin/unknown-runtime-tool').write_bytes(b'keep unknown executable')
                for name in ('qrcode', 'rsa', 'fontTools'):
                    (packages / name).mkdir()
                    (packages / name / '__init__.py').write_bytes(b'# imported runtime\n')
            result = module.prune_ios_support(project)
            self.assertEqual(result['removed_files'], 22)
            for packages in (project / 'TGASCII').iterdir():
                self.assertEqual([p.name for p in (packages / 'bin').iterdir()], ['unknown-runtime-tool'])
                for name in ('qrcode', 'rsa', 'fontTools'):
                    self.assertEqual((packages / name / '__init__.py').read_bytes(), b'# imported runtime\n')
            self.assertEqual(module.prune_ios_support(project)['removed_files'], 0)

    def test_linked_console_directory_cannot_modify_the_build_mac(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as external:
            project, host = Path(directory), Path(external)
            (project / 'Support/Python.xcframework/lib/python3.12').mkdir(parents=True)
            packages = project / 'TGASCII/app_packages.iphoneos'
            packages.mkdir(parents=True)
            (host / 'qr').write_bytes(b'#!/bin/sh\n# original host tool\n')
            (packages / 'bin').symlink_to(host, target_is_directory=True)
            with self.assertRaises(ValueError):
                module.prune_ios_support(project)
            self.assertTrue((host / 'qr').is_file())

    def test_unexpected_content_is_preserved_and_stops_packaging(self):
        with TemporaryDirectory() as directory:
            project = Path(directory)
            (project / 'Support/Python.xcframework/lib/python3.12').mkdir(parents=True)
            folder = project / 'TGASCII/app_packages.iphoneos/bin'
            folder.mkdir(parents=True)
            (folder / 'fonttools').write_bytes(b'#!/bin/sh\n# standard launcher\n')
            (folder / 'qr').write_bytes(b'Unexpected binary runtime')
            with self.assertRaises(ValueError):
                module.prune_ios_support(project)
            self.assertTrue((folder / 'fonttools').exists())
            self.assertEqual((folder / 'qr').read_bytes(), b'Unexpected binary runtime')

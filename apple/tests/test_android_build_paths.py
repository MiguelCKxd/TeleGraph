"""Android packages must not contain the build machine's home path (read-only gate)."""
import hashlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools' / 'android'))
from check_build_paths import leaks, main, marker  # noqa: E402

HOME = '/Users/builder'


def package(folder, members):
    path = Path(folder) / 'app.apk'
    with ZipFile(path, 'w') as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


class AndroidBuildPathTests(TestCase):
    def test_reports_members_with_the_home_path(self):
        with TemporaryDirectory() as folder:
            apk = package(folder, {
                'lib/arm64-v8a/libntgcalls.so': b'\x7fELF..' + HOME.encode() + b'/Developer/x/a.cpp\x00',
                'classes.dex': b'dex', 'assets/readme.txt': b'/Users/builder2/other\x00'})
            self.assertEqual(leaks(apk, HOME), ['lib/arm64-v8a/libntgcalls.so'])
            self.assertEqual(main([str(apk), '--home', HOME]), 1)

    def test_clean_package_passes(self):
        with TemporaryDirectory() as folder:
            apk = package(folder, {'lib/arm64-v8a/libntgcalls.so': b'\x7fELF ./ntgcalls/src/a.cpp\x00'})
            self.assertEqual(leaks(apk, HOME), [])
            self.assertEqual(main([str(apk), '--home', HOME]), 0)

    def test_package_is_never_modified(self):
        with TemporaryDirectory() as folder:
            apk = package(folder, {'lib/x.so': HOME.encode() + b'/a\x00'})
            before = hashlib.sha256(apk.read_bytes()).hexdigest()
            leaks(apk, HOME)
            self.assertEqual(hashlib.sha256(apk.read_bytes()).hexdigest(), before)

    def test_home_marker_is_a_directory_and_not_too_short(self):
        self.assertEqual(marker(HOME), HOME.encode() + b'/')
        with self.assertRaises(ValueError):
            marker('/')

    def test_android_packaging_runs_the_gate_before_signing(self):
        script = (ROOT / 'tools' / 'package_android.sh').read_text(encoding='utf-8')
        gate = script.index('check_build_paths.py "$unsigned"')
        self.assertLess(gate, script.index('apksigner" sign'))
        self.assertNotIn('scrub', script)

    def test_android_bundle_runs_the_gate_before_signing(self):
        script = (ROOT / 'tools' / 'package_android.sh').read_text(encoding='utf-8')
        gate = script.index('check_build_paths.py "$unsigned_bundle"')
        self.assertLess(gate, script.index('jarsigner -keystore'))

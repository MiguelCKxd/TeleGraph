import hashlib,json,tempfile,unittest
from pathlib import Path
from tools.native_engine_wheel import bundled_engine


class BundledEngineTests(unittest.TestCase):
    def fixture(self, root, bad=False):
        name='ntgcalls-3.0.5+tgascii.volume1-cp312-cp312-macosx_14_0_arm64.whl'
        data=b'wheel fixture'
        (root/name).write_bytes(data)
        (root/'manifest.json').write_text(json.dumps({'version':'3.0.5+tgascii.volume1','wheels':{name:{'bytes':len(data),'sha256':('0'*64 if bad else hashlib.sha256(data).hexdigest())}}}),encoding='utf-8')
        return name

    def test_matching_abi_and_platform_are_selected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);name=self.fixture(root)
            self.assertEqual(bundled_engine(root,{'cp312-cp312-macosx_14_0_arm64'}),str((root/name).resolve()))
            self.assertIsNone(bundled_engine(root,{'cp313-cp313-win_amd64'}))

    def test_modified_wheel_blocks_install_instead_of_silent_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root,bad=True)
            with self.assertRaisesRegex(ValueError,'integrity'):bundled_engine(root,{'cp312-cp312-macosx_14_0_arm64'})

    def test_manifest_cannot_escape_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'manifest.json').write_text(json.dumps({'version':'3.0.5+tgascii.volume1','wheels':{'../other.whl':{}}}),encoding='utf-8')
            with self.assertRaises(ValueError):bundled_engine(root,set())

"""The generated phone target keeps a single compile/link pipeline."""
import importlib.util
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import unittest


TOOLS = Path(__file__).resolve().parents[1] / 'tools'
spec = importlib.util.spec_from_file_location('telegraph_configure_glass_test', TOOLS / 'configure_glass.py')
glass = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(TOOLS))
try:
    spec.loader.exec_module(glass)
finally:
    sys.path.pop(0)


def fixture(extra_phase=False):
    return '''/* Begin PBXFileReference section */
/* End PBXFileReference section */
/* Begin PBXBuildFile section */
/* End PBXBuildFile section */
/* Begin PBXSourcesBuildPhase section */
		AAAAAAAAAAAAAAAAAAAAAAAA /* Sources */ = {
			isa = PBXSourcesBuildPhase;
			files = (
				111111111111111111111111 /* main.m */,
			);
		};
OLD_PHASE
/* End PBXSourcesBuildPhase section */
		60796EE119190F4100A9926B /* Phone */ = {
			isa = PBXNativeTarget;
			buildConfigurationList = BBBBBBBBBBBBBBBBBBBBBBBB;
			buildPhases = (
				AAAAAAAAAAAAAAAAAAAAAAAA /* Sources */,
OLD_MEMBER
			);
		};
		BBBBBBBBBBBBBBBBBBBBBBBB /* Configs */ = {
			buildConfigurations = (
				CCCCCCCCCCCCCCCCCCCCCCCC /* Release */,
			);
		};
		CCCCCCCCCCCCCCCCCCCCCCCC /* Release */ = {
			buildSettings = {
			};
		};
'''.replace('OLD_PHASE', '\t\t34A61A550000000000000003 /* Native Glass */ = {isa = PBXSourcesBuildPhase; files = (); };' if extra_phase else '').replace('OLD_MEMBER', '\t\t\t\t34A61A550000000000000003,' if extra_phase else '')


class NativeGlassProjectTests(unittest.TestCase):
    def test_native_swift_joins_existing_sources_once_and_repairs_old_phase(self):
        for old_phase in (False, True):
            with self.subTest(old_phase=old_phase), TemporaryDirectory() as folder:
                xcode = Path(folder)
                (xcode / 'TGASCII').mkdir()
                (xcode / 'TG-ASCII.xcodeproj').mkdir()
                project = xcode / 'TG-ASCII.xcodeproj/project.pbxproj'
                project.write_text(fixture(old_phase))
                glass.configure_glass(xcode)
                first = project.read_text()
                glass.configure_glass(xcode)
                self.assertEqual(project.read_text(), first)
                self.assertEqual(first.count('isa = PBXSourcesBuildPhase;'), 1)
                sources = re.search(r'AAAAAAAAAAAAAAAAAAAAAAAA /\* Sources \*/ = \{(.*?)\n\t\t\};', first, re.S)[1]
                self.assertIn('111111111111111111111111 /* main.m */', sources)
                self.assertEqual(sources.count('34A61A550000000000000002'), 1)
                self.assertNotIn('34A61A550000000000000003', first)
                for name, build in [('TGNativeGlass.swift', 2), ('TGNativeGeometry.swift', 5),
                                    ('TGNativeViewport.swift', 7), ('TGNativeDialogs.swift', 9)]:
                    self.assertEqual((xcode / 'TGASCII' / name).read_bytes(), (TOOLS / 'ios' / name).read_bytes())
                    self.assertEqual(sources.count(f'34A61A55{build:016X}'), 1)
                    self.assertEqual(first.count('path = TGASCII/' + name), 1)

    def test_missing_sources_fails_before_writing_project(self):
        with TemporaryDirectory() as folder:
            xcode = Path(folder)
            (xcode / 'TGASCII').mkdir()
            (xcode / 'TG-ASCII.xcodeproj').mkdir()
            project = xcode / 'TG-ASCII.xcodeproj/project.pbxproj'
            original = fixture().replace('isa = PBXSourcesBuildPhase;', 'isa = PBXResourcesBuildPhase;')
            project.write_text(original)
            with self.assertRaisesRegex(ValueError, 'one Sources'):
                glass.configure_glass(xcode)
            self.assertEqual(project.read_text(), original)

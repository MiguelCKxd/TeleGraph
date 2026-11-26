"""Generated Android windows reserve IME space without changing the WebView code."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from android.keyboard_insets import main_activity, manifest

TEMPLATE = '''
                Insets systemBars = insets.getInsets(
                    WindowInsetsCompat.Type.systemBars()
                    | WindowInsetsCompat.Type.displayCutout()
                );
                ((ViewGroup.MarginLayoutParams) v.getLayoutParams()).setMargins(
                    systemBars.left, systemBars.top, systemBars.right, systemBars.bottom
                );
                statusLp.height = systemBars.top;
'''


class AndroidKeyboardTests(unittest.TestCase):
    def test_main_window_uses_union_not_sum_and_applies_layout(self):
        result = main_activity(TEMPLATE)
        self.assertIn('| WindowInsetsCompat.Type.ime()', result)
        self.assertIn('v.setLayoutParams(contentLp)', result)
        self.assertIn('contentLp.bottomMargin != systemBars.bottom', result)
        self.assertIn('statusLp.height = systemBars.top', result)
        self.assertEqual(main_activity(result), result)

    def test_unknown_template_fails_instead_of_silent_missing_fix(self):
        with self.assertRaisesRegex(ValueError, 'Unknown BeeWare'):
            main_activity(TEMPLATE.replace('displayCutout()', 'otherInsets()'))

    def test_only_editable_windows_receive_resize(self):
        text = '''<activity android:name="org.beeware.android.MainActivity" android:windowSoftInputMode="adjustPan"></activity>
<activity android:name="org.tgas.windows.ChatWindowActivity" />
<activity android:name="org.tgas.calls.CallPipActivity" />
<activity-alias android:name="org.tgas.android.IconDefault" />'''
        result = manifest(text)
        self.assertEqual(result.count('windowSoftInputMode="adjustResize"'), 2)
        self.assertNotIn('adjustPan', result)
        self.assertIn('<activity android:name="org.tgas.calls.CallPipActivity" />', result)
        self.assertEqual(manifest(result), result)

    def test_separate_chat_windows_share_the_inset_policy(self):
        text = (ROOT/'tools/android/ChatWindowActivity.java').read_text()
        self.assertIn('WindowCompat.setDecorFitsSystemWindows(getWindow(), false)', text)
        self.assertIn('WindowInsetsCompat.Type.ime()', text)
        self.assertIn('view.setLayoutParams(lp)', text)
        self.assertIn('ViewCompat.requestApplyInsets(web)', text)


if __name__ == '__main__':
    unittest.main()

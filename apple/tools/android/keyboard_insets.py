"""Patch the known BeeWare edge-to-edge template to reserve visible IME space."""
import re


def main_activity(source):
    marker = '// TeleGraph: the root viewport excludes the keyboard exactly once.'
    if marker in source:
        return source
    mask = '| WindowInsetsCompat.Type.displayCutout()'
    margins = '''                ((ViewGroup.MarginLayoutParams) v.getLayoutParams()).setMargins(
                    systemBars.left, systemBars.top, systemBars.right, systemBars.bottom
                );'''
    if source.count(mask) != 1 or source.count(margins) != 1:
        raise ValueError('Unknown BeeWare Android insets template; review keyboard handling')
    source = source.replace(mask, mask + '\n                    | WindowInsetsCompat.Type.ime()', 1)
    return source.replace(margins, '''                ''' + marker + '''
                ViewGroup.MarginLayoutParams contentLp =
                    (ViewGroup.MarginLayoutParams) v.getLayoutParams();
                if (contentLp.leftMargin != systemBars.left || contentLp.topMargin != systemBars.top
                        || contentLp.rightMargin != systemBars.right || contentLp.bottomMargin != systemBars.bottom) {
                    contentLp.setMargins(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom);
                    v.setLayoutParams(contentLp);
                }''', 1)


def manifest(source):
    def activity(match):
        tag = match[0]
        if not any(f'android:name="{name}"' in tag for name in (
                'org.beeware.android.MainActivity', 'org.tgas.windows.ChatWindowActivity')):
            return tag
        tag = re.sub(r'\s+android:windowSoftInputMode="[^"]*"', '', tag)
        return tag.replace('<activity', '<activity android:windowSoftInputMode="adjustResize"', 1)
    return re.sub(r'<activity\b[^>]*>', activity, source)

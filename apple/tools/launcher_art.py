"""Store-only resources generated directly into the Android and Xcode projects."""
from tg_ascii.logos import LOGO_PALETTES, mobile_wordmark


def android_vector(choice, round_icon):
    variant, theme, color = choice
    background, ink = ('#%02x%02x%02x' % rgb for rgb in LOGO_PALETTES[color][theme])
    path = ''.join(f'M{x},{y}H{r}V{b}H{x}Z' for x, y, r, b in mobile_wordmark(variant))
    badge = 'M512,0a512,512 0,1 1,-1,0Z' if round_icon else 'M0,0H1024V1024H0Z'
    return (f'<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="48dp" '
            f'android:height="48dp" android:viewportWidth="1024" android:viewportHeight="1024">'
            f'<path android:fillColor="{background}" android:pathData="{badge}"/>'
            f'<path android:fillColor="{ink}" android:pathData="{path}"/></vector>\n')


def android_notification_icon():
    # Android tints only the alpha mask. Centre the original mobile lettering in the status icon.
    rects = mobile_wordmark('title-short')
    left, right = min(x for x, _, _, _ in rects), max(r for _, _, r, _ in rects)
    span = right - left
    center_y = (min(y for _, y, _, _ in rects) + max(b for _, _, _, b in rects)) // 2
    side = span + span // 10
    x0, y0 = (left + right - side) // 2, center_y - side // 2
    ink = ''.join(f'M{x-x0},{y-y0}H{r-x0}V{b-y0}H{x-x0}Z' for x, y, r, b in rects)
    return (f'<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="24dp" '
            f'android:height="24dp" android:viewportWidth="{side}" android:viewportHeight="{side}">'
            f'<path android:fillColor="#FFFFFFFF" android:pathData="{ink}"/></vector>\n')


def ios_image(path, choice):
    from PIL import Image, ImageDraw
    variant, theme, color = choice
    background, ink = LOGO_PALETTES[color][theme]
    image = Image.new('RGB', (1024, 1024), background)
    draw = ImageDraw.Draw(image)
    for x, y, r, b in mobile_wordmark(variant):
        draw.rectangle((x, y, r-1, b-1), fill=ink)
    image.save(path)

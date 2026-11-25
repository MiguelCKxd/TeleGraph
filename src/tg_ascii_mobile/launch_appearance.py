"""Native launch presentation, read from the same choices as the chat window."""

from tg_ascii.logos import asset_path, brand_asset_path
from tg_ascii.preferences import Preferences


def launch_appearance(core, system_dark):
    settings = (core.prefs or Preferences(core.root)).values
    theme = settings.get('theme', 'dark')
    if theme == 'system':
        theme = 'dark' if system_dark else 'light'
    background, text = (('#f4f8f3', '#14532d') if theme == 'light' else ('#08100c', '#8cf5a6'))
    look = core.stored_appearance()
    logo = core.logo_photo_file(look.get('brand_photo')) if not core.locked else None
    if logo is None:
        logo = core.official_logo_file(look.get('official_logo', ''))
    saved = look.get('brand_logo')
    icon = look.get('icon', 'default')
    if logo is None and (isinstance(saved, dict) or isinstance(icon, str) and icon != 'default'):
        selected = core.brand_logo(saved if isinstance(saved, dict) else {}, icon if isinstance(icon, str) else 'default')
        try:
            logo = brand_asset_path(core.root / 'mobile', **selected, size=192)
        except (OSError, ValueError):
            pass
    selected_font = look.get('font', '')
    apple = getattr(core, 'system', '') == 'iOS'
    fonts = {
        '': 'monospace', 'courier': 'Courier New' if apple else 'monospace', 'mono': 'monospace',
        'book': 'Georgia' if apple else 'serif', 'classic': 'Palatino' if apple else 'serif',
        'serif': 'Georgia' if apple else 'serif', 'humanist': 'Trebuchet MS' if apple else 'sans-serif',
        'rounded': 'rounded' if apple else 'sans-serif',
        'sf_rounded': 'rounded' if apple else 'sans-serif', 'sf_mono': 'monospace',
        'new_york': 'system-serif' if apple else 'serif', 'sf_compact': 'SF Compact' if apple else 'system',
        'condensed': 'Arial Narrow' if apple else 'sans-serif-condensed',
        'light': 'system' if apple else 'sans-serif-light', 'medium': 'system' if apple else 'sans-serif-medium',
        'noto_serif': 'Georgia' if apple else 'serif', 'typewriter': 'Courier New' if apple else 'serif-monospace',
        'casual': 'Snell Roundhand' if apple else 'casual', 'handwriting': 'Snell Roundhand' if apple else 'cursive',
        'smallcaps': 'system' if apple else 'sans-serif-smallcaps',
    }
    effects = look.get('effects')
    effects = effects if isinstance(effects, dict) else {}
    dim = look.get('dim', 55)
    return {
        'title': settings.get('app_display_name') or 'TeleGraph',
        'background': settings.get('background_color') or background,
        'foreground': settings.get('text_color') or text,
        'size': settings.get('font_size', 12),
        'logo': logo or asset_path('title-short', theme),
        'font': fonts.get(selected_font, 'system') if isinstance(selected_font, str) else 'system',
        'bold': bool(effects.get('text_bold')), 'italic': bool(effects.get('text_italic')),
        'wallpaper': core.background_file(look.get('background')) if not core.locked else None,
        'opacity': 1 - max(0, min(100, dim)) / 100 if type(dim) in (float, int) else .45,
    }


def set_apple_typeface(label, family):
    if family == 'system':
        return
    from rubicon.objc import ObjCClass, objc_const
    from rubicon.objc.runtime import load_library
    native = label._impl.native
    current = native.font
    uikit = load_library('UIKit')
    designs = {'monospace': 'Monospaced', 'rounded': 'Rounded', 'system-serif': 'Serif'}
    if family in designs:
        design = designs[family]
        system_design = objc_const(uikit, 'UIFontDescriptorSystemDesign' + design)
        descriptor = current.fontDescriptor.fontDescriptorWithDesign_(system_design)
    else:
        if not len(ObjCClass('UIFont').fontNamesForFamilyName_(family)):
            return
        attributes = {str(objc_const(uikit, 'UIFontDescriptorFamilyAttribute')): family}
        descriptor = ObjCClass('UIFontDescriptor').fontDescriptorWithFontAttributes_(attributes)
    if descriptor is not None:
        traits = current.fontDescriptor.symbolicTraits & 3  # user's bold and italic
        if traits:
            descriptor = descriptor.fontDescriptorWithSymbolicTraits_(traits) or descriptor
        resolved = ObjCClass('UIFont').fontWithDescriptor_size_(descriptor, current.pointSize)
        if resolved and (family in designs or str(resolved.familyName).casefold() == family.casefold()):
            native.font = resolved


def set_android_typeface(label, family):
    if family != 'system':
        from android.graphics import Typeface
        native = label._impl.native
        native.setTypeface(Typeface.create(family, native.getTypeface().getStyle()))


def set_launch_wallpaper(splash, look, system, activity=None):
    """Place the private interface background behind the native brand and title."""
    path = look['wallpaper']
    if path is None or not look['opacity']:
        return
    parent = splash._impl.native
    if system == 'iOS':
        from rubicon.objc import ObjCClass
        image = ObjCClass('UIImage').imageWithContentsOfFile_(str(path))
        if image is not None:
            layer = ObjCClass('UIImageView').alloc().initWithImage_(image)
            layer.frame = parent.bounds
            layer.autoresizingMask = 2 | 16  # flexible width and height
            layer.contentMode = 2  # scale aspect fill
            layer.clipsToBounds = True
            layer.alpha = look['opacity']
            parent.insertSubview_atIndex_(layer, 0)
    elif system == 'Android':
        from android.graphics import BitmapFactory
        from android.widget import ImageView
        from java import jclass
        bitmap = BitmapFactory.decodeFile(str(path))
        if bitmap is not None:
            layer = ImageView(activity)
            layer.setImageBitmap(bitmap)
            layer.setScaleType(jclass('android.widget.ImageView$ScaleType').CENTER_CROP)
            layer.setAlpha(float(look['opacity']))
            parent.addView(layer, 0, jclass('android.view.ViewGroup$LayoutParams')(-1, -1))

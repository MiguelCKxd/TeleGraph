"""Publisher-only native build. Never copy account sessions into a release."""
import argparse
from datetime import datetime, timezone
import hashlib
import getpass
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from typing import NamedTuple
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MODULES = ['windows_launcher.py','recovery.py','ui_work.py','sticker_search.py','translations_search.py','composer.py','message_translation.py','pin_order.py','translation_queue.py','mobile_icons.py','sender_identity.py','free_crop.py','official_icons.py','translations_editing.py','animated_emojis.py','animation.py','interface_background.py','telegram_wallpapers.py','wallpaper_render.py','custom_icon.py','translations_visual.py','translated_view.py','shared_media.py','appearance.py','desktop_settings.py','attachments.py','translations_customization.py','translations_profiles.py', 'profile_details.py', 'desktop_profile.py', '__init__.py', '__main__.py', 'auth.py', 'backend.py', 'desktop.py', 'typography.py', 'notifications.py', 'translations_v092.py', 'translations_v010.py', 'bot_buttons.py', 'desktop_bot_buttons.py', 'folder_features.py', 'desktop_folders.py', 'rich_preview.py', 'sticker_picker.py', 'image_gestures.py', 'interactions.py',
                  'desktop_service.py', 'i18n.py', 'preferences.py', 'accounts.py', 'transfers.py',
                  'telegram_features.py', 'desktop_features.py', 'media_viewer.py', 'demo_features.py', 'windows_drop.py', 'app_dialogs.py', 'desktop_plus.py',
                  'telegram_extras.py', 'translations.py', 'local_state.py', 'updater.py', 'themes.py', 'message_tools.py', 'desktop_tools.py', 'audio_engine.py', 'background.py', 'instance.py', 'scrolling.py', 'logos.py', 'desktop_actions.py', 'telegram_actions.py', 'links.py', 'video_metadata.py', 'translations_extra.py', 'messaging_features.py', 'desktop_modern.py', 'bubbles.py', 'image_tools.py', 'native_emoji.py', 'translations_v08.py', 'translations_v09.py']
sys.path.insert(0, str(ROOT))
# 3.2 (Claude): grouped authors, placeholder avatars, account photos, launchers and recents.
SOURCE_MODULES += ['default_avatar.py', 'sender_runs.py', 'account_photos.py', 'number_input.py',
                   'startup_look.py', 'launcher_names.py', 'recent_search_ui.py', 'recent_searches.py',
                   'settings_search.py', 'back_gesture.py']
SOURCE_MODULES += ['account_profile.py', 'customization_sync.py', 'desktop_customization.py',
                   'contact_appearance.py', 'contact_profile.py', 'contact_settings.py', 'ui.py',
                   'drafts.py', 'emoji_documents.py', 'interface_editor.py', 'interface_layout.py',
                   'interface_store.py', 'interface_windows.py', 'motion.py', 'profile_customization.py',
                   'telegram_drafts.py', 'text_layout.py', 'translations_effects.py', 'visual_effects.py', 'startup_accounts.py']
SOURCE_MODULES += ['advanced_editor.py','advanced_features.py','advanced_messaging.py','article_view.py',
                   'desktop_advanced.py','desktop_peer_tools.py','expandable_text.py','link_navigation.py',
                   'media_formats.py','media_gallery.py','media_retry.py','peer_tools.py','profile_media.py',
                   'profile_tabs.py','rich_articles.py','video_frames.py','advanced_updates.py',
                   'app_lock.py','native_auth.py','translations_v11.py','chat_capabilities.py',
                   'capability_cache.py','poll_attachments.py','poll_attachment_editor.py']
SOURCE_MODULES += ['calls.py', 'calls_native.py', 'calls_crypto.py', 'calls_process.py', 'calls_worker.py', 'desktop_calls.py',
                   'notification_delivery.py', 'push_windows.py', 'push_notifications.py',
                   'translations_v12.py']
from tg_ascii import APP_NAME, __version__, __edition__
from tg_ascii.logos import LEGACY_VARIANTS, filename, png_bytes
ASSETS = ['tg-as-dark.png', 'tg-as-light.png'] + [filename(v,t) for v in LEGACY_VARIANTS for t in ('dark','light')] + [f'mobile-{n}.png' for n in ('default', 'light', 'orange', 'blue', 'red', 'pink')]
from tg_ascii.auth import validate_credentials
from tg_ascii.translations_extra import LOCALE_FILES
from tg_ascii.translations_extended import LOCALE_FILES as EXTENDED_LOCALE_FILES
LOCALE_FILES = [*LOCALE_FILES, *EXTENDED_LOCALE_FILES]
SOURCE_MODULES += ['translations_extended.py', 'translations_playful.py', 'rtl_ui.py']
SOURCE_MODULES += ['gift_picker.py']
SOURCE_MODULES += ['translations_v13.py']
SOURCE_MODULES += ['calls_rpc_codec.py', 'calls_group_native.py', 'calls_group_worker.py']
SOURCE_MODULES += ['calls_group.py', 'calls_group_media.py', 'calls_source_volume.py']
SOURCE_MODULES += ['mac_camera.py', 'channel_calls.py', 'desktop_channel_calls.py']
SOURCE_MODULES += ['mac_media_access.py']
SOURCE_MODULES += ['community_management.py', 'desktop_community.py', 'timestamps.py', 'call_outcomes.py', 'notification_history.py', 'conference_invitations.py', 'desktop_conference.py', 'push_macos.py']
SOURCE_MODULES += ['desktop_call_pip.py', 'mac_call_pip.py']
SOURCE_MODULES += ['flood_control.py', 'media_cache.py', 'tk_safety.py']
SOURCE_MODULES += ['day_separators.py', 'gift_preview.py', 'native_open.py', 'device_contacts.py', 'contact_sync.py',
                   'desktop_contacts.py', 'app_lifecycle.py', 'attachment_preview.py', 'chat_menus.py', 'chat_activity.py',
                   'contact_tools.py', 'contact_list_view.py', 'article_carousel.py', 'translations_v14.py',
                   'translations_v14_world.py', 'contact_search.py']
# 1.4.1 / 1.5. A test checks that every tg_ascii module is listed.
SOURCE_MODULES += ['outbox.py', 'read_visibility.py', 'composer_keys.py', 'message_window.py', 'line_breaking.py',
                   'translations_v15.py', 'resources.py', 'preload.py', 'tree_fit.py', 'row_emoji.py', 'pane_memory.py', 'menu_style.py', 'app_menus.py', 'translations_v151.py', 'custom_menus.py', 'tl_codec.py', 'offline_store.py', 'pending_actions.py', 'app_data.py', 'translations_v153.py', 'autostart.py', 'saved_windows.py', 'window_settings.py', 'translations_v154.py', 'spanish_latam.py', 'linux_runtime.py', 'decode_pool.py', 'translations_v155.py', 'gpu_video.py', 'translations_v155_gpu.py', 'translations_v155_archive.py', 'translations_v156.py', 'devices.py', 'desktop_devices.py', 'emoji_usage.py', 'service_messages.py', 'translations_v30.py', 'secret_tl.py', 'secret_chats.py', 'translations_v3002.py']


def build_architecture():
    # On Windows ARM, platform.machine() can describe the host even when
    # Python (and therefore the executable we build) runs as emulated x64.
    target = sysconfig.get_platform().lower()
    windows_targets = {'win-amd64': 'x64', 'win-arm64': 'arm64', 'win32': 'x86'}
    return windows_targets.get(target, platform.machine().lower())


def runtime_tls_data():
    # Some redistributable Python runtimes load an adjacent public CA policy
    # file from ssl.py. Preserve that resource rather than changing TLS checks.
    import ssl
    policy = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
    return ['--add-data', str(policy) + os.pathsep + '.'] if policy.is_file() else []


def stage_source(destination, credentials):
    package = destination / 'tg_ascii'
    package.mkdir(parents=True)
    # Explicit source whitelist: never glob an account directory or config file.
    for name in SOURCE_MODULES:
        shutil.copyfile(ROOT / 'tg_ascii' / name, package / name)
    for asset in ASSETS:
        target = package / 'assets' / asset
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / 'tg_ascii' / 'assets' / asset, target)
    for name in LOCALE_FILES:
        target = package / 'locales' / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / 'tg_ascii' / 'locales' / name, target)
    templates = ROOT / 'tg_ascii' / 'interface_templates'
    if templates.is_dir():
        for path in templates.rglob('*'):
            if path.is_file() and not path.is_symlink() and path.suffix in ('.json', '.md', '.txt'):
                target = package / 'interface_templates' / path.relative_to(templates)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
    shutil.copyfile(ROOT / 'run.py', destination / 'run.py')
    if credentials:
        number, secret = validate_credentials(*credentials)
        with (package / '_app_credentials.py').open('w', encoding='utf-8') as stream:
            stream.write(f'API_ID = {number!r}\nAPI_HASH = {secret!r}\n')
    return destination


def sdl2_binaries():
    """SDL2 for the GPU video window (complex feature "GPU video in group calls").

    On macOS SDL2 ships as SDL2.framework; collected as a binary its 'SDL2'
    file lands next to the 'sdl2' package and collides on case-insensitive
    disks, so only the core framework is copied, at its own path."""
    import importlib.util
    spec = importlib.util.find_spec('sdl2dll')
    if spec is None:
        return []
    if platform.system().lower() != 'darwin':
        return ['--collect-all', 'sdl2dll']
    folder = Path(spec.origin).parent
    framework = folder / 'dll' / 'SDL2.framework'
    return ['--collect-submodules', 'sdl2dll',
            '--add-data', f'{folder / "__init__.py"}{os.pathsep}sdl2dll',
            '--add-data', f'{framework}{os.pathsep}sdl2dll/dll/SDL2.framework']


class MacPushSigning(NamedTuple):
    profile: Path
    identity: str
    entitlements: dict


def mac_push_signing(profile):
    """Only sign for APNs with an explicit profile and one of its certified identities."""
    result = subprocess.run(['security', 'cms', '-D', '-i', str(profile)], capture_output=True, check=True)
    data = plistlib.loads(result.stdout)
    allowed = data['Entitlements']
    team = allowed.get('com.apple.developer.team-identifier')
    app_id = allowed.get('com.apple.application-identifier')
    environment = allowed.get('com.apple.developer.aps-environment')
    prefixes = data.get('ApplicationIdentifierPrefix', ())
    if ('OSX' not in data.get('Platform', ()) or team not in data.get('TeamIdentifier', ())
            or app_id not in {prefix + '.org.tgas.desktop' for prefix in prefixes}
            or environment not in ('development', 'production')
            or data['ExpirationDate'].replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)):
        raise ValueError('El perfil debe estar vigente y autorizar APNs para org.tgas.desktop en macOS.')
    identities = subprocess.run(['security', 'find-identity', '-v', '-p', 'codesigning'],
                                capture_output=True, check=True, text=True).stdout
    fingerprints = {hashlib.sha1(der).hexdigest().upper() for der in data['DeveloperCertificates']}
    for line in identities.splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[1] not in fingerprints:
            continue
        if environment == 'production' and '"Developer ID Application:' not in line:
            continue  # The ZIP is distributed outside the Mac App Store.
        entitlements = {key: allowed[key] for key in ('com.apple.application-identifier',
                         'com.apple.developer.team-identifier', 'com.apple.developer.aps-environment')}
        return MacPushSigning(profile, fields[1], entitlements)
    raise ValueError('No hay una identidad válida del perfil para firmar esta app de macOS.')


def prepare_mac_calls_extension(path):
    """Remap diagnostic __FILE__ paths in the prebuilt calls engine, without moving native data."""
    from macholib.MachO import MachO
    import re

    raw = path.read_bytes()
    homes = list(re.finditer(rb'/Users/[A-Za-z0-9_.-]+/', raw))
    if not homes:
        return False
    spans = []
    for header in MachO(str(path)).headers:
        for _, command, sections in header.commands:
            if not hasattr(command, 'nsects'):
                continue
            for section in sections:
                if section.sectname.rstrip(b'\x00') == b'__cstring':
                    start = header.offset + section.offset
                    spans.append((start, start + section.size))
    clean = bytearray(raw)
    for match in homes:
        if not any(start <= match.start() and match.end() <= end for start, end in spans):
            raise ValueError('Build path outside a native diagnostic string in the calls engine')
        prefix = b'/build/' + b'_' * (len(match[0]) - 8) + b'/'
        clean[match.start():match.end()] = prefix
    path.write_bytes(clean)
    return True


def build_mac_dock_plugin(app, identifier):
    """The Dock loads this signed plug-in when the main app is closed."""
    bundle = app / 'Contents/PlugIns/TeleGraph.docktileplugin'
    contents = bundle / 'Contents'
    executable = contents / 'MacOS/TeleGraphDockIcon'
    executable.parent.mkdir(parents=True, exist_ok=True)
    (contents / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundlePackageType': 'BNDL', 'CFBundleExecutable': executable.name,
        'CFBundleIdentifier': identifier + '.dockicon', 'CFBundleVersion': __version__,
        'NSPrincipalClass': 'TeleGraphDockIcon',
    }))
    binary = app / 'Contents/MacOS/TG-ASCII'
    architectures = subprocess.check_output(['xcrun', 'lipo', '-archs', str(binary)], text=True).split()
    flags = [flag for arch in architectures for flag in ('-arch', arch)]
    subprocess.run(['xcrun', 'clang', '-bundle', '-fobjc-arc', '-Os', '-mmacosx-version-min=11.0',
                    *flags, '-framework', 'AppKit', '-framework', 'ImageIO', '-framework', 'CoreGraphics',
                    str(ROOT / 'tools/macos/TeleGraphDockIcon.m'), '-o', str(executable)], check=True)
    return bundle


def slim_linux_bundle(app):
    """3.0.0.2: lighter Linux downloads and installs.

    * Wheels such as PyAV and NumPy ship their libraries in ``<name>.libs``;
      PyInstaller copied each one again to ``_internal``. Same bytes: the copy
      becomes a relative link (about 150 MB installed on x86_64).
    * Debug sections of native libraries are removed (``strip --strip-debug``
      keeps every symbol the loader uses). The call engine alone carried 110 MB.
    Returns the bytes saved."""
    import filecmp
    internal = app / '_internal'
    before = sum(path.stat().st_size for path in app.rglob('*') if path.is_file() and not path.is_symlink())
    originals = {}
    for libs in sorted(internal.glob('*.libs')):
        for path in libs.iterdir():
            if path.is_file() and not path.is_symlink():
                originals.setdefault(path.name, path)
    for path in sorted(internal.iterdir()):
        twin = originals.get(path.name)
        if twin is not None and path.is_file() and not path.is_symlink() and filecmp.cmp(path, twin, shallow=False):
            path.unlink()
            path.symlink_to(twin.relative_to(internal))
    strip = shutil.which('strip')
    if strip:
        for path in sorted(app.rglob('*')):
            if path.is_symlink() or not path.is_file() or path.stat().st_size < 256 * 1024:
                continue
            with path.open('rb') as stream:
                if stream.read(4) != b'\x7fELF':
                    continue
            subprocess.run([strip, '--strip-debug', '--preserve-dates', str(path)], check=False, capture_output=True)
    else:
        print('Aviso: falta strip (binutils); las bibliotecas conservan su informacion de depuracion.')
    after = sum(path.stat().st_size for path in app.rglob('*') if path.is_file() and not path.is_symlink())
    return before - after


def zip_tree(app, archive, label):
    """Zip a portable build keeping its symbolic links (the updater and the
    Debian packager recreate them)."""
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(app.rglob('*')):
            name = (Path(label) / path.relative_to(app)).as_posix()
            if path.is_symlink():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (0o120777 << 16)
                bundle.writestr(info, os.readlink(path))
            elif path.is_file():
                bundle.write(path, name)


def configure_mac_bundle(app, signing=None):
    path = app / 'Contents' / 'Info.plist'
    with path.open('rb') as stream: info = plistlib.load(stream)
    info['NSMicrophoneUsageDescription'] = 'TeleGraph uses the microphone when you choose Record or start or answer a call.'
    info['NSCameraUsageDescription'] = 'TeleGraph uses the camera only when you start or answer with video, or enable the camera during a call.'
    info['NSFaceIDUsageDescription'] = 'Unlock your TeleGraph interface with device authentication when you enable app lock.'
    info['NSContactsUsageDescription'] = 'TeleGraph reads your contacts only when you turn on Sync contacts, and saves a contact only when you ask it to.'
    info['CFBundleIdentifier'] = 'org.tgas.desktop'
    info['CFBundleDisplayName'] = APP_NAME
    info['CFBundleName'] = APP_NAME
    info['NSUserNotificationAlertStyle'] = 'banner'
    # Wheels installed from a path may keep the build machine's location in PEP 610 metadata.
    # Compiled copies of a package's license files are also local build artifacts.
    for metadata in (app / 'Contents/Resources').glob('*.dist-info'):
        (metadata / 'direct_url.json').unlink(missing_ok=True)
        licenses = metadata / 'licenses'
        if licenses.is_dir():
            for cache in licenses.rglob('__pycache__'):
                shutil.rmtree(cache)
    plugin = build_mac_dock_plugin(app, info['CFBundleIdentifier'])
    info['NSDockTilePlugIn'] = plugin.name
    # PyInstaller leaves 0.0.0; Finder, notifications and crash reports used it.
    # Apple allows three numbers in the short version; the build keeps all four.
    info['CFBundleShortVersionString'] = '.'.join(__version__.split('.')[:3])
    info['CFBundleVersion'] = __version__
    with path.open('wb') as stream: plistlib.dump(info, stream)

    identity = '-'
    code_options = []
    entitlement_options = []
    if signing:
        profile, identity, entitlements = signing
        shutil.copyfile(profile, app / 'Contents' / 'embedded.provisionprofile')
        entitlements_path = app.parent / 'entitlements.plist'
        entitlements_path.write_bytes(plistlib.dumps(entitlements))
        entitlement_options = ['--entitlements', str(entitlements_path)]
        if entitlements['com.apple.developer.aps-environment'] == 'production':
            code_options = ['--options', 'runtime', '--timestamp']

    try:
        subprocess.run(['xattr', '-d', 'com.apple.FinderInfo', str(app)], capture_output=True)
    except Exception:
        pass
    try:
        subprocess.run(['xattr', '-cr', str(app)], capture_output=True)
    except Exception:
        pass

    for engine in (app / 'Contents/Frameworks').glob('ntgcalls*.so'):
        if prepare_mac_calls_extension(engine):
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', identity, *code_options, str(engine)], check=True, capture_output=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', identity, *code_options, str(plugin)], check=True, capture_output=True)
    # Nested frameworks (SDL2) are signed before the app itself.
    for framework in sorted(app.glob('Contents/**/*.framework'), key=lambda path: len(path.parts), reverse=True):
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', identity, *code_options, str(framework)], check=True, capture_output=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', identity, *code_options, *entitlement_options, str(app)], check=True, capture_output=True)


def windows_version_resource(work):
    """Use the public product name in Explorer and Task Manager."""
    parts = [int(part) for part in __version__.split('.')]
    numeric = tuple(parts + [0] * (4 - len(parts)))
    strings = {'ProductName': APP_NAME, 'FileDescription': APP_NAME,
               'InternalName': APP_NAME, 'OriginalFilename': 'TG-ASCII.exe',
               'FileVersion': __version__, 'ProductVersion': __version__}
    entries = ',\n'.join(f'        StringStruct({key!r}, {value!r})' for key, value in strings.items())
    path = work / 'version-info.txt'
    path.write_text(f"""VSVersionInfo(
    ffi=FixedFileInfo(filevers={numeric}, prodvers={numeric}, OS=0x40004, fileType=1),
    kids=[StringFileInfo([StringTable('040904B0', [
{entries}
    ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding='utf-8')
    return path


def build(output, credentials=None, demo_only=False, keep_app=False, mac_push_profile=None, user_api=False):
    if not importlib.util.find_spec('PyInstaller'):
        raise RuntimeError('Falta PyInstaller. El desarrollador debe instalar requirements-build.txt.')
    if user_api and (demo_only or credentials):
        raise ValueError('La edición con API propia se compila sin credenciales del editor y sin modo demo.')
    if not demo_only and not user_api and not credentials:
        raise ValueError('Las compilaciones para usuarios necesitan las credenciales de la aplicacion.')
    system = platform.system().lower()
    architecture = build_architecture()
    if mac_push_profile and system != 'darwin':
        raise ValueError('--mac-push-profile sólo se aplica a macOS.')
    signing = mac_push_signing(mac_push_profile) if mac_push_profile else None
    label = f'{APP_NAME}-{__edition__}-{system}-{architecture}' + ('-DEMO' if demo_only else '')
    if signing and signing.entitlements['com.apple.developer.aps-environment'] == 'development':
        label += '-DEVELOPMENT'
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f'{label}.zip'
    if archive.exists() or (keep_app and (output / label).exists()):
        raise FileExistsError(f'Ya existe {archive.name}; elige otra carpeta de salida.')
    # Windows can keep a loaded .pyd locked briefly after the startup check.
    # Best-effort cleanup must not turn a completed ZIP into a build failure,
    # or hide the original exception if compilation itself failed.
    with tempfile.TemporaryDirectory(prefix='tg-ascii-build-', ignore_cleanup_errors=True) as folder:
        work = Path(folder)
        source = stage_source(work / 'source', None if demo_only else credentials)
        if user_api:
            (source / 'tg_ascii' / '_user_api.py').write_text('ENABLED = True\n', encoding='utf-8')
        update_url = os.environ.get('TG_UPDATE_URL', '')
        if update_url:
            from urllib.parse import urlsplit
            if urlsplit(update_url).scheme != 'https': raise ValueError('TG_UPDATE_URL must use HTTPS')
            (source / 'tg_ascii' / '_update_channel.py').write_text(f'UPDATE_URL = {update_url!r}\n', encoding='utf-8')
        if demo_only:
            (source / 'run.py').write_text("import sys\nfrom tg_ascii.__main__ import main\nif __name__ == '__main__':\n    import multiprocessing\n    multiprocessing.freeze_support()\n    if '--demo' not in sys.argv:\n        sys.argv.append('--demo')\n    main()\n", encoding='utf-8')
        # These packages expose data/licenses or use dynamic imports.
        command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                   '--onedir', '--windowed', '--name', 'TG-ASCII',
                   '--distpath', str(work / 'dist'), '--workpath', str(work / 'build'),
                   '--specpath', str(work / 'spec'), '--paths', str(source),
                   '--collect-all', 'telethon', '--hidden-import', 'tkinter',
                   '--hidden-import', 'tkinterdnd2', '--collect-all', 'PIL',
                   '--collect-all', 'sounddevice', '--collect-all', 'soundfile',
                   '--collect-all', 'pystray', '--collect-all', 'qrcode',
                   '--collect-all', 'pyphen', '--collect-submodules', 'sdl2', *sdl2_binaries(),
                   '--additional-hooks-dir', str(ROOT / 'tools' / 'hooks'),
                   '--add-data', str(source / 'tg_ascii' / 'assets') + os.pathsep + 'tg_ascii/assets',
                   '--add-data', str(source / 'tg_ascii' / 'locales') + os.pathsep + 'tg_ascii/locales',
                   '--copy-metadata', 'telethon',
                   '--copy-metadata', 'pyaes', '--copy-metadata', 'rsa',
                   '--copy-metadata', 'pyasn1',
                   str(source / 'run.py')]
        if user_api:
            command[-1:-1] = ['--hidden-import', 'tg_ascii._user_api', '--exclude-module', 'tg_ascii._app_credentials']
        for module in ('cryptg','rlottie_python','av','resvg_py','ntgcalls'):
            if importlib.util.find_spec(module) is not None:
                command[-1:-1] = ['--collect-all', module]
        if importlib.util.find_spec('pytgcalls') is not None:
            command[-1:-1] = ['--collect-all', 'pytgcalls', '--copy-metadata', 'py-tgcalls']
        if sys.platform == 'darwin' and importlib.util.find_spec('AVKit') is not None:
            command[-1:-1] = ['--collect-submodules', 'AVKit']
        if sys.platform == 'darwin' and importlib.util.find_spec('AVFoundation') is not None:
            command[-1:-1] = ['--collect-submodules', 'AVFoundation', '--collect-submodules', 'CoreMedia']
        if (source / 'tg_ascii' / 'interface_templates').is_dir():
            command[-1:-1] = ['--add-data', str(source / 'tg_ascii' / 'interface_templates') + os.pathsep + 'tg_ascii/interface_templates']
        command[-1:-1] = runtime_tls_data()
        if system == 'darwin':
            if signing and signing.entitlements['com.apple.developer.aps-environment'] == 'production':
                # Every Mach-O library must belong to the team for hardened runtime library validation.
                command[-1:-1] = ['--codesign-identity', signing.identity]
            command[-1:-1] = ['--hidden-import', 'UserNotifications','--collect-submodules','LocalAuthentication']
            if importlib.util.find_spec('Contacts') is not None:
                command[-1:-1] = ['--collect-submodules', 'Contacts']
        elif system == 'linux':
            # 1.5.5: tray icon through AppIndicator (PyGObject); typelibs come from the system.
            command[-1:-1] = ['--hidden-import', 'pystray._appindicator', '--hidden-import', 'pystray._xorg',
                              '--hidden-import', 'gi', '--collect-submodules', 'gi']
        elif system == 'windows':
            if importlib.util.find_spec('winui3') is not None:
                command[-1:-1] = ['--collect-all', 'winui3']
            command[-1:-1] = ['--version-file', str(windows_version_resource(work)),
                              '--collect-all', 'winrt', '--hidden-import', 'winrt.system',
                              '--hidden-import', 'winrt.windows.ui.notifications',
                              '--hidden-import', 'winrt.windows.foundation.collections',
                              '--hidden-import', 'winrt.windows.data.xml.dom']
            if importlib.util.find_spec('winrt.windows.applicationmodel.contacts') is not None:
                command[-1:-1] = ['--hidden-import', 'winrt.windows.applicationmodel.contacts']
            try:
                push_available = importlib.util.find_spec('winrt.windows.networking.pushnotifications') is not None
            except ModuleNotFoundError:
                push_available = False
            if push_available:
                command[-1:-1] = ['--hidden-import', 'winrt.windows.networking.pushnotifications']
        if system in ('darwin', 'windows'):
            from PIL import Image
            from io import BytesIO
            icon = work / ('TeleGraph.icns' if system == 'darwin' else 'TeleGraph.ico')
            with Image.open(BytesIO(png_bytes(size=1024 if system == 'darwin' else 256))) as picture:
                picture.save(icon)
            command[-1:-1] = ['--icon', str(icon)]
        print('Compilando TeleGraph... puede tardar unos minutos.', flush=True)
        build_env = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(work / 'pyinstaller-cache'))
        result = subprocess.run(command, cwd=source, env=build_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if result.returncode:
            # No credentials are command arguments; still redact possible diagnostic output.
            details = result.stdout
            if credentials:
                details = details.replace(credentials[1], '[REDACTED]')
            raise RuntimeError('La compilacion fallo:\n' + details[-7000:])
        app = work / 'dist' / ('TG-ASCII.app' if system == 'darwin' else 'TG-ASCII')
        if system == 'darwin':
            configure_mac_bundle(app, signing)
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True, capture_output=True)
        if system == 'linux':
            # GTK reads the user's theme and icon packs from XDG_DATA_DIRS.
            # The GI hook otherwise bundles thousands of unrelated host desktop assets.
            for folder in ('icons', 'themes'):
                host_assets = app / '_internal' / 'share' / folder
                if host_assets.is_dir():
                    shutil.rmtree(host_assets)
            saved = slim_linux_bundle(app)
            print(f'Paquete Linux aligerado en {saved / 1e6:.0f} MB.', flush=True)
        executable = app / ('Contents/MacOS/TG-ASCII' if system == 'darwin' else
                            'TG-ASCII.exe' if system == 'windows' else 'TG-ASCII')
        report = work / 'gui-self-test.json'
        smoke = subprocess.run([str(executable), '--self-test', str(report)], capture_output=True, text=True, timeout=60)
        if smoke.returncode or not report.exists():
            details = f"Returncode: {smoke.returncode}\nStdout: {smoke.stdout}\nStderr: {smoke.stderr}"
            if credentials:
                details = details.replace(credentials[1], '[REDACTED]')
            raise RuntimeError('El ejecutable no supero la prueba de arranque.\n' + details)
        result = json.loads(report.read_text(encoding='utf-8'))
        if result.get('version') != __version__ or not result.get('gui') or result.get('demo_chats') != 3:
            raise RuntimeError('El ejecutable no supero la prueba de interfaz.')
        if not result.get('audio_codec'):
            raise RuntimeError('El ejecutable no incluye un codificador Opus funcional.')
        if importlib.util.find_spec('ntgcalls') is not None and not result.get('calls_available'):
            raise RuntimeError('El ejecutable no reconoce el motor de llamadas instalado.')
        if not result.get('drag_drop'):
            print('Aviso: arrastrar archivos no disponible en este runtime; el boton Adjuntar sigue activo.')
        manifest = {'app': 'TG-ASCII', 'version': __version__, 'target': system + '-' + architecture}
        (app / 'release.json' if system != 'darwin' else work / 'dist' / 'release.json').write_text(json.dumps(manifest), encoding='utf-8')
        readme = app / 'READ-ME.txt' if system != 'darwin' else work / 'dist' / 'READ-ME.txt'
        shutil.copyfile(ROOT / 'FOR-FRIENDS.txt', readme)
        for path in app.rglob('*'):
            if path.is_file() and ('.session' in path.name or path.name in ('config.json', '.env')):
                raise RuntimeError('No se publica: se detecto un archivo de datos personales.')
        # ditto preserves the symbolic links and executable permissions used
        # by macOS bundles. The Windows distribution has ordinary files.
        if system == 'darwin':
            package = work / label
            package.mkdir()
            app.rename(package / app.name)
            app = package / app.name
            readme.rename(package / readme.name)
            (work / 'dist' / 'release.json').rename(package / 'release.json')
            subprocess.run(['/usr/bin/ditto', '-c', '-k', '--norsrc', '--noextattr', '--keepParent',
                            str(package), str(archive.resolve())], check=True)
        else:
            zip_tree(app, archive, label)
        if keep_app:
            # Keep the verified app outside the temporary build tree before cleanup.
            destination=output / label
            if system=='darwin': shutil.copytree(package,destination,symlinks=True)
            else: shutil.copytree(app,destination,symlinks=True)
    return archive


def launch_built_app(archive, system=None):
    system=system or platform.system().lower()
    folder=archive.with_suffix('').resolve()
    executable=folder / ('TG-ASCII.app' if system=='darwin' else 'TG-ASCII.exe' if system=='windows' else 'TG-ASCII')
    if not executable.exists(): raise FileNotFoundError(executable)
    if system=='darwin': subprocess.run(['/usr/bin/open',str(executable)],check=True)
    else:
        options={'stdin':subprocess.DEVNULL,'stdout':subprocess.DEVNULL,'stderr':subprocess.DEVNULL,'cwd':str(folder)}
        if system=='windows': options['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else: options['start_new_session']=True
        subprocess.Popen([str(executable)],**options)
    return executable


def main():
    parser = argparse.ArgumentParser(description='Generar TeleGraph para el sistema actual. Solo para el desarrollador.')
    parser.add_argument('--output', type=Path, default=ROOT / 'releases')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--user-api', action='store_true', help='Crear una variante de desarrollo que pide API ID y hash al iniciar')
    mode.add_argument('--demo-only', action='store_true', help='Compilar solo la demo; sin acceso a cuentas')
    parser.add_argument('--mac-push-profile', type=Path,
                        help='Perfil APNs para macOS. Los ZIP con perfil de desarrollo se marcan DEVELOPMENT.')
    parser.add_argument('--launch', action='store_true', help='Conservar y abrir la app verificada al terminar')
    parser.add_argument('--check', action='store_true', help='Comprobar las herramientas sin leer claves ni compilar')
    args = parser.parse_args()
    if args.check:
        ready = importlib.util.find_spec('PyInstaller') is not None
        print(json.dumps({'system': platform.system(), 'architecture': build_architecture(), 'pyinstaller_available': ready}))
        return 0 if ready else 2
    credentials = None
    if not args.demo_only and not args.user_api:
        if not sys.stdin.isatty() and not all(os.environ.get(key) for key in
                ('TG_APP_API_ID', 'TG_APP_API_HASH')):
            print('Faltan TG_APP_API_ID y TG_APP_API_HASH. Usa --demo-only o configura las credenciales de la app.', file=sys.stderr)
            return 1
        app_id = os.environ.get('TG_APP_API_ID') or input('API ID de TeleGraph (desarrollador): ')
        app_hash = os.environ.get('TG_APP_API_HASH') or getpass.getpass('API hash de TeleGraph (desarrollador): ')
        credentials = validate_credentials(app_id, app_hash)
        print('El paquete incluira la identidad API de la app; puede extraerse del binario.')
        print('No incluye ni necesita tu archivo de sesion, tus chats ni tus codigos personales.')
        if os.environ.get('TG_BUILD_EMBED_APP_CREDENTIALS') != 'yes':
            if not sys.stdin.isatty():
                print('Falta autorizacion para incorporar las credenciales. Configura TG_BUILD_EMBED_APP_CREDENTIALS=yes.', file=sys.stderr)
                return 1
            if input('Incluir estas credenciales de app en la descarga? [s/N]: ').strip().lower() not in ('s', 'si', 'sí', 'y', 'yes'):
                print('Compilacion cancelada. No se ha generado el paquete.')
                return 1
    try:
        path = build(args.output, credentials, args.demo_only, keep_app=args.launch, mac_push_profile=args.mac_push_profile, user_api=args.user_api)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(path)
    if args.launch:
        try:
            executable=launch_built_app(path)
            print('App preparada y apertura solicitada: ' + str(executable))
        except (OSError,subprocess.SubprocessError):
            print('El ZIP se creo correctamente, pero no se pudo abrir la app. Abrela desde: ' + str(path.with_suffix('')),file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Give the generated projects the final store identifiers.

Briefcase derives ids from the app name (org.tgas.tg-ascii-mobile); the
stores already know TG-ASCII as org.tgas.android and org.tgas.ios.
"""
import os
from pathlib import Path
import re
import sys

APP = sys.argv[2] if len(sys.argv) > 2 else 'tg_ascii_mobile'
WATCH = APP == 'tg_ascii_watch'          # Wear OS: standalone watch app
LEGACY_WEAR = WATCH and os.environ.get('WEAR_LEGACY') == '1'
ANDROID_ID = 'org.tgas.wear' if LEGACY_WEAR else 'org.tgas.android'
IOS_ID = 'org.tgas.ios'
IOS_LAUNCH_STORYBOARD = 'TeleGraphLaunch'
build = Path(__file__).resolve().parents[1] / 'build' / APP
platform = sys.argv[1].lower()

# Briefcase writes the version only when it creates a project; keep it in
# step with pyproject.toml on every build.
import tomllib
VERSION = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text())['tool']['briefcase']['version']
major, minor, patch = (int(part) for part in VERSION.split('.')[:3])
# build-number: raised for every published mobile build of the same version
# (Android needs a higher versionCode, TestFlight a new CFBundleVersion).
BUILD = int((Path(__file__).resolve().parents[1] / 'build-number').read_text().strip() or 1)
VERSION_CODE = major * 1000000 + minor * 10000 + patch * 100 + BUILD   # Briefcase's scheme + build
IOS_BUILD = str(BUILD)
# Alternative launcher icons (tools/make_alt_icons.py), chosen in Settings.
# Privacy manifest: no tracking, no data collected; file timestamps are read
# only inside the app's container (Python's os.stat), boot-relative time for
# timers (time.monotonic).
PRIVACY_MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>NSPrivacyTracking</key>
	<false/>
	<key>NSPrivacyTrackingDomains</key>
	<array/>
	<key>NSPrivacyCollectedDataTypes</key>
	<array/>
	<key>NSPrivacyAccessedAPITypes</key>
	<array>
		<dict>
			<key>NSPrivacyAccessedAPIType</key>
			<string>NSPrivacyAccessedAPICategoryFileTimestamp</string>
			<key>NSPrivacyAccessedAPITypeReasons</key>
			<array>
				<string>C617.1</string>
			</array>
		</dict>
		<dict>
			<key>NSPrivacyAccessedAPIType</key>
			<string>NSPrivacyAccessedAPICategorySystemBootTime</string>
			<key>NSPrivacyAccessedAPITypeReasons</key>
			<array>
				<string>35F9.1</string>
			</array>
		</dict>
	</array>
</dict>
</plist>
"""
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from tg_ascii_mobile.native_logos import LEGACY, NATIVE_LOGOS
from launcher_art import android_notification_icon, android_vector, ios_image
ALT_ICONS = tuple(key for key in NATIVE_LOGOS if key != 'default')
ICONS_DIR = Path(__file__).resolve().parents[1] / 'icons' / 'alt'

def android_icon_aliases(text):
    """The launcher entry moves to <activity-alias> elements, one per icon;
    the app enables one and disables the rest (app.install_icon_switcher)."""
    launcher = re.compile(r'\s*<intent-filter>\s*<action android:name="android.intent.action.MAIN" />\s*'
                          r'<category android:name="android.intent.category.LAUNCHER" />\s*</intent-filter>')
    match = re.search(r'<activity\b[^>]*android:name="org.beeware.android.MainActivity"[^>]*>(.*?)</activity>', text, re.S)
    if match and launcher.search(match.group(1)):
        body = launcher.sub('', match.group(1), count=1)
        text = text[:match.start(1)] + body + text[match.end(1):]
    text = re.sub(r'\s*<!-- tg-ascii icons -->.*?<!-- /tg-ascii icons -->', '', text, flags=re.S)
    # Disabling the alias of a running activity closes its task on Android.
    # Only this short-lived launcher should ever run under an icon alias.
    aliases = [
        '        <activity android:name="org.tgas.launcher.LauncherActivity" android:exported="false"\n'
        '            android:theme="@android:style/Theme.NoDisplay" android:noHistory="true"\n'
        '            android:excludeFromRecents="true" android:taskAffinity="" />'
    ]
    for name in ('default',) + ALT_ICONS:
        icon = 'ic_launcher' if name == 'default' else f'ic_launcher_{name}'
        aliases.append(
            f'        <activity-alias android:name="{ANDROID_ID}.Icon{name.capitalize()}"\n'
            f'            android:targetActivity="org.tgas.launcher.LauncherActivity"\n'
            f'            android:enabled="{"true" if name == "default" else "false"}" android:exported="true"\n'
            f'            android:icon="@mipmap/{icon}" android:roundIcon="@mipmap/{icon}_round"\n'
            f'            android:label="@string/formal_name">\n'
            '            <intent-filter>\n'
            '                <action android:name="android.intent.action.MAIN" />\n'
            '                <category android:name="android.intent.category.LAUNCHER" />\n'
            '            </intent-filter>\n'
            '        </activity-alias>')
    block = '\n        <!-- tg-ascii icons -->\n' + '\n'.join(aliases) + '\n        <!-- /tg-ascii icons -->'
    return text.replace('</application>', block + '\n    </application>', 1)


def android_backup_rules(manifest, resources):
    """Keep session databases and device-bound secret chats off both backup transports."""
    import xml.etree.ElementTree as ET

    excluded = ('account.session', 'account.session-journal', 'account.session-wal', 'account.session-shm',
                'accounts', 'accounts.json', 'secret-chats', 'secret-exports', 'secret-previews')
    xml_dir = resources / 'xml'
    xml_dir.mkdir(parents=True, exist_ok=True)
    legacy = ET.Element('full-backup-content')
    modern = ET.Element('data-extraction-rules')
    for section in (legacy, ET.SubElement(modern, 'cloud-backup'), ET.SubElement(modern, 'device-transfer')):
        for name in excluded:
            ET.SubElement(section, 'exclude', domain='file', path=f'data/tg-ascii/{name}')
    for attribute, name, rules in (('fullBackupContent', 'telegraph_backup', legacy),
                                   ('dataExtractionRules', 'telegraph_data_extraction', modern)):
        ET.indent(rules)
        ET.ElementTree(rules).write(xml_dir / (name + '.xml'), encoding='utf-8', xml_declaration=True)
        ref = f'android:{attribute}="@xml/{name}"'
        if f'android:{attribute}=' in manifest:
            manifest = re.sub(r'android:' + attribute + r'="[^"]*"', ref, manifest, count=1)
        else:
            manifest = manifest.replace('<application', '<application\n        ' + ref, 1)
    return manifest


def android_firebase(project, configuration):
    """Install FCM only when building the phone app with its Firebase project."""
    import json
    import shutil

    app = project / 'app'
    config = app / 'google-services.json'
    gradle = app / 'build.gradle'
    root_gradle = project / 'build.gradle'
    manifest = app / 'src/main/AndroidManifest.xml'
    java = app / 'src/main/java/org/tgas/push/TelegraphMessagingService.java'
    worker = java.with_name('TelegraphPushWorker.java')
    service = (
        '\n        <service android:name="org.tgas.push.TelegraphMessagingService" android:exported="false">'
        '\n            <intent-filter>'
        '\n                <action android:name="com.google.firebase.MESSAGING_EVENT" />'
        '\n            </intent-filter>'
        '\n        </service>\n'
    )
    plugin = "apply plugin: 'com.google.gms.google-services'\n"
    classpath = "        classpath 'com.google.gms:google-services:4.5.0'\n"
    dependency = '    implementation "com.google.firebase:firebase-messaging:25.1.3"\n'
    work_runtime = '    implementation "androidx.work:work-runtime:2.10.5"\n'
    app_text = gradle.read_text().replace(plugin, '').replace(dependency, '').replace(work_runtime, '')
    root_text = root_gradle.read_text().replace(classpath, '')
    xml = manifest.read_text().replace(service, '')
    if configuration:
        content = Path(configuration).read_bytes()
        clients = json.loads(content).get('client', [])
        if not any(c.get('client_info', {}).get('android_client_info', {}).get('package_name') == ANDROID_ID
                   for c in clients):
            raise ValueError(f'Firebase configuration has no Android client for {ANDROID_ID}')
        config.write_bytes(content)
        java.parent.mkdir(parents=True, exist_ok=True)
        for source in (java, worker):
            shutil.copyfile(Path(__file__).with_name('android') / source.name, source)
        app_text = app_text.replace('dependencies {\n', 'dependencies {\n' + dependency + work_runtime, 1)
        app_text = app_text.rstrip() + '\n' + plugin
        root_text = root_text.replace('dependencies {\n', 'dependencies {\n' + classpath, 1)
        xml = xml.replace('    </application>', service + '    </application>', 1)
    else:
        config.unlink(missing_ok=True)
        java.unlink(missing_ok=True)
        worker.unlink(missing_ok=True)
    gradle.write_text(app_text)
    root_gradle.write_text(root_text)
    manifest.write_text(xml)


def ios_phone_privacy(project, text):
    """Add the phone's cache timestamps and elapsed-time use to its own bundle."""
    import plistlib

    xcode = project.parent.parent
    reasons = plistlib.loads(PRIVACY_MANIFEST.encode())['NSPrivacyAccessedAPITypes']
    (xcode / 'TGASCII' / 'PrivacyInfo.xcprivacy').write_bytes(
        plistlib.dumps({'NSPrivacyAccessedAPITypes': reasons}))
    ref = '50A500000000000000000001'
    resource = '50A500000000000000000002'
    if resource in text:
        return text
    # Anchor the file and its membership to the phone's launch storyboard.
    storyboard = f'{IOS_LAUNCH_STORYBOARD}.storyboard'
    entries = (
        ('PBXFileReference', f'{ref} /* PrivacyInfo.xcprivacy */ = {{isa = PBXFileReference; '
         'lastKnownFileType = text.xml; path = PrivacyInfo.xcprivacy; sourceTree = "<group>"; };'),
        ('PBXBuildFile', f'{resource} /* Phone privacy manifest in Resources */ = {{isa = PBXBuildFile; '
         f'fileRef = {ref} /* PrivacyInfo.xcprivacy */; }};'),
        (f'/* {storyboard} */,', f'{ref} /* PrivacyInfo.xcprivacy */,'),
        (f'/* {storyboard} in Resources */,', f'{resource} /* Phone privacy manifest in Resources */,'),
    )
    for anchor, entry in entries:
        if anchor.startswith('PBX'):
            anchor = f'/* Begin {anchor} section */'
            if text.count(anchor) != 1:
                raise ValueError(f'Missing Xcode section for the iPhone privacy manifest: {anchor}')
            text = text.replace(anchor, anchor + '\n\t\t' + entry)
        else:
            line = re.compile(r'^([ \t]*)[^\n]*' + re.escape(anchor) + r'$', re.M)
            text, count = line.subn(lambda m: m[0] + '\n' + m[1] + entry, text)
            if count != 1:
                raise ValueError('Could not locate the iPhone storyboard in its resources and group')
    return text


def ios_calls_framework(project, text):
    import json
    import plistlib
    import shutil
    import subprocess

    xcode = project.parent.parent
    support = xcode / 'Support'
    script = support / 'EmbedTeleGraphCalls.sh'
    shutil.copyfile(Path(__file__).with_name('ios') / 'embed_calls.sh', script)
    staged = support / 'TeleGraphCalls.framework'
    configuration = os.environ.get('TELEGRAPH_IOS_CALLS_FRAMEWORK')
    if configuration:
        source = Path(configuration).expanduser().resolve()
        if source.suffix == '.xcframework':
            source /= 'ios-arm64/TeleGraphCalls.framework'
        if source == staged.resolve():
            raise ValueError('Set TELEGRAPH_IOS_CALLS_FRAMEWORK to the original framework outside derived Xcode files')
        info = plistlib.loads((source / 'Info.plist').read_bytes())
        if info.get('CFBundleExecutable') != 'TeleGraphCalls':
            raise ValueError('The calls framework must expose the TeleGraphCalls executable')
        binary = source / 'TeleGraphCalls'
        metadata = subprocess.check_output(['xcrun', 'vtool', '-show-build', binary], text=True)
        architectures = subprocess.check_output(['xcrun', 'lipo', '-archs', binary], text=True).split()
        if not re.search(r'^\s*platform IOS\s*$', metadata, re.M) or architectures != ['arm64']:
            raise ValueError('The TeleGraphCalls framework must be an arm64 iPhoneOS build')
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns('Headers', 'Modules', '_CodeSignature'))
        manifest = staged / 'PrivacyInfo.xcprivacy'
        if not manifest.exists():
            manifest.write_text(PRIVACY_MANIFEST)
    elif staged.exists():
        shutil.rmtree(staged)

    ident = 'A1D0CA110000000000000001'
    label = 'Embed TeleGraph Calls'
    if ident in text:
        return text
    phase = (
        f'\t\t{ident} /* {label} */ = {{\n'
        '\t\t\tisa = PBXShellScriptBuildPhase;\n'
        '\t\t\talwaysOutOfDate = 1;\n'
        '\t\t\tbuildActionMask = 2147483647;\n'
        '\t\t\tfiles = ();\n'
        f'\t\t\tname = "{label}";\n'
        '\t\t\trunOnlyForDeploymentPostprocessing = 0;\n'
        '\t\t\tshellPath = /bin/sh;\n'
        '\t\t\tshellScript = ' + json.dumps('/bin/sh "$PROJECT_DIR/Support/EmbedTeleGraphCalls.sh"\n') + ';\n'
        '\t\t\tshowEnvVarsInLog = 0;\n'
        '\t\t};\n'
    )
    # Only the iPhone target has the template's first Embed Frameworks phase.
    anchor = re.search(r'^([ \t]+)[A-F0-9]+ /\* Embed Frameworks \*/,\n', text, re.M)
    marker = '/* End PBXShellScriptBuildPhase section */'
    if not anchor or marker not in text:
        raise ValueError('Unable to locate the iPhone target in the generated Xcode project')
    text = text[:anchor.end()] + f'{anchor[1]}{ident} /* {label} */,\n' + text[anchor.end():]
    return text.replace(marker, phase + marker, 1)


def android_calls_dependency(text, directory):
    """Use the local volume-enabled engine when a build supplies it."""
    import shutil
    from zipfile import ZipFile

    stock = '    implementation "io.github.pytgcalls:ntgcalls:3.0.5"'
    custom = "    implementation files('libs/telegraph-calls.aar')"
    staged = directory / 'libs' / 'telegraph-calls.aar'
    source = os.environ.get('TELEGRAPH_ANDROID_CALLS_AAR')
    text = text.replace(stock + '\n', '').replace(custom + '\n', '')
    if source:
        source = Path(source).expanduser().resolve()
        if source == staged.resolve():
            raise ValueError('Set the calls AAR path outside the generated Gradle project')
        required = {'classes.jar', 'libs/webrtc.jar', 'jni/arm64-v8a/libntgcalls.so'}
        with ZipFile(source) as archive:
            if not required.issubset(archive.namelist()):
                raise ValueError('Calls AAR must include the arm64 engine and Java classes')
        staged.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, staged)
    else:
        staged.unlink(missing_ok=True)
    return text.replace('dependencies {', 'dependencies {\n' + (custom if source else stock), 1)


if platform == 'android':
    import shutil
    gradle = build / 'android' / 'gradle' / 'app' / 'build.gradle'
    text = gradle.read_text()
    text = re.sub(r'applicationId "[^"]+"', f'applicationId "{ANDROID_ID}"', text)
    text = re.sub(r'versionCode \d+', f'versionCode {VERSION_CODE}', text)
    text = re.sub(r'versionName "[^"]+"', f'versionName "{VERSION} ({BUILD})"', text)
    # Briefcase applies Gradle dependencies at creation; update existing projects too.
    wearable = 'com.google.android.gms:play-services-wearable:20.0.1'
    dependencies = [] if LEGACY_WEAR else [wearable]
    if not WATCH:
        # Remove the original on-demand Play services scanner from existing projects.
        text = re.sub(r'^\s*implementation "com\.google\.android\.gms:play-services-(?:code-scanner|mlkit-barcode-scanning):[^"]+"\s*$', '', text, flags=re.M)
        dependencies.append('com.journeyapps:zxing-android-embedded:4.3.0')
        text = android_calls_dependency(text, gradle.parent)
        # Use the same NDK as the phone engine for AGP's release symbol split.
        # Without a selected NDK, AGP may package unstripped shared libraries.
        ndk = '    ndkVersion "28.1.13356709"'
        symbols = '            ndk.debugSymbolLevel "FULL"'
        if ndk not in text:
            text = text.replace('android {', 'android {\n' + ndk, 1)
        if symbols not in text:
            text = text.replace('        release {', '        release {\n' + symbols, 1)
    for dependency in dependencies:
        if dependency not in text:
            text = text.replace('dependencies {', f'dependencies {{\n    implementation "{dependency}"', 1)
    if LEGACY_WEAR:
        text = re.sub(r'^[ \t]*implementation "' + re.escape(wearable) + r'"\n', '\n', text, flags=re.M)
    # 3.0.0.2: phones, watches and this Mac's emulators are all arm64. The x86_64
    # copies of Python, OpenSSL and the call engine added ~42 MB to every APK.
    # TELEGRAPH_ANDROID_ABIS="arm64-v8a x86_64" restores them for an Intel emulator.
    abis = os.environ.get('TELEGRAPH_ANDROID_ABIS', 'arm64-v8a').split()
    if not abis or any(abi not in ('arm64-v8a', 'x86_64') for abi in abis):
        raise ValueError('TELEGRAPH_ANDROID_ABIS accepts arm64-v8a and x86_64')
    text = re.sub(r'abiFilters [^\n]+', 'abiFilters ' + ', '.join(f'"{abi}"' for abi in abis), text)
    gradle.write_text(text)
    manifest = build / 'android' / 'gradle' / 'app' / 'src' / 'main' / 'AndroidManifest.xml'
    text = manifest.read_text()
    text = re.sub(r'android:authorities="[^"]+\.fileprovider"', f'android:authorities="{ANDROID_ID}.fileprovider"', text)
    if 'enableOnBackInvokedCallback' not in text:
        # Back button handled by the app (Android 13+), see app.install_back_button.
        text = text.replace('<application', '<application\n        android:enableOnBackInvokedCallback="true"', 1)
    launcher_java = manifest.parent / 'java/org/tgas/launcher/LauncherActivity.java'
    launcher_java.parent.mkdir(parents=True, exist_ok=True)
    launcher_java.write_bytes((Path(__file__).parent / 'android/LauncherActivity.java').read_bytes())
    text = android_icon_aliases(text)
    if 'android:launchMode=' not in text:
        # One activity, so one core and one Telegram connection per session: the
        # launcher, a renamed icon alias or a notification can otherwise start a
        # second activity (and a second core) in the same process.
        text = text.replace('android:name="org.beeware.android.MainActivity"',
                            'android:name="org.beeware.android.MainActivity"\n            android:launchMode="singleTask"', 1)
    if WATCH:
        # A standalone Wear OS app (works without a phone app).
        if 'android.hardware.type.watch' not in text:
            text = text.replace('<application', '<uses-feature android:name="android.hardware.type.watch" />\n    <application', 1)
        if 'com.google.android.wearable.standalone' not in text:
            text = text.replace('</application>', '    <meta-data android:name="com.google.android.wearable.standalone" android:value="true" />\n    </application>', 1)
    else:
        # Notifications, calls, screen sharing, and the service that keeps the connection in the background.
        permissions = ('android.permission.RECORD_AUDIO', 'android.permission.MODIFY_AUDIO_SETTINGS',
                       'android.permission.POST_NOTIFICATIONS', 'android.permission.FOREGROUND_SERVICE',
                       'android.permission.FOREGROUND_SERVICE_REMOTE_MESSAGING',
                       'android.permission.FOREGROUND_SERVICE_PHONE_CALL',
                       'android.permission.FOREGROUND_SERVICE_MICROPHONE',
                       'android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK',
                       'android.permission.FOREGROUND_SERVICE_CAMERA',
                       'android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION',
                       'android.permission.MANAGE_OWN_CALLS',
                       'android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS')
        for permission in permissions:
            if f'"{permission}"' not in text:
                text = text.replace('<application', f'<uses-permission android:name="{permission}" />\n    <application', 1)
        if 'org.tgas.keepalive.KeepAliveService' not in text:
            text = text.replace('</application>', '    <service android:name="org.tgas.keepalive.KeepAliveService" android:exported="false"'
                                ' android:foregroundServiceType="remoteMessaging" />\n    </application>', 1)
        text = re.sub(r'(android:name="org.tgas.keepalive.KeepAliveService"[^>]*android:foregroundServiceType=)"[^"]+"',
                      r'\1"remoteMessaging"', text)
        java = build / 'android' / 'gradle' / 'app' / 'src' / 'main' / 'java' / 'org' / 'tgas' / 'keepalive'
        java.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).with_name('android') / 'KeepAliveService.java', java / 'KeepAliveService.java')
        calls = java.parent / 'calls'
        calls.mkdir(exist_ok=True)
        shutil.copyfile(Path(__file__).with_name('android') / 'CallCallbacks.java', calls / 'CallCallbacks.java')
        shutil.copyfile(Path(__file__).with_name('android') / 'GroupCallCallbacks.java', calls / 'GroupCallCallbacks.java')
        shutil.copyfile(Path(__file__).with_name('android') / 'ScreenShareService.java', calls / 'ScreenShareService.java')
        if 'org.tgas.calls.ScreenShareService' not in text:
            text = text.replace('</application>', '    <service android:name="org.tgas.calls.ScreenShareService"'
                                ' android:exported="false" android:foregroundServiceType="mediaProjection" />\n    </application>', 1)
        shutil.copyfile(Path(__file__).with_name('android') / 'IncomingCallAction.java', calls / 'IncomingCallAction.java')
        if 'org.tgas.calls.IncomingCallAction' not in text:
            text = text.replace('</application>', '    <receiver android:name="org.tgas.calls.IncomingCallAction"'
                                ' android:exported="false" />\n    </application>', 1)
        shutil.copyfile(Path(__file__).with_name('android') / 'TelegraphConnectionService.java',
                        calls / 'TelegraphConnectionService.java')
        if 'org.tgas.calls.TelegraphConnectionService' not in text:
            text = text.replace('</application>', '    <service android:name="org.tgas.calls.TelegraphConnectionService"'
                                ' android:exported="true" android:permission="android.permission.BIND_TELECOM_CONNECTION_SERVICE">'
                                '<intent-filter><action android:name="android.telecom.ConnectionService" /></intent-filter>'
                                '</service>\n    </application>', 1)
        shutil.copyfile(Path(__file__).with_name('android') / 'CallMediaService.java', calls / 'CallMediaService.java')
        if 'org.tgas.calls.CallMediaService' not in text:
            text = text.replace('</application>', '    <service android:name="org.tgas.calls.CallMediaService"'
                                ' android:exported="false" android:foregroundServiceType="phoneCall|microphone|mediaPlayback|camera" />\n    </application>', 1)
        text = re.sub(r'(android:name="org.tgas.calls.CallMediaService"[^>]*android:foregroundServiceType=)"[^"]+"',
                      r'\1"phoneCall|microphone|mediaPlayback|camera"', text)
        windows = java.parent / 'windows'
        windows.mkdir(exist_ok=True)
        shutil.copyfile(Path(__file__).with_name('android') / 'ChatWindowActivity.java', windows / 'ChatWindowActivity.java')
        if 'org.tgas.windows.ChatWindowActivity' not in text:
            # A chat in its own system window (split screen, free-form, recents).
            text = text.replace('</application>', '    <activity android:name="org.tgas.windows.ChatWindowActivity" android:exported="false"'
                                ' android:documentLaunchMode="intoExisting" android:autoRemoveFromRecents="true"'
                                ' android:resizeableActivity="true" android:theme="@style/AppTheme"'
                                ' android:configChanges="orientation|screenSize|screenLayout|smallestScreenSize|keyboardHidden" />\n    </application>', 1)
        text = re.sub(r'\s*<meta-data android:name="com.google.mlkit.vision.DEPENDENCIES"[^>]*/>', '', text)
        qr = java.parent / 'qr'
        qr.mkdir(exist_ok=True)
        shutil.copyfile(Path(__file__).with_name('android') / 'QrCaptureActivity.java', qr / 'QrCaptureActivity.java')
        if 'org.tgas.qr.QrCaptureActivity' not in text:
            text = text.replace('</application>', '    <activity android:name="org.tgas.qr.QrCaptureActivity"'
                                ' android:exported="false" android:screenOrientation="fullSensor"'
                                ' android:theme="@style/zxing_CaptureTheme" />\n    </application>', 1)
    manifest.write_text(android_backup_rules(text, manifest.parent / 'res'))
    import shutil
    res = build / 'android' / 'gradle' / 'app' / 'src' / 'main' / 'res'
    if not WATCH:
        drawable = res / 'drawable'
        drawable.mkdir(exist_ok=True)
        (drawable / 'ic_telegraph_notification.xml').write_text(android_notification_icon())
    formal_name = 'TeleGraph Watch (Legacy)' if LEGACY_WEAR else 'TeleGraph Watch' if WATCH else 'TeleGraph'
    strings = res / 'values' / 'strings.xml'
    strings.write_text(re.sub(r'(<string name="formal_name">).*?(</string>)',
                              lambda match: match[1] + formal_name + match[2], strings.read_text()))
    icons = ICONS_DIR.parent
    for density, size, splash_size in (
        ('mdpi', 48, 320), ('hdpi', 72, 480), ('xhdpi', 96, 640),
        ('xxhdpi', 144, 960), ('xxxhdpi', 192, 1280),
    ):
        folder = res / f'mipmap-{density}'
        shutil.copyfile(icons / f'tg-ascii-square-{size}.png', folder / 'ic_launcher.png')
        shutil.copyfile(icons / f'tg-ascii-round-{size}.png', folder / 'ic_launcher_round.png')
        shutil.copyfile(icons / f'tg-ascii-adaptive-{size * 9 // 4}.png', folder / 'ic_launcher_foreground.png')
        shutil.copyfile(icons / f'tg-ascii-square-{splash_size}.png', folder / 'splash.png')
    for folder in (ICONS_DIR / 'android').iterdir():
        target = res / folder.name
        target.mkdir(exist_ok=True)
        for icon in folder.glob('*.png'):
            shutil.copyfile(icon, target / icon.name)
    vectors = res / 'mipmap-anydpi-v21'
    vectors.mkdir(exist_ok=True)
    for key, choice in NATIVE_LOGOS.items():
        if key in LEGACY:
            continue
        for rounded in (False, True):
            suffix = '_round' if rounded else ''
            (vectors / f'ic_launcher_{key}{suffix}.xml').write_text(android_vector(choice, rounded))
    if not WATCH:
        local_firebase = Path.home() / '.tg-ascii-lite' / 'firebase-android.json'
        configuration = os.environ.get('TELEGRAPH_FIREBASE_CONFIG') or (local_firebase if local_firebase.is_file() else None)
        android_firebase(build / 'android' / 'gradle', configuration)
    print('android id ->', ANDROID_ID, VERSION, VERSION_CODE)
elif platform == 'ios':
    import plistlib

    # Telegram attaches the APNs provider certificate to a specific API ID.
    # Stage the iPhone identity in Xcode only. The shared sources also feed Android and watchOS.
    import json
    import shutil

    credentials = build / 'ios' / 'xcode' / 'TGASCII' / 'app' / 'tg_ascii' / '_app_credentials.py'
    override = os.environ.get('TELEGRAPH_IOS_API_CONFIG')
    local = Path(override).expanduser() if override else Path.home() / '.tg-ascii-lite' / 'api-ios.json'
    if override or local.is_file():
        settings = json.loads(local.read_text())
        number, secret = int(settings['id']), settings['hash']
        if number <= 0 or not isinstance(secret, str) or not re.fullmatch('[0-9a-fA-F]{32}', secret):
            raise ValueError('Invalid Telegram credentials in the iOS API configuration')
        credentials.chmod(0o600)
        credentials.write_text(f'API_ID = {number}\nAPI_HASH = {secret!r}\n')
    else:
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'src/tg_ascii/_app_credentials.py', credentials)

    for project in (build / 'ios' / 'xcode').glob('*.xcodeproj/project.pbxproj'):
        text = project.read_text()
        entitlements = project.parent.parent / 'TeleGraphPush.entitlements'
        text = re.sub(rf'\n\s*CODE_SIGN_ENTITLEMENTS = {re.escape(entitlements.name)};', '', text)
        # Xcode's own Archive (needed to create the watch app's profiles) signs
        # with the team written in the project, not only the command line's.
        team = os.environ.get('TELEGRAPH_APPLE_TEAM', '')
        if team and not re.fullmatch(r'[A-Z0-9]{10}', team):
            raise ValueError('Invalid Apple development team identifier')
        # Not the Apple Watch app's (org.tgas.ios.watchkitapp, add_watch_target.py).
        text = re.sub(r'PRODUCT_BUNDLE_IDENTIFIER = (?!"?[\w.]+\.watchkitapp"?;)"?[^";]+"?;', f'PRODUCT_BUNDLE_IDENTIFIER = "{IOS_ID}";', text)
        if team:
            text = re.sub(
                rf'(\n(\s*)PRODUCT_BUNDLE_IDENTIFIER = "{re.escape(IOS_ID)}";)(?:\n\2DEVELOPMENT_TEAM = [^;]*;)?(?:\n\2CODE_SIGN_STYLE = Automatic;)?',
                rf'\1\n\2DEVELOPMENT_TEAM = {team};\n\2CODE_SIGN_STYLE = Automatic;', text)
        with entitlements.open('wb') as stream:
            # Xcode selects the final APNs environment from the signing profile.
            plistlib.dump({'aps-environment': 'development',
                           'com.apple.developer.usernotifications.communication': True}, stream)
        text = re.sub(
            rf'(\n(\s*)PRODUCT_BUNDLE_IDENTIFIER = "{re.escape(IOS_ID)}";)(?!\n\s*CODE_SIGN_ENTITLEMENTS)',
            rf'\1\n\2CODE_SIGN_ENTITLEMENTS = {entitlements.name};',
            text,
        )
        # Automatic signing reads capabilities from the native iPhone target.
        if 'com.apple.Push = ' not in text:
            target = re.search(r'^\s*([A-F0-9]+) /\* TG-ASCII \*/ = \{\s*isa = PBXNativeTarget;', text, re.M)
            if target:
                capabilities = (
                    '\n\t\t\t\tTargetAttributes = {'
                    f'\n\t\t\t\t\t{target[1]} = {{'
                    '\n\t\t\t\t\t\tSystemCapabilities = {'
                    '\n\t\t\t\t\t\t\tcom.apple.Push = { enabled = 1; };'
                    '\n\t\t\t\t\t\t};\n\t\t\t\t\t};\n\t\t\t\t};'
                )
                text = text.replace('attributes = {', 'attributes = {' + capabilities, 1)
        names = ' '.join(f'AppIcon-{name}' for name in ALT_ICONS)
        text = re.sub(r'\n\s*ASSETCATALOG_COMPILER_(ALTERNATE_APPICON_NAMES|INCLUDE_ALL_APPICON_ASSETS) = [^;]*;', '', text)
        text = re.sub(r'(\n(\s*)ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;)',
                      lambda m: m.group(1) + f'\n{m.group(2)}ASSETCATALOG_COMPILER_ALTERNATE_APPICON_NAMES = "{names}";'
                                             f'\n{m.group(2)}ASSETCATALOG_COMPILER_INCLUDE_ALL_APPICON_ASSETS = YES;', text)
        launch = project.parent.parent / 'TGASCII' / 'Launch Screen.storyboard'
        if launch.is_file():
            launch.replace(launch.with_name(f'{IOS_LAUNCH_STORYBOARD}.storyboard'))
        text = text.replace('Launch Screen.storyboard', f'{IOS_LAUNCH_STORYBOARD}.storyboard')
        text = ios_phone_privacy(project, text)
        project.write_text(ios_calls_framework(project, text))
    # ITMS-91061: Apple requires a privacy manifest in every framework that
    # contains OpenSSL ("BoringSSL / openssl_grpc"): Python's _ssl and _hashlib.
    # Python-Apple-support's install_dylib installs <module>.xcprivacy found next
    # to the extension as Frameworks/<module>.framework/PrivacyInfo.xcprivacy.
    for dynload in (build / 'ios' / 'xcode' / 'Support').glob('Python.xcframework/*/lib*/python3.*/lib-dynload'):
        for module in ('_ssl', '_hashlib'):
            if any(dynload.glob(f'{module}.*.so')):
                (dynload / f'{module}.xcprivacy').write_text(PRIVACY_MANIFEST)
    import json
    import shutil
    for assets in (build / 'ios' / 'xcode').glob('*/Images.xcassets'):
        # Recreate the launch image set from the current brand. Briefcase
        # can retain the catalog from an earlier project or use other filenames.
        splash = assets / 'Splash.imageset'
        splash.mkdir(exist_ok=True)
        images = []
        for scale, size in enumerate((640, 1280, 1920), start=1):
            filename = f'splash-{size}.png'
            shutil.copyfile(ICONS_DIR.parent / f'tg-ascii-{size}.png', splash / filename)
            images.append({'filename': filename, 'idiom': 'universal', 'scale': f'{scale}x'})
        (splash / 'Contents.json').write_text(json.dumps({
            'images': images, 'info': {'author': 'xcode', 'version': 1}}, indent=2))
        for image in splash.glob('*.png'):
            if image.name not in {entry['filename'] for entry in images}:
                image.unlink()
        for name in ('default', *ALT_ICONS):
            folder = assets / ('AppIcon.appiconset' if name == 'default' else f'AppIcon-{name}.appiconset')
            folder.mkdir(exist_ok=True)
            # The generated catalog has one universal source. Remove legacy
            # size-specific PNGs left by earlier Briefcase layouts.
            for image in folder.glob('icon-*.png'):
                if image.name != 'icon-1024.png' and re.fullmatch(r'icon-\d+\.png', image.name):
                    image.unlink()
            ios_image(folder / 'icon-1024.png', NATIVE_LOGOS[name])
            (folder / 'Contents.json').write_text(json.dumps({
                'images': [{'filename': 'icon-1024.png', 'idiom': 'universal', 'platform': 'ios', 'size': '1024x1024'}],
                'info': {'author': 'xcode', 'version': 1}}, indent=2))
    for info in (build / 'ios' / 'xcode').glob('*/*-Info.plist'):
        with info.open('rb') as stream:
            data = plistlib.load(stream)
        data['CFBundleIdentifier'] = IOS_ID
        data['CFBundleDisplayName'] = 'TeleGraph'
        data['CFBundleShortVersionString'] = VERSION
        data['CFBundleVersion'] = IOS_BUILD
        # Export compliance is answered by the owner in App Store Connect;
        # the Briefcase template would answer it ("no non-exempt encryption").
        data.pop('ITSAppUsesNonExemptEncryption', None)
        # iPad: split view, Stage Manager and resizable windows on a Mac.
        data['UIRequiresFullScreen'] = False
        # Camera and microphone are used only when the person takes a photo
        # or records a video to send (the gallery uses the system picker).
        data['NSCameraUsageDescription'] = 'TeleGraph uses the camera only when you take a photo or video to send.'
        data['NSMicrophoneUsageDescription'] = 'TeleGraph uses the microphone only while you record a voice message or a video to send.'
        data['NSFaceIDUsageDescription'] = 'TeleGraph uses Face ID only to unlock the app when you turn that on.'
        if 'Watch' not in info.name:
            services = data.setdefault('NSApplicationServices', {}).setdefault('Advertises', [])
            if not any(entry.get('NSApplicationServiceIdentifier') == 'telegraph-companion' for entry in services):
                services.append({'NSApplicationServiceIdentifier': 'telegraph-companion'})
            data['UILaunchStoryboardName'] = IOS_LAUNCH_STORYBOARD
            modes = set(data.get('UIBackgroundModes', [])) | {'remote-notification', 'audio', 'voip'}
            if os.environ.get('TELEGRAPH_IOS_CALLS_FRAMEWORK'):
                modes.add('screen-capture')
                data['NSScreenCaptureUsageDescription'] = 'TeleGraph shares your screen in a call when you choose to start sharing.'
                data['NSCameraUsageDescription'] = 'TeleGraph uses the camera for video calls and to take photos or videos you choose to send.'
                data['NSMicrophoneUsageDescription'] = 'TeleGraph uses the microphone for calls and to record voice messages or videos you choose to send.'
            else:
                modes.discard('screen-capture')
                data.pop('NSScreenCaptureUsageDescription', None)
            # iPadOS / Mac: a chat in its own system window (ios_windows.py).
            manifest = data.setdefault('UIApplicationSceneManifest', {})
            manifest['UIApplicationSupportsMultipleScenes'] = True
            manifest.setdefault('UISceneConfigurations', {})
            data['NSUserActivityTypes'] = sorted(set(data.get('NSUserActivityTypes', [])) | {'org.tgas.chat', 'INSendMessageIntent'})
            data['UIBackgroundModes'] = sorted(modes)
        with info.open('wb') as stream:
            plistlib.dump(data, stream)
    # Apple Watch companion (watch/TGASCIIWatch), same version and build.
    import subprocess
    subprocess.run([sys.executable, str(Path(__file__).with_name('add_watch_target.py')), VERSION, IOS_BUILD], check=True)
    phone = build / 'ios' / 'xcode' / 'TGASCII'
    main = phone / 'main.m'
    source = main.read_text()
    for name in ('TeleGraphTVLink.m', 'TGCallAudio.m'):
        shutil.copyfile(Path(__file__).parent / 'ios' / name, phone / name)
        include = f'#import "{name}"'
        if include not in source:
            source = include + '\n' + source
    main.write_text(source)
    from configure_siri import configure_siri
    configure_siri(build / 'ios' / 'xcode')
    from add_notification_target import add_notification_target
    add_notification_target(build / 'ios' / 'xcode', VERSION, IOS_BUILD, IOS_ID)
    print('iOS id ->', IOS_ID, VERSION, IOS_BUILD)

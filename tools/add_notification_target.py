"""Embed the lightweight APNs Notification Service Extension in the iPhone target."""
from pathlib import Path
import plistlib
import re
import shutil

from add_watch_target import IOS_TARGET, add_to_list, add_to_section


def add_notification_target(xcode, version, build, bundle):
    source = Path(__file__).parent / 'ios' / 'TeleGraphNotificationService.m'
    name = 'TeleGraphNotificationService'
    folder = xcode / name
    folder.mkdir(exist_ok=True)
    shutil.copy2(source, folder / source.name)
    presentation = source.with_name('TGNotificationPresentation.m')
    shutil.copy2(presentation, folder / presentation.name)
    group = f'group.{bundle}'
    capabilities = {'com.apple.security.application-groups': [group]}
    phone = xcode / 'TeleGraphPush.entitlements'
    entitlements = plistlib.loads(phone.read_bytes())
    groups = entitlements.setdefault('com.apple.security.application-groups', [])
    if group not in groups:
        groups.append(group)
    phone.write_bytes(plistlib.dumps(entitlements))
    (folder / 'Extension.entitlements').write_bytes(plistlib.dumps(capabilities))
    (folder / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': '$(PRODUCT_BUNDLE_IDENTIFIER)', 'CFBundleName': name,
        'CFBundleDisplayName': 'TeleGraph', 'CFBundleExecutable': '$(EXECUTABLE_NAME)',
        'CFBundlePackageType': 'XPC!', 'CFBundleInfoDictionaryVersion': '6.0',
        'TeleGraphCarPlayEnabled': bool(entitlements.get('com.apple.developer.carplay-communication')),
        'CFBundleShortVersionString': str(version), 'CFBundleVersion': str(build),
        'NSUserActivityTypes': ['INSendMessageIntent'],
        'NSExtension': {'NSExtensionPointIdentifier': 'com.apple.usernotifications.service',
                        'NSExtensionPrincipalClass': name}}))

    project = xcode / 'TG-ASCII.xcodeproj' / 'project.pbxproj'
    prefix = '301A9FCE'
    text = '\n'.join(line for line in project.read_text().split('\n') if prefix not in line)
    root = text.split('rootObject = ', 1)[1].split(' ', 1)[0]
    def uid(number):
        return f'{prefix}{number:016X}'

    def obj(number, section, fields):
        nonlocal text
        line = f'\t\t{uid(number)} /* {name} */ = {{isa = {section}; {fields} }};\n'
        text = add_to_section(text, section, line)

    obj(1, 'PBXFileReference', f'lastKnownFileType = sourcecode.c.objc; path = {name}/{source.name}; sourceTree = SOURCE_ROOT;')
    obj(2, 'PBXFileReference', f'explicitFileType = "wrapper.app-extension"; path = {name}.appex; sourceTree = BUILT_PRODUCTS_DIR;')
    obj(3, 'PBXBuildFile', f'fileRef = {uid(1)};')
    obj(4, 'PBXBuildFile', f'fileRef = {uid(2)}; settings = {{ATTRIBUTES = (RemoveHeadersOnCopy, ); }};')
    obj(5, 'PBXSourcesBuildPhase', f'buildActionMask = 2147483647; files = ({uid(3)}, ); runOnlyForDeploymentPostprocessing = 0;')
    obj(6, 'PBXCopyFilesBuildPhase', f'buildActionMask = 2147483647; dstPath = ""; dstSubfolderSpec = 13; files = ({uid(4)}, ); name = "Embed Notification Service"; runOnlyForDeploymentPostprocessing = 0;')
    obj(7, 'PBXContainerItemProxy', f'containerPortal = {root}; proxyType = 1; remoteGlobalIDString = {uid(12)}; remoteInfo = {name};')
    obj(8, 'PBXTargetDependency', f'target = {uid(12)}; targetProxy = {uid(7)};')
    team = re.search(r'DEVELOPMENT_TEAM = ([A-Z0-9]+);', text)
    team_id = team[1] if team else ''
    settings = (f'PRODUCT_NAME = {name}; PRODUCT_BUNDLE_IDENTIFIER = {bundle}.notificationservice; '
                f'INFOPLIST_FILE = {name}/Info.plist; CODE_SIGN_ENTITLEMENTS = {name}/Extension.entitlements; '
                f'DEVELOPMENT_TEAM = "{team_id}"; ')
    settings += ('SDKROOT = iphoneos; SUPPORTED_PLATFORMS = "iphoneos iphonesimulator"; '
                 'TARGETED_DEVICE_FAMILY = "1,2"; IPHONEOS_DEPLOYMENT_TARGET = 15.0; '
                 'SKIP_INSTALL = YES; APPLICATION_EXTENSION_API_ONLY = YES; CLANG_ENABLE_OBJC_ARC = YES; '
                 'CODE_SIGN_STYLE = Automatic; OTHER_LDFLAGS = ("-framework", UserNotifications, "-framework", Intents, "-framework", UIKit, "-framework", ImageIO, );')
    for number, config in ((9, 'Debug'), (10, 'Release')):
        obj(number, 'XCBuildConfiguration', f'buildSettings = {{{settings}}}; name = {config};')
    obj(11, 'XCConfigurationList', f'buildConfigurations = ({uid(9)}, {uid(10)}, ); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;')
    obj(12, 'PBXNativeTarget', f'buildConfigurationList = {uid(11)}; buildPhases = ({uid(5)}, ); buildRules = (); dependencies = (); name = {name}; productName = {name}; productReference = {uid(2)}; productType = "com.apple.product-type.app-extension";')
    for owner, key, item in ((root, 'targets', 12), (IOS_TARGET, 'dependencies', 8), (IOS_TARGET, 'buildPhases', 6)):
        text = add_to_list(text, owner, key, uid(item))
    project.write_text(text)

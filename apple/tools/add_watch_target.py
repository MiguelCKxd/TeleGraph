"""Add the Apple Watch app (watch/TGASCIIWatch, SwiftUI) to the Xcode project
Briefcase generates, embedded in the iOS app (TG-ASCII.app/Watch), so it is the
iOS app's companion (org.tgas.ios.watchkitapp) on TestFlight.

Two ways to get chats, both in the watch app:
- linked (default): the iPhone app answers over WatchConnectivity;
- own connection (complex feature): Python + Telethon inside the watch
  (BeeWare's Python-Apple-support for watchOS, watch/python/tgwatch), with a
  session approved by the iPhone app; works with the iPhone off.

Run by tools/patch_ids.py for iOS on every build: it removes what it added
before (ids starting with 7A7C4A5C) and adds it again, so it stays current.
"""
from pathlib import Path
import json
import plistlib
import re
import os
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'watch' / 'TGASCIIWatch'
PYTHON_SOURCE = ROOT / 'watch' / 'python'
DEFAULT_SUPPORT = ROOT.parent / 'watch-python' / 'support' / 'Python.xcframework'
SUPPORT = Path(os.environ.get('TELEGRAPH_WATCH_PYTHON_FRAMEWORK', DEFAULT_SUPPORT)).expanduser()
XCODE = ROOT / 'build' / 'tg_ascii_mobile' / 'ios' / 'xcode'
PROJECT = XCODE / 'TG-ASCII.xcodeproj' / 'project.pbxproj'
IOS_TARGET = '60796EE119190F4100A9926B'
MARK = 'TGASCIIWatch'
SWIFT = ('TGASCIIWatchApp.swift', 'Phone.swift', 'Views.swift', 'Engine.swift', 'SettingsView.swift', 'LogoView.swift', 'LogoVariants.swift')
C_FILES = ('PythonBridge.c',)
# Pure-Python packages the watch's own connection needs (from the iOS app's).
PACKAGES = ('telethon', 'pyaes', 'rsa', 'pyasn1', 'rubicon', 'qrcode')
PREFIX = '7A7C4A5C'
# The watch's own connection (Python inside the watch) is only built on request.
PYTHON = os.environ.get('WATCH_PYTHON') == '1'


def ident(n):
    return f'{PREFIX}{n:016X}'


def add_to_section(text, section, entries):
    end = f'/* End {section} section */'
    if end not in text:
        block = f'/* Begin {section} section */\n/* End {section} section */\n\n'
        text = text.replace('/* Begin PBXFileReference section */', block + '/* Begin PBXFileReference section */', 1)
    return text.replace(end, entries + end, 1)


def add_to_list(text, owner, key, item):
    """Append `item` at the end of the `key = ( ... );` list of object `owner`."""
    start = text.index(f'\n\t\t{owner} ')
    begin = text.index(f'{key} = (', start)
    at = text.index('\n\t\t\t);', begin)
    return text[:at] + f'\n\t\t\t\t{item},' + text[at:]


def remove_previous(text):
    text = re.sub(rf'\n\t\t{PREFIX}[0-9A-F]{{16}} /\*[^*]*\*/ = \{{\n.*?\n\t\t\}};', '', text, flags=re.S)
    text = re.sub(rf'\n\t\t{PREFIX}[0-9A-F]{{16}} /\*.*?\*/ = \{{[^\n]*\}};', '', text)
    text = re.sub(rf'\n\t+{PREFIX}[0-9A-F]{{16}}(?: /\*[^*]*\*/)?,', '', text)
    return text


def copy_python():
    """Python framework, our module, credentials and packages for the watch."""
    support = XCODE / 'WatchSupport'
    framework = support / 'Python.xcframework'
    plist = (SUPPORT / 'Info.plist').read_bytes()
    device_slice = next(
        library for library in plistlib.loads(plist)['AvailableLibraries']
        if library['SupportedPlatform'] == 'watchos' and 'SupportedPlatformVariant' not in library
    )
    device_architectures = device_slice['SupportedArchitectures']
    if (not framework.exists() or (framework / 'Info.plist').read_bytes() != plist
            or SUPPORT != DEFAULT_SUPPORT):
        support.mkdir(exist_ok=True)
        if framework.exists():
            shutil.rmtree(framework)
        shutil.copytree(SUPPORT, framework, symlinks=True)
    alias = framework / 'watchos-arm64'
    if device_architectures == ['arm64_32'] and not alias.exists():
        # BeeWare's helper looks for watchos-arm64 in older releases.
        alias.symlink_to(device_slice['LibraryIdentifier'])
    target = XCODE / 'WatchPython'
    if target.exists():
        shutil.rmtree(target)
    ignore_bytecode = shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo')
    shutil.copytree(PYTHON_SOURCE, target / 'app', ignore=ignore_bytecode)
    for module in ('message_translation.py', 'pin_order.py'):
        shutil.copy2(ROOT / 'src' / 'tg_ascii' / module, target / 'app' / 'tgwatch' / module)
    # patch_ids.py has already selected the Apple client's identity for this build.
    iphone_app = XCODE / 'TGASCII' / 'app'
    shutil.copy2(iphone_app / 'tg_ascii' / '_app_credentials.py', target / 'app' / '_app_credentials.py')
    packages = XCODE / 'TGASCII' / 'app_packages.iphoneos'
    for name in PACKAGES:
        shutil.copytree(packages / name, target / 'app_packages' / name, ignore=ignore_bytecode)
    # Package metadata too: rubicon reads its own version at import.
    for info in packages.glob('*.dist-info'):
        if info.name.split('-')[0].lower().replace('_', '') in {name.lower().replace('_', '') for name in PACKAGES} | {'rubiconobjc'}:
            shutil.copytree(info, target / 'app_packages' / info.name)

    return device_architectures


def copy_logos(target):
    sys.path.insert(0, str(ROOT / 'src'))
    from tg_ascii.logos import LOGO_PALETTES, VARIANTS, mobile_wordmark

    variants = []
    for key, label in VARIANTS.items():
        ink = ' '.join(str(n) for rect in mobile_wordmark(key) for n in rect)
        variants.append(f'        (id: {json.dumps(key)}, title: {json.dumps(label)}, ink: {json.dumps(ink)})')
    palettes = []
    for color, themes in LOGO_PALETTES.items():
        for theme, (background, foreground) in themes.items():
            background = '#%02x%02x%02x' % background
            foreground = '#%02x%02x%02x' % foreground
            palettes.append(f'        "{color}-{theme}": (background: "{background}", foreground: "{foreground}")')
    entries = ',\n'.join(variants)
    colors = ',\n'.join(palettes)
    (target / 'LogoVariants.swift').write_text(
        f'enum LogoVariants {{\n    static let options = [\n{entries}\n    ]\n'
        f'    static let palettes = [\n{colors}\n    ]\n}}\n')


def main(version, build, team=os.environ.get('TELEGRAPH_APPLE_TEAM', ''), bundle='org.tgas.ios'):
    target = XCODE / MARK
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SOURCE, target)
    copy_logos(target)
    device_architectures = copy_python() if PYTHON else ['arm64_32', 'arm64']
    device_archs = " ".join(device_architectures)
    text = remove_previous(PROJECT.read_text())
    sources = SWIFT + C_FILES
    ids = {name: ident(i) for i, name in enumerate(
        ['group', 'product', 'assets', 'target', 'sources', 'resources', 'frameworks', 'debug', 'release', 'configs',
         'proxy', 'dependency', 'embed_phase', 'embed_file', 'assets_build', 'python_ref', 'python_link', 'python_embed',
         'python_embed_phase', 'python_script', 'header', 'privacy', 'privacy_build']
        + [f'file:{name}' for name in sources] + [f'build:{name}' for name in sources])}
    kind = lambda name: 'sourcecode.swift' if name.endswith('.swift') else 'sourcecode.c.c'
    files = ''.join(f'\t\t{ids["file:" + name]} /* {name} */ = {{isa = PBXFileReference; lastKnownFileType = {kind(name)}; path = {name}; sourceTree = "<group>"; }};\n'
                    for name in sources)
    files += (f'\t\t{ids["header"]} /* PythonBridge.h */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.c.h; path = PythonBridge.h; sourceTree = "<group>"; }};\n'
              f'\t\t{ids["privacy"]} /* PrivacyInfo.xcprivacy */ = {{isa = PBXFileReference; lastKnownFileType = text.xml; path = PrivacyInfo.xcprivacy; sourceTree = "<group>"; }};\n'
              f'\t\t{ids["assets"]} /* Assets.xcassets */ = {{isa = PBXFileReference; lastKnownFileType = folder.assetcatalog; path = Assets.xcassets; sourceTree = "<group>"; }};\n'
              f'\t\t{ids["product"]} /* TGASCIIWatch.app */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = TGASCIIWatch.app; sourceTree = BUILT_PRODUCTS_DIR; }};\n'
              f'\t\t{ids["python_ref"]} /* Python.xcframework */ = {{isa = PBXFileReference; lastKnownFileType = wrapper.xcframework; path = WatchSupport/Python.xcframework; sourceTree = "<group>"; }};\n')
    text = add_to_section(text, 'PBXFileReference', files)
    builds = ''.join(f'\t\t{ids["build:" + name]} /* {name} in Sources */ = {{isa = PBXBuildFile; fileRef = {ids["file:" + name]} /* {name} */; }};\n'
                     for name in sources)
    builds += (f'\t\t{ids["assets_build"]} /* Assets.xcassets in Resources */ = {{isa = PBXBuildFile; fileRef = {ids["assets"]} /* Assets.xcassets */; }};\n'
               f'\t\t{ids["privacy_build"]} /* PrivacyInfo.xcprivacy in Resources */ = {{isa = PBXBuildFile; fileRef = {ids["privacy"]} /* PrivacyInfo.xcprivacy */; }};\n'
               f'\t\t{ids["embed_file"]} /* TGASCIIWatch.app in Embed Watch Content */ = {{isa = PBXBuildFile; fileRef = {ids["product"]} /* TGASCIIWatch.app */; settings = {{ATTRIBUTES = (RemoveHeadersOnCopy, ); }}; }};\n'
               f'\t\t{ids["python_link"]} /* Python.xcframework in Frameworks */ = {{isa = PBXBuildFile; fileRef = {ids["python_ref"]} /* Python.xcframework */; }};\n'
               f'\t\t{ids["python_embed"]} /* Python.xcframework in Embed Frameworks */ = {{isa = PBXBuildFile; fileRef = {ids["python_ref"]} /* Python.xcframework */; settings = {{ATTRIBUTES = (CodeSignOnCopy, RemoveHeadersOnCopy, ); }}; }};\n')
    text = add_to_section(text, 'PBXBuildFile', builds)
    children = ''.join(f'\t\t\t\t{ids["file:" + name]} /* {name} */,\n' for name in sources)
    children += f'\t\t\t\t{ids["header"]} /* PythonBridge.h */,\n\t\t\t\t{ids["privacy"]} /* PrivacyInfo.xcprivacy */,\n\t\t\t\t{ids["assets"]} /* Assets.xcassets */,\n'
    text = add_to_section(text, 'PBXGroup', f'\t\t{ids["group"]} /* {MARK} */ = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n{children}\t\t\t);\n\t\t\tpath = {MARK};\n\t\t\tsourceTree = "<group>";\n\t\t}};\n')
    main_group = text.split('mainGroup = ', 1)[1].split(';', 1)[0].strip()
    products = text.split('productRefGroup = ', 1)[1].split(' ', 1)[0].strip()
    text = add_to_list(text, main_group, 'children', f'{ids["group"]} /* {MARK} */')
    text = add_to_list(text, main_group, 'children', f'{ids["python_ref"]} /* Python.xcframework */')
    text = add_to_list(text, products, 'children', f'{ids["product"]} /* TGASCIIWatch.app */')
    phase = lambda key, isa, name, entries: (
        f'\t\t{ids[key]} /* {name} */ = {{\n\t\t\tisa = {isa};\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = (\n{entries}\t\t\t);\n'
        f'\t\t\trunOnlyForDeploymentPostprocessing = 0;\n\t\t}};\n')
    text = add_to_section(text, 'PBXSourcesBuildPhase', phase('sources', 'PBXSourcesBuildPhase', 'Sources',
                          ''.join(f'\t\t\t\t{ids["build:" + name]} /* {name} in Sources */,\n' for name in sources)))
    text = add_to_section(text, 'PBXResourcesBuildPhase', phase('resources', 'PBXResourcesBuildPhase', 'Resources',
                          f'\t\t\t\t{ids["assets_build"]} /* Assets.xcassets in Resources */,\n\t\t\t\t{ids["privacy_build"]} /* PrivacyInfo.xcprivacy in Resources */,\n'))
    text = add_to_section(text, 'PBXFrameworksBuildPhase', phase('frameworks', 'PBXFrameworksBuildPhase', 'Frameworks',
                          f'\t\t\t\t{ids["python_link"]} /* Python.xcframework in Frameworks */,\n' if PYTHON else ''))
    copy_phase = lambda key, name, path, spec, entry: (
        f'\t\t{ids[key]} /* {name} */ = {{\n\t\t\tisa = PBXCopyFilesBuildPhase;\n\t\t\tbuildActionMask = 2147483647;\n'
        f'\t\t\tdstPath = "{path}";\n\t\t\tdstSubfolderSpec = {spec};\n\t\t\tfiles = (\n' + (f'\t\t\t\t{entry},\n' if entry else '') + '\t\t\t);\n'
        f'\t\t\tname = "{name}";\n\t\t\trunOnlyForDeploymentPostprocessing = 0;\n\t\t}};\n')
    text = add_to_section(text, 'PBXCopyFilesBuildPhase',
                          copy_phase('embed_phase', 'Embed Watch Content', '$(CONTENTS_FOLDER_PATH)/Watch', 16,
                                     f'{ids["embed_file"]} /* TGASCIIWatch.app in Embed Watch Content */')
                          + copy_phase('python_embed_phase', 'Embed Frameworks', '', 10,
                                       f'{ids["python_embed"]} /* Python.xcframework in Embed Frameworks */' if PYTHON else ''))
    # WATCH_PYTHON=1 enables the same runtime for testing and archives.
    # Keep Python sources free of bytecode generated on the build host.
    script = 'echo \\"Watch Python not embedded (WATCH_PYTHON=1 to embed)\\"\\n' if not PYTHON else ('set -e\\n'
              'rsync -a --delete \\"$PROJECT_DIR/WatchPython/app/\\" \\"$CODESIGNING_FOLDER_PATH/app\\"\\n'
              'rsync -a --delete \\"$PROJECT_DIR/WatchPython/app_packages/\\" \\"$CODESIGNING_FOLDER_PATH/app_packages\\"\\n'
              '/bin/bash \\"$PROJECT_DIR/TGASCIIWatch/package_python.sh\\"\\n')

    text = add_to_section(text, 'PBXShellScriptBuildPhase',
                          f'\t\t{ids["python_script"]} /* Process Python libraries */ = {{\n\t\t\tisa = PBXShellScriptBuildPhase;\n'
                          f'\t\t\talwaysOutOfDate = 1;\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = (\n\t\t\t);\n'
                          f'\t\t\tinputFileListPaths = (\n\t\t\t);\n\t\t\tinputPaths = (\n\t\t\t);\n\t\t\tname = "Process Python libraries";\n'
                          f'\t\t\toutputFileListPaths = (\n\t\t\t);\n\t\t\toutputPaths = (\n\t\t\t);\n\t\t\trunOnlyForDeploymentPostprocessing = 0;\n'
                          f'\t\t\tshellPath = /bin/sh;\n\t\t\tshellScript = "{script}";\n\t\t\tshowEnvVarsInLog = 0;\n\t\t}};\n')
    project = text.split('rootObject = ', 1)[1].split(' ', 1)[0].strip()
    text = add_to_section(text, 'PBXContainerItemProxy',
                          f'\t\t{ids["proxy"]} /* PBXContainerItemProxy */ = {{\n\t\t\tisa = PBXContainerItemProxy;\n\t\t\tcontainerPortal = {project};\n'
                          f'\t\t\tproxyType = 1;\n\t\t\tremoteGlobalIDString = {ids["target"]};\n\t\t\tremoteInfo = {MARK};\n\t\t}};\n')
    text = add_to_section(text, 'PBXTargetDependency',
                          f'\t\t{ids["dependency"]} /* PBXTargetDependency */ = {{\n\t\t\tisa = PBXTargetDependency;\n\t\t\ttarget = {ids["target"]} /* {MARK} */;\n'
                          f'\t\t\ttargetProxy = {ids["proxy"]} /* PBXContainerItemProxy */;\n\t\t}};\n')
    text = add_to_section(text, 'PBXNativeTarget',
                          f'\t\t{ids["target"]} /* {MARK} */ = {{\n\t\t\tisa = PBXNativeTarget;\n\t\t\tbuildConfigurationList = {ids["configs"]};\n'
                          f'\t\t\tbuildPhases = (\n\t\t\t\t{ids["sources"]} /* Sources */,\n\t\t\t\t{ids["frameworks"]} /* Frameworks */,\n'
                          f'\t\t\t\t{ids["resources"]} /* Resources */,\n\t\t\t\t{ids["python_script"]} /* Process Python libraries */,\n'
                          f'\t\t\t\t{ids["python_embed_phase"]} /* Embed Frameworks */,\n\t\t\t);\n\t\t\tbuildRules = (\n\t\t\t);\n\t\t\tdependencies = (\n\t\t\t);\n'
                          f'\t\t\tname = {MARK};\n\t\t\tproductName = {MARK};\n\t\t\tproductReference = {ids["product"]} /* TGASCIIWatch.app */;\n'
                          f'\t\t\tproductType = "com.apple.product-type.application";\n\t\t}};\n')
    settings = lambda optimize: (
        '\t\t\tbuildSettings = { /* watch */\n'
        '\t\t\t\tARCHS = "$(ARCHS_WATCH_$(PLATFORM_NAME))";\n'
        + f'\t\t\t\tARCHS_WATCH_watchos = "{device_archs}";\n'
        + ('\t\t\t\tGCC_PREPROCESSOR_DEFINITIONS = ("TGW_PYTHON=1", "$(inherited)");\n' if PYTHON else '')
        +
        '\t\t\t\tARCHS_WATCH_watchsimulator = arm64;\n'
        '\t\t\t\tASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;\n'
        '\t\t\t\tCODE_SIGN_STYLE = Automatic;\n'
        f'\t\t\t\tCURRENT_PROJECT_VERSION = {build};\n'
        f'\t\t\t\tDEVELOPMENT_TEAM = {team};\n'
        '\t\t\t\tENABLE_PREVIEWS = NO;\n'
        '\t\t\t\tENABLE_USER_SCRIPT_SANDBOXING = NO;\n'
        '\t\t\t\tFRAMEWORK_SEARCH_PATHS = "\\"$(PROJECT_DIR)/WatchSupport\\"";\n'
        '\t\t\t\tGENERATE_INFOPLIST_FILE = YES;\n'
        '\t\t\t\tHEADER_SEARCH_PATHS = "\\"$(BUILT_PRODUCTS_DIR)/Python.framework/Headers\\"";\n'
        '\t\t\t\tINFOPLIST_KEY_CFBundleDisplayName = "TeleGraph";\n'
        '\t\t\t\tINFOPLIST_KEY_UISupportedInterfaceOrientations = "UIInterfaceOrientationPortrait UIInterfaceOrientationPortraitUpsideDown";\n'
        f'\t\t\t\tINFOPLIST_KEY_WKCompanionAppBundleIdentifier = {bundle};\n'
        f'\t\t\t\tINFOPLIST_KEY_WKRunsIndependentlyOfCompanionApp = {"YES" if PYTHON else "NO"};\n'
        '\t\t\t\tLD_RUNPATH_SEARCH_PATHS = ("$(inherited)", "@executable_path/Frameworks");\n'
        f'\t\t\t\tMARKETING_VERSION = {version};\n'
        f'\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = {bundle}.watchkitapp;\n'
        '\t\t\t\tPRODUCT_NAME = TGASCIIWatch;\n'
        '\t\t\t\tSDKROOT = watchos;\n'
        '\t\t\t\tSKIP_INSTALL = YES;\n'
        '\t\t\t\tSUPPORTED_PLATFORMS = "watchos watchsimulator";\n'
        '\t\t\t\tSWIFT_EMIT_LOC_STRINGS = YES;\n'
        f'\t\t\t\tSWIFT_OBJC_BRIDGING_HEADER = "{MARK}/PythonBridge.h";\n'
        f'\t\t\t\tSWIFT_OPTIMIZATION_LEVEL = "{optimize}";\n'
        '\t\t\t\tSWIFT_VERSION = 5.0;\n'
        '\t\t\t\tTARGETED_DEVICE_FAMILY = 4;\n'
        '\t\t\t\tWATCHOS_DEPLOYMENT_TARGET = 10.0;\n'
        '\t\t\t};\n')
    text = add_to_section(text, 'XCBuildConfiguration',
                          f'\t\t{ids["debug"]} /* Debug */ = {{\n\t\t\tisa = XCBuildConfiguration;\n{settings("-Onone")}\t\t\tname = Debug;\n\t\t}};\n'
                          f'\t\t{ids["release"]} /* Release */ = {{\n\t\t\tisa = XCBuildConfiguration;\n{settings("-O")}\t\t\tname = Release;\n\t\t}};\n')
    text = add_to_section(text, 'XCConfigurationList',
                          f'\t\t{ids["configs"]} /* Build configuration list for PBXNativeTarget "{MARK}" */ = {{\n\t\t\tisa = XCConfigurationList;\n'
                          f'\t\t\tbuildConfigurations = (\n\t\t\t\t{ids["debug"]} /* Debug */,\n\t\t\t\t{ids["release"]} /* Release */,\n\t\t\t);\n'
                          f'\t\t\tdefaultConfigurationIsVisible = 0;\n\t\t\tdefaultConfigurationName = Release;\n\t\t}};\n')
    text = add_to_list(text, project, 'targets', f'{ids["target"]} /* {MARK} */')
    text = add_to_list(text, IOS_TARGET, 'dependencies', f'{ids["dependency"]} /* PBXTargetDependency */')
    text = add_to_list(text, IOS_TARGET, 'buildPhases', f'{ids["embed_phase"]} /* Embed Watch Content */')
    PROJECT.write_text(text)


if __name__ == '__main__':
    main(*sys.argv[1:3])

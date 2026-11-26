"""Add native SwiftUI controls to the generated phone target, idempotently."""
from pathlib import Path
import re
import shutil

from add_watch_target import IOS_TARGET, add_to_list, add_to_section


def configure_glass(xcode):
    source = Path(__file__).parent / 'ios' / 'TGNativeGlass.swift'
    shutil.copyfile(source, xcode / 'TGASCII' / source.name)
    project = xcode / 'TG-ASCII.xcodeproj' / 'project.pbxproj'
    prefix = '34A61A55'
    text = '\n'.join(line for line in project.read_text().split('\n') if prefix not in line)

    def uid(number):
        return f'{prefix}{number:016X}'

    for section, number, fields in (
        ('PBXFileReference', 1, 'lastKnownFileType = sourcecode.swift; path = TGASCII/TGNativeGlass.swift; sourceTree = SOURCE_ROOT;'),
        ('PBXBuildFile', 2, f'fileRef = {uid(1)};'),
    ):
        text = add_to_section(text, section, f'\t\t{uid(number)} /* Native Glass */ = {{isa = {section}; {fields} }};\n')
    target = re.search(rf'\n\t\t{IOS_TARGET} /\*.*?\*/ = \{{(.*?)\n\t\t\}};', text, re.S)
    if not target:
        raise ValueError('Missing phone target')
    # One target must have exactly one Sources phase. A second phase makes
    # Xcode schedule duplicate Swift compilation and link tasks for the app.
    phases = re.search(r'buildPhases = \((.*?)\);', target[1], re.S)
    sources = []
    for phase in re.findall(r'[A-F0-9]{24}', phases[1] if phases else ''):
        block = re.search(rf'\n\t\t{phase} /\*.*?\*/ = \{{(.*?)\n\t\t\}};', text, re.S)
        if block and re.search(r'isa = PBXSourcesBuildPhase;', block[1]):
            sources.append(phase)
    if len(sources) != 1:
        raise ValueError('Phone target must have one Sources phase')
    text = add_to_list(text, sources[0], 'files', uid(2))
    config_list = re.search(r'buildConfigurationList = ([A-F0-9]{24})', target[1])[1]
    configs = re.search(rf'\n\t\t{config_list} /\*.*?\*/ = \{{(.*?)\n\t\t\}};', text, re.S)
    if not configs:
        raise ValueError('Missing phone build configurations')
    for config in re.findall(r'([A-F0-9]{24}) /\*', configs[1]):
        pattern = rf'(\n\t\t{config} /\*.*?\*/ = \{{)(.*?)(\n\t\t\}};)'

        def swift_settings(match):
            body = re.sub(r'\n\s*(?:SWIFT_VERSION|ALWAYS_EMBED_SWIFT_STANDARD_LIBRARIES) = [^;]+;', '', match[2])
            body = body.replace('buildSettings = {', 'buildSettings = {\n\t\t\t\tSWIFT_VERSION = 5.0;\n\t\t\t\tALWAYS_EMBED_SWIFT_STANDARD_LIBRARIES = YES;', 1)
            return match[1] + body + match[3]

        text, count = re.subn(pattern, swift_settings, text, count=1, flags=re.S)
        if count != 1:
            raise ValueError(f'Missing phone configuration {config}')
    project.write_text(text)

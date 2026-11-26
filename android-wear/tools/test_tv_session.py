#!/usr/bin/env python3
"""Exercise the real TV controller in a disposable simulator, without accounts."""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import time


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    runtime = next(row['identifier'] for row in json.loads(run('xcrun', 'simctl', 'list', 'runtimes', '-j'))['runtimes']
                   if row['isAvailable'] and row['name'].startswith('tvOS'))
    kind = next(row['identifier'] for row in json.loads(run('xcrun', 'simctl', 'list', 'devicetypes', '-j'))['devicetypes']
                if row['name'].startswith('Apple TV') and '1080p' in row['name'])
    device = run('xcrun', 'simctl', 'create', 'TeleGraph-TV-session-QA', kind, runtime)
    try:
        with tempfile.TemporaryDirectory(prefix='telegraph-tv-qa-') as directory:
            work = Path(directory)
            source = (root / 'tv/Television.swift').read_text()
            entrypoint = '@main final class TVApp: UIResponder, UIApplicationDelegate {}'
            assert source.count(entrypoint) == 1
            (work / 'TVSessionQA.swift').write_text(source.replace(entrypoint, '') + '\n' +
                                                   (root / 'tests/tv_session.swift').read_text())
            app = work / 'TeleGraphTVQA.app'
            app.mkdir()
            (app / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'org.tgas.tvqa34', 'CFBundleExecutable': 'TeleGraphTVQA',
                'CFBundleName': 'TeleGraphTVQA', 'CFBundleVersion': '1',
                'CFBundleShortVersionString': '3.4.0', 'CFBundlePackageType': 'APPL',
                'UIDeviceFamily': [3], 'MinimumOSVersion': '16.0',
                'UIApplicationSceneManifest': {'UIApplicationSupportsMultipleScenes': False,
                    'UISceneConfigurations': {'UIWindowSceneSessionRoleApplication': [{
                        'UISceneConfigurationName': 'QA', 'UISceneDelegateClassName': 'TVSessionQA.TVSessionQAScene'}]}}
            }))
            sdk = run('xcrun', '--sdk', 'appletvsimulator', '--show-sdk-path')
            run('xcrun', '--sdk', 'appletvsimulator', 'swiftc', '-parse-as-library', '-module-name', 'TVSessionQA',
                '-target', 'arm64-apple-tvos16.0-simulator', '-sdk', sdk,
                str(work / 'TVSessionQA.swift'), '-o', str(app / 'TeleGraphTVQA'))
            run('xcrun', 'simctl', 'boot', device)
            run('xcrun', 'simctl', 'bootstatus', device, '-b')
            run('xcrun', 'simctl', 'install', device, str(app))
            run('xcrun', 'simctl', 'launch', device, 'org.tgas.tvqa34')
            container = Path(run('xcrun', 'simctl', 'get_app_container', device, 'org.tgas.tvqa34', 'data'))
            result = container / 'Documents/tv-session-result.json'
            deadline = time.monotonic() + 30
            while not result.exists() and time.monotonic() < deadline:
                time.sleep(.1)
            data = json.loads(result.read_text())
            assert data['passed'] == 10
            args.output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(result, args.output)
            print(json.dumps(data))
    finally:
        subprocess.run(['xcrun', 'simctl', 'shutdown', device], capture_output=True)
        subprocess.run(['xcrun', 'simctl', 'delete', device], check=True)


if __name__ == '__main__':
    main()

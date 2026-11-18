"""1.5.5: Linux support (notifications, tray, typelibs, .deb package)."""
import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile


class FakeProcess:
    def __init__(self, lines, code=0):
        self.stdout = io.StringIO(''.join(line + '\n' for line in lines))
        self.stderr = io.StringIO('')
        self.code = code
        self.terminated = False

    def wait(self):
        return self.code

    def terminate(self):
        self.terminated = True


class LinuxNotificationTests(unittest.TestCase):
    def center(self):
        from tg_ascii.notifications import LinuxCenter
        with patch('shutil.which', side_effect=lambda name: f'/usr/bin/{name}'):
            return LinuxCenter()

    def run_show(self, center, lines, **kwargs):
        calls = []
        process = FakeProcess(lines)
        threads = []
        def start_thread(target, **_):
            threads.append(target)
            return SimpleNamespace(start=lambda: target())
        with patch('subprocess.Popen', side_effect=lambda command, **_: calls.append(command) or process), \
                patch('threading.Thread', side_effect=start_thread):
            center.show('Ana', 'Hola', 'key1', kwargs.pop('report', Mock()), **kwargs)
        return calls, process

    def test_click_opens_the_chat_and_ids_are_reused(self):
        center = self.center()
        opened = Mock()
        calls, _ = self.run_show(center, ['42', 'default'], activate=opened, sound=True)
        command = calls[0]
        self.assertEqual(command[0], '/usr/bin/notify-send')
        self.assertIn('--app-name=TeleGraph', command)
        self.assertIn('--hint=string:sound-name:message-new-instant', command)
        self.assertTrue(any(part.startswith('--action=default=') for part in command))
        self.assertEqual(command[-3:], ['--', 'Ana', 'Hola'])
        opened.assert_called_once()
        calls, _ = self.run_show(center, ['42'])
        self.assertIn('--replace-id=42', calls[0])

    def test_locking_closes_shown_notifications_and_ignores_clicks(self):
        center = self.center()
        self.run_show(center, ['7'])
        with patch('subprocess.run') as run:
            center.set_locked(True)
        self.assertIn('7', run.call_args.args[0])
        opened = Mock()
        self.run_show(center, ['8', 'default'], activate=opened)
        opened.assert_not_called()

    def test_without_libnotify_the_app_keeps_working(self):
        from tg_ascii.notifications import LinuxCenter
        with patch('shutil.which', return_value=None):
            with self.assertRaises(RuntimeError):
                LinuxCenter()

    def test_center_picks_linux(self):
        from tg_ascii.notifications import NotificationCenter
        center = NotificationCenter(Mock())
        with patch.object(sys, 'platform', 'linux'), patch('tg_ascii.notifications.LinuxCenter') as linux:
            center._create_adapter()
        linux.assert_called_once()


class LinuxTrayTests(unittest.TestCase):
    def icon(self, backend):
        return type('Icon', (), {'__module__': f'pystray.{backend}'})()

    def test_only_a_visible_tray_counts(self):
        from tg_ascii.background import visible_backend
        with patch.object(sys, 'platform', 'linux'):
            icon = self.icon('_appindicator')
            icon._appindicator = Mock()
            for connected in (False, True):
                icon._appindicator.get_property.return_value = connected
                self.assertEqual(visible_backend(icon), connected)
            icon._appindicator.get_property.assert_called_with('connected')
            icon = self.icon('_gtk')
            icon._status_icon = Mock()
            for embedded in (False, True):
                icon._status_icon.is_embedded.return_value = embedded
                self.assertEqual(visible_backend(icon), embedded)
            with patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-0'}):
                self.assertFalse(visible_backend(self.icon('_xorg')))
            with patch.dict(os.environ, {}, clear=True):
                self.assertTrue(visible_backend(self.icon('_xorg')))
        with patch.object(sys, 'platform', 'darwin'):
            self.assertTrue(visible_backend(self.icon('_darwin')))


class LinuxRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux distribution engine')
    def test_packaged_call_engine_version_is_enabled(self):
        from tg_ascii import calls_native
        with patch.object(calls_native.importlib.util, 'find_spec', return_value=object()), \
                patch.object(calls_native.importlib.metadata, 'version', return_value='3.0.7'):
            self.assertTrue(calls_native.engine_available.__wrapped__())

    def test_system_typelibs_are_appended(self):
        from tg_ascii import linux_runtime
        with tempfile.TemporaryDirectory() as folder, patch.object(sys, 'platform', 'linux'), \
                patch.object(linux_runtime, 'SYSTEM_TYPELIBS', (folder,)), \
                patch.dict(os.environ, {'GI_TYPELIB_PATH': '/bundle/gi_typelibs'}):
            linux_runtime.prepare()
            self.assertEqual(os.environ['GI_TYPELIB_PATH'].split(os.pathsep), ['/bundle/gi_typelibs', folder])

    def test_nothing_changes_elsewhere(self):
        from tg_ascii import linux_runtime
        with patch.object(sys, 'platform', 'darwin'), patch.dict(os.environ, {}, clear=True):
            linux_runtime.prepare()
            self.assertNotIn('GI_TYPELIB_PATH', os.environ)


class LinuxLauncherTests(unittest.TestCase):
    def test_pinned_id_updates_in_place_and_preserves_unrelated_launchers(self):
        from tg_ascii.linux_runtime import DESKTOP_ENTRY, DESKTOP_ID, ICON_NAME, sync_launcher_icon
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'XDG_DATA_HOME': folder}), \
                patch('tg_ascii.linux_runtime.SYSTEM_DESKTOP', Path(folder) / 'system.desktop'), \
                patch.object(sys, 'executable', '/opt/tg-ascii/TG-ASCII'), patch.object(sys, 'frozen', True, create=True):
            base = Path(folder)
            first, second = base / 'first.png', base / 'second.png'
            first.write_bytes(b'first')
            second.write_bytes(b'second')
            launcher = base / 'applications' / DESKTOP_ID
            sync_launcher_icon(first)
            original = launcher.read_bytes()
            sync_launcher_icon(second)
            updated = launcher.read_text(encoding='utf-8')
            self.assertIn('Name=TeleGraph', updated)
            self.assertIn('StartupWMClass=Tg-ascii', updated)
            selected = next(line[5:] for line in updated.splitlines() if line.startswith('Icon='))
            self.assertEqual(selected, ICON_NAME)
            themed = base / 'icons/hicolor/512x512/apps' / (selected + '.png')
            self.assertEqual(themed.read_bytes(), b'second')
            self.assertEqual(original, launcher.read_bytes())
            self.assertEqual(list(launcher.parent.iterdir()), [launcher])
            sync_launcher_icon(first)
            self.assertEqual(launcher.read_bytes(), original)
            for n in range(5):
                second.write_bytes(bytes([n]))
                sync_launcher_icon(second)
            self.assertEqual(len(list((base / 'telegraph' / 'launcher-icons').glob('*.png'))), 1)
            launcher.unlink()
            (base / 'system.desktop').write_text(DESKTOP_ENTRY.format(command='/opt/tg-ascii/TG-ASCII', icon=ICON_NAME), encoding='utf-8')
            sync_launcher_icon(first)
            self.assertFalse(launcher.exists())
            self.assertEqual(themed.read_bytes(), b'first')
            second.write_bytes(b'second')
            for malformed in (b'\xffnot UTF-8', b'[invalid', b'[Other]\nName=Other'):
                launcher.write_bytes(malformed)
                sync_launcher_icon(first)
                self.assertEqual(launcher.read_bytes(), malformed)
            launcher.unlink()
            launcher.symlink_to(first)
            sync_launcher_icon(second)
            self.assertTrue(launcher.is_symlink())
            self.assertEqual(first.read_bytes(), b'first')
            launcher.unlink()
            launcher.write_text(DESKTOP_ENTRY.format(command='/opt/tg-ascii/TG-ASCII',icon='old') + 'X-Extra=keep\n', encoding='utf-8')
            sync_launcher_icon(second)
            self.assertIn('X-Extra=keep', launcher.read_text(encoding='utf-8'))
            self.assertIn('Icon=' + selected, launcher.read_text(encoding='utf-8'))
            launcher.write_text('[Desktop Entry]\nExec=/bin/true\nName=Other\n', encoding='utf-8')
            sync_launcher_icon(second)
            self.assertEqual(launcher.read_text(encoding='utf-8'), '[Desktop Entry]\nExec=/bin/true\nName=Other\n')


@unittest.skipUnless(sys.platform.startswith('linux'), 'dpkg-deb runs on Linux')
class DebPackageTests(unittest.TestCase):
    def test_deb_layout_and_metadata(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
        from package_deb import package
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            for machine, architecture in (('aarch64', 'arm64'), ('x86_64', 'amd64')):
                with self.subTest(machine=machine):
                    archive = Path(folder) / f'TeleGraph-9.9.9-linux-{machine}.zip'
                    with zipfile.ZipFile(archive, 'w') as bundle:
                        info = zipfile.ZipInfo(f'{archive.stem}/TG-ASCII')
                        info.external_attr = 0o755 << 16
                        bundle.writestr(info, '#!/bin/sh\n')
                    deb = package(archive)
                    self.assertEqual(deb.name, f'TeleGraph-9.9.9-linux-{architecture}.deb')
                    listing = subprocess.run(['dpkg-deb', '-c', str(deb)], capture_output=True, text=True, check=True).stdout
                    for path in ('./opt/tg-ascii/TG-ASCII', './usr/bin/tg-ascii', './usr/share/applications/tg-ascii.desktop',
                                 './usr/share/icons/hicolor/512x512/apps/tg-ascii.png'):
                        self.assertIn(path, listing)
                    fields = subprocess.run(['dpkg-deb', '-f', str(deb), 'Package', 'Version', 'Architecture'],
                                            capture_output=True, text=True, check=True).stdout
                    self.assertEqual(dict(line.split(': ', 1) for line in fields.splitlines()),
                                     {'Package': 'tg-ascii', 'Version': '9.9.9', 'Architecture': architecture})


if __name__ == '__main__':
    unittest.main()

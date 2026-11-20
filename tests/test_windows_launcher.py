"""Run with python -m unittest discover -s tests -p test_windows_launcher.py on Windows."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


class PinnedIconNoticeTest(unittest.TestCase):
    """Order of the shell notices that makes the pinned taskbar button show a new logo."""

    def update(self, outcomes):
        from tg_ascii import windows_launcher as shell
        notices = []
        windll = mock.MagicMock()
        windll.ole32.CoInitializeEx.return_value = 0
        windll.shell32.SHGetFolderPathW.return_value = -1  # Only the pinned folder below exists.
        windll.shell32.SHChangeNotify.side_effect = (
            lambda event, flags, item, other: notices.append((event, flags, getattr(item, 'value', item))))
        def update_link(path, executable, icon):
            outcome = outcomes[path.name]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        with tempfile.TemporaryDirectory() as folder:
            pins = Path(folder) / 'Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar'
            pins.mkdir(parents=True)
            for name in outcomes:
                (pins / name).write_bytes(b'')
            with mock.patch.object(shell.C, 'windll', windll, create=True), \
                 mock.patch.dict(os.environ, {'APPDATA': folder}), \
                 mock.patch.object(shell, '_update_link', side_effect=update_link):
                shell.update_shortcuts(Path('TeleGraph.exe'), Path('icon.ico'))
            return notices, pins

    def test_icon_cache_is_dropped_before_the_changed_pin_is_announced(self):
        # Without the first notice Windows 11 kept the previous logo on the pin for minutes.
        notices, pins = self.update({'TeleGraph.lnk': True, 'Browser.lnk': False})
        self.assertEqual(notices, [(0x08000000, 0x1000, None), (0x2000, 0x2005, str(pins / 'TeleGraph.lnk'))])

    def test_unchanged_links_send_no_notice(self):
        notices, _ = self.update({'TeleGraph.lnk': False, 'Browser.lnk': False})
        self.assertEqual(notices, [])

    def test_a_failing_link_does_not_hide_the_others(self):
        notices, pins = self.update({'TeleGraph.lnk': True, 'Locked.lnk': OSError('read-only')})
        self.assertEqual(notices, [(0x08000000, 0x1000, None), (0x2000, 0x2005, str(pins / 'TeleGraph.lnk'))])


@unittest.skipUnless(sys.platform == 'win32', 'requires the real Windows Shell')
class WindowsLauncherTest(unittest.TestCase):
    def test_native_icon_variant_and_targeted_shortcut(self):
        import ctypes
        import tkinter
        from tg_ascii import windows_launcher as shell
        from tg_ascii.logos import png_bytes

        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            executable = Path(sys.executable)
            link = folder / 'TeleGraph.lnk'
            env = dict(os.environ, TG_TEST_SHORTCUT=str(link), TG_TEST_EXECUTABLE=str(executable))
            def shortcut(script):
                return subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                               env=env, text=True).strip()
            shortcut('$w=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TG_TEST_SHORTCUT);'
                     '$w.TargetPath=$env:TG_TEST_EXECUTABLE; $w.Save()')
            inspect = ("$s=New-Object -ComObject Shell.Application;"
                       "$i=$s.Namespace((Split-Path $env:TG_TEST_SHORTCUT)).ParseName('TeleGraph.lnk');"
                       "$i.ExtendedProperty('System.AppUserModel.ID');"
                       "(New-Object -ComObject WScript.Shell).CreateShortcut($env:TG_TEST_SHORTCUT).IconLocation")
            status = ctypes.windll.ole32.CoInitializeEx(None, 2)
            root = tkinter.Tk()
            root.title('TeleGraph icon test')
            user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
            user32.SendMessageW.restype = ctypes.c_void_p
            class IconInfo(ctypes.Structure):
                _fields_ = [('icon', ctypes.c_int), ('x', ctypes.c_uint32), ('y', ctypes.c_uint32),
                            ('mask', ctypes.c_void_p), ('color', ctypes.c_void_p)]
            def window_pixels():
                hwnd = int(root.wm_frame(), 0)
                handle = user32.SendMessageW(ctypes.c_void_p(hwnd), 0x7f, 1, 0)  # WM_GETICON / ICON_BIG
                info = IconInfo()
                self.assertTrue(handle and user32.GetIconInfo(ctypes.c_void_p(handle), ctypes.byref(info)))
                try:
                    buffer = ctypes.create_string_buffer(256 * 256 * 4)
                    count = gdi32.GetBitmapBits(ctypes.c_void_p(info.color), len(buffer), buffer)
                    self.assertGreater(count, 0)
                    return buffer.raw[:count]
                finally:
                    for bitmap in (info.mask, info.color):
                        gdi32.DeleteObject(ctypes.c_void_p(bitmap))
            try:
                files, pixels = [], []
                for name in ('title-short', 'telegraph-title', 'title-short'):
                    png = folder / (name + '.png')
                    png.write_bytes(png_bytes(variant=name))
                    icon = shell.icon_file(png, folder)
                    files.append(icon)
                    self.assertTrue(shell._update_link(link, executable, icon))
                    self.assertFalse(shell._update_link(link, executable, icon))
                    shell._announce([link])
                    self.assertEqual(shortcut(inspect).splitlines(), [shell.APP_ID, str(icon) + ',0'])
                    shell.set_window_icon(root, png, False)
                    root.update()
                    pixels.append(window_pixels())
                self.assertEqual(pixels[0], pixels[2])
                self.assertNotEqual(pixels[0], pixels[1])
                self.assertEqual(files[0], files[2])
                self.assertNotEqual(files[0].read_bytes(), files[1].read_bytes())
                self.assertFalse(shell._update_link(link, folder / 'other.exe', files[1]))
                shortcut('$w=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TG_TEST_SHORTCUT);'
                         '$w.Arguments="--demo"; $w.Save()')
                self.assertFalse(shell._update_link(link, executable, files[1]))
            finally:
                root.destroy()
                if status >= 0:
                    ctypes.windll.ole32.CoUninitialize()

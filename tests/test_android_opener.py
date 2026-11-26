import ast
import asyncio
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import threading
from types import ModuleType, SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch


class AndroidOpenerTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.target = self.folder / 'large.mp4'
        self.target.write_bytes(b'video-bytes-' * (1 << 19))
        self.ui_thread = threading.get_ident()
        self.presented, self.content_threads = [], []
        self.rows, self.deleted, self.updated = [], [], []
        self.fail_write = False
        testcase = self

        class Intent:
            ACTION_VIEW, ACTION_SEND, EXTRA_STREAM = 'view', 'send', 'stream'
            FLAG_GRANT_READ_URI_PERMISSION, FLAG_ACTIVITY_NEW_TASK = 1, 2

            def __init__(self, *args):
                testcase.assertEqual(threading.get_ident(), testcase.ui_thread)

            def __getattr__(self, name):
                return lambda *args: None

            @staticmethod
            def createChooser(intent, title):
                return intent

        class Integer(int):
            pass

        class Values(dict):
            def put(self, key, value):
                if type(value) is int:
                    raise TypeError('ContentValues.put is ambiguous for arguments (str, int)')
                self[key] = value

        class Stream:
            def write(self, value):
                testcase.content_threads.append(threading.get_ident())
                if testcase.fail_write:
                    raise OSError('storage full')

            def close(self):
                pass

        class Resolver:
            def insert(self, target, values):
                testcase.rows.append(values)
                return 'content://saved'

            def openOutputStream(self, uri):
                return Stream()

            def delete(self, *args):
                testcase.deleted.append(args)

            def update(self, *args):
                testcase.updated.append(args)

        self.activity = SimpleNamespace(
            getCacheDir=lambda: SimpleNamespace(getAbsolutePath=lambda: str(self.folder / 'cache')),
            getPackageName=lambda: 'org.example.app',
            getContentResolver=lambda: Resolver(),
            startActivity=lambda intent: self.presented.append((threading.get_ident(), intent)),
        )
        exports = {
            'android.content': dict(Intent=Intent, ContentValues=Values,
                                    ClipData=SimpleNamespace(newRawUri=lambda title, uri: uri)),
            'android.net': dict(Uri=SimpleNamespace(parse=lambda uri: uri)),
            'android.os': dict(Build=SimpleNamespace(VERSION=SimpleNamespace(SDK_INT=35))),
            'java.io': dict(File=lambda path: path),
            'java.lang': dict(Integer=Integer),
            'androidx.core.content': dict(FileProvider=SimpleNamespace(getUriForFile=lambda *args: args[-1])),
            'android.provider': dict(MediaStore=SimpleNamespace(
                MediaColumns=SimpleNamespace(DISPLAY_NAME='name', MIME_TYPE='mime', RELATIVE_PATH='path', IS_PENDING='pending'),
                Downloads=SimpleNamespace(EXTERNAL_CONTENT_URI='downloads'))),
        }
        modules = {}
        for name, items in exports.items():
            module = modules[name] = ModuleType(name)
            module.__dict__.update(items)
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, modules).start()
        # Execute the production method without creating a Toga app or Java VM.
        source = Path(__file__).parents[1] / 'src/tg_ascii_mobile/app.py'
        cls = next(node for node in ast.parse(source.read_text()).body if isinstance(node, ast.ClassDef))
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                      and node.name == 'install_android_opener')
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
        self.app = SimpleNamespace(loop=asyncio.get_running_loop(), core=SimpleNamespace(
            account='first', backend=object(), locked=False))
        namespace['install_android_opener'](self.app, self.activity)

    async def copy_gate(self, *, change_account=False):
        entered, release = threading.Event(), threading.Event()
        finished = asyncio.get_running_loop().create_future()
        copy = shutil.copyfile
        copy_threads, done_threads = [], []

        def slow_copy(*args, **kwargs):
            copy_threads.append(threading.get_ident())
            entered.set()
            if not release.wait(2):
                raise TimeoutError('The interface did not release the copy')
            return copy(*args, **kwargs)

        def done(result):
            done_threads.append(threading.get_ident())
            finished.set_result(result)

        with patch('shutil.copyfile', side_effect=slow_copy):
            self.app.core.native_open('share', str(self.target), done)
            try:
                await asyncio.wait_for(asyncio.to_thread(entered.wait, 1), 1.5)
                # This callback must run while the worker is still copying.
                heartbeat = asyncio.get_running_loop().create_future()
                self.app.loop.call_soon(heartbeat.set_result, True)
                self.assertTrue(await asyncio.wait_for(heartbeat, .2))
                if change_account:
                    self.app.core.account = 'second'
            finally:
                release.set()
            result = await asyncio.wait_for(finished, 2)
        self.assertNotIn(self.ui_thread, copy_threads)
        self.assertEqual(done_threads, [self.ui_thread])
        return result

    async def test_large_share_copy_keeps_ui_responsive_and_presents_on_ui(self):
        self.assertTrue(await self.copy_gate())
        self.assertEqual(len(self.presented), 1)
        self.assertEqual(self.presented[0][0], self.ui_thread)
        copies = list((self.folder / 'cache/shared').glob('*/*'))
        self.assertEqual([item.read_bytes() for item in copies], [self.target.read_bytes()])

    async def test_account_change_during_copy_prevents_late_chooser_and_removes_copy(self):
        self.assertFalse(await self.copy_gate(change_account=True))
        self.assertFalse(self.presented)
        self.assertEqual(list((self.folder / 'cache/shared').glob('*')), [])

    async def test_save_runs_off_ui_and_only_publishes_complete_media(self):
        done = asyncio.get_running_loop().create_future()
        self.app.core.native_open('save', str(self.target), done.set_result)
        self.assertTrue(await asyncio.wait_for(done, 2))
        self.assertNotIn(self.ui_thread, self.content_threads)
        self.assertEqual(self.rows[0]['pending'], 1)
        self.assertEqual(self.updated[0][1], {'pending': 0})
        self.assertFalse(self.deleted)

    async def test_failed_save_removes_partial_mediastore_entry(self):
        self.fail_write = True
        done = asyncio.get_running_loop().create_future()
        self.app.core.native_open('save', str(self.target), done.set_result)
        self.assertFalse(await asyncio.wait_for(done, 2))
        self.assertEqual(self.deleted, [('content://saved', None, None)])
        self.assertFalse(self.updated)

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock

from tg_ascii_mobile.core import Core


class VoiceLifecycleTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = Core(Path(directory.name), 'test')
        self.core.loop.close()
        self.core.loop = asyncio.get_running_loop()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.path = None

        def start(base, callback):
            self.path = Path(base + '.ogg')
            self.callback = callback
            self.started.set()

        def cancel():
            self.core.loop.call_soon_threadsafe(self.cancelled.set)
            return self.path

        self.core.native_voice = {'start': start, 'cancel': cancel, 'level': lambda: 0}

    async def test_lock_cancels_pending_permission_and_ignores_late_result(self):
        pending = asyncio.create_task(self.core.api_voice_start(capture='first'))
        await asyncio.wait_for(self.started.wait(), 1)
        self.core.lock_record = Mock(return_value={'enabled': True})
        self.core.lock()
        await asyncio.wait_for(self.cancelled.wait(), 1)
        self.callback({'path': str(self.path)})
        with self.assertRaises(ValueError):
            await pending
        self.assertIsNone(self.core.voice_recording)
        self.assertFalse((await self.core.api_voice_level(capture='first'))['recording'])

    async def test_another_window_cannot_stop_or_cancel_an_active_note(self):
        pending = asyncio.create_task(self.core.api_voice_start(capture='new'))
        await asyncio.wait_for(self.started.wait(), 1)
        self.path.write_bytes(b'fixture')
        self.callback({'path': str(self.path)})
        await pending
        with self.assertRaises(ValueError):
            await self.core.api_voice_start(capture='other')
        with self.assertRaises(ValueError):
            await self.core.api_voice_stop(capture='older')
        await self.core.api_voice_cancel(capture='older')
        self.assertTrue((await self.core.api_voice_level(capture='new'))['recording'])
        await self.core.api_voice_cancel(capture='new')
        self.assertFalse(self.path.exists())

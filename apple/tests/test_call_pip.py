import asyncio
import io
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock

from PIL import Image

from tg_ascii_mobile.call_pip import CallPictureInPicture


class NativeCallPictureInPictureTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = Mock()
        self.manager.snapshot = {'token': 'current', 'state': 'active', 'video': True}
        self.manager.take_frame.return_value = None
        self.manager.take_local_frame.return_value = None
        self.core = SimpleNamespace(locked=False, account='first', call_manager=self.manager,
                                    group_call_manager=None)
        self.window = Mock()
        self.window.open.return_value = True
        self.window.status.return_value = 2
        self.factory = Mock(return_value=self.window)
        self.pip = CallPictureInPicture(self.core, asyncio.get_running_loop().call_soon, self.factory)

    async def asyncTearDown(self):
        if self.pip.task:
            self.pip.close()
            await asyncio.wait_for(self.pip.task, 1)

    async def test_local_video_when_remote_camera_is_off(self):
        self.manager.take_local_frame.return_value = {
            'token': 'current', 'width': 4, 'height': 2, 'rotation': 90,
            'data': bytes([120] * 8 + [128] * 4),
        }
        framed = asyncio.Event()
        self.window.frame.side_effect = lambda data: framed.set()
        first, second = await asyncio.gather(self.pip.open('current'), self.pip.open('current'))
        self.assertTrue(first and second)
        self.factory.assert_called_once_with('current')
        await asyncio.wait_for(framed.wait(), 1)
        with Image.open(io.BytesIO(self.window.frame.call_args.args[0])) as image:
            self.assertEqual((image.format, image.size), ('JPEG', (2, 4)))

    async def test_account_change_stops_group_route_without_consuming_another_frame(self):
        self.core.group_call_manager, self.core.call_manager = self.manager, None
        self.assertFalse(await self.pip.open('current'))
        self.assertTrue(await self.pip.open('current', group=True))
        self.core.account = 'second'
        pulls = self.manager.take_frame.call_count
        await asyncio.wait_for(self.pip.task, 1)
        self.assertEqual(self.manager.take_frame.call_count, pulls)
        self.window.close.assert_called_once()
        self.assertFalse(self.pip.matches('current'))

    async def test_rejects_stale_locked_or_ended_call(self):
        self.assertFalse(await self.pip.open('old'))
        self.core.locked = True
        self.assertFalse(await self.pip.open('current'))
        self.core.locked = False
        self.manager.snapshot['state'] = 'ended'
        self.assertFalse(await self.pip.open('current'))
        self.factory.assert_not_called()

    async def test_reopens_after_native_start_fails_and_after_dismissal(self):
        self.window.status.return_value = 0
        self.assertFalse(await self.pip.open('current'))
        self.window.status.return_value = 2
        self.assertTrue(await self.pip.open('current'))
        task = self.pip.task
        self.window.status.return_value = 0
        await asyncio.wait_for(task, 1)
        self.assertFalse(self.pip.matches('current'))
        self.window.status.return_value = 2
        self.assertTrue(await self.pip.open('current'))

    async def test_lock_cancels_open_even_while_native_window_is_starting(self):
        started = asyncio.Event()
        def starting():
            started.set()
            return 1
        self.window.status.side_effect = starting
        requested = asyncio.create_task(self.pip.open('current'))
        await asyncio.wait_for(started.wait(), 1)
        self.core.locked = True
        self.pip.close()
        self.assertFalse(await asyncio.wait_for(requested, 1))
        self.window.frame.assert_not_called()


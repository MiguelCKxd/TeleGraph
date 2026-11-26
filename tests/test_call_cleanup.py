import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock, patch

from tg_ascii.calls_group_native import GroupNativeProxy


class GroupCleanupTests(IsolatedAsyncioTestCase):
    async def test_finished_group_child_is_removed_from_exit_registry(self):
        proxy = GroupNativeProxy()
        proxy._process = SimpleNamespace(pid=987654, returncode=0, stdin=Mock())
        with patch('tg_ascii.app_lifecycle.unregister_child') as unregister:
            await proxy.close()
        unregister.assert_called_once_with(987654)
        proxy._process.stdin.close.assert_called_once()

    async def test_callbacks_are_drained_before_native_owner_closes(self):
        proxy = GroupNativeProxy()
        started, finished = asyncio.Event(), asyncio.Event()
        async def callback():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.set()
        task = asyncio.create_task(callback())
        proxy._native_tasks.add(task)
        await started.wait()
        await proxy.close()
        self.assertTrue(task.done())
        self.assertTrue(finished.is_set())
        self.assertFalse(proxy._native_tasks)

    async def test_close_from_callback_does_not_cancel_or_await_itself(self):
        proxy = GroupNativeProxy()
        async def callback():
            proxy._native_tasks.add(asyncio.current_task())
            await proxy.close()
            return True
        self.assertTrue(await asyncio.wait_for(asyncio.create_task(callback()), 1))

    async def test_threadsafe_callback_future_is_supported(self):
        from concurrent.futures import Future
        proxy = GroupNativeProxy()
        future = Future()
        proxy._native_tasks.add(future)
        await proxy.close()
        self.assertTrue(future.cancelled())

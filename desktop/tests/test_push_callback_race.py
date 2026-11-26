import asyncio
from unittest import IsolatedAsyncioTestCase

from tg_ascii.push_macos import complete_on_loop, PushUnavailable


class PushCallbackRaceTests(IsolatedAsyncioTestCase):
    async def test_registration_response_after_timeout_is_discarded_on_worker(self):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        complete_on_loop(loop, future, result='fixture-token')
        future.cancel()  # timeout wins after the OS callback was enqueued
        failures = []
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _, context: failures.append(context))
        try:
            await asyncio.sleep(0)
            self.assertTrue(future.cancelled())
            self.assertEqual(failures, [])
        finally:
            loop.set_exception_handler(previous)

    async def test_duplicate_registration_callbacks_do_not_overwrite_first_result(self):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        failures = []
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _, context: failures.append(context))
        try:
            complete_on_loop(loop, future, result='fixture-token')
            complete_on_loop(loop, future, error=PushUnavailable('late error'))
            self.assertEqual(await future, 'fixture-token')
            self.assertEqual(failures, [])
        finally:
            loop.set_exception_handler(previous)

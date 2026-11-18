"""Exercise the real optional helper without devices, network or accounts."""
import asyncio
import secrets
import signal
import sys
import time
from types import SimpleNamespace
import unittest

from tg_ascii.calls_native import engine_available
from tg_ascii.calls_process import NativeWorkerError, ProcessNativeEngine
from tests.test_calls_native_v12 import PRIME


@unittest.skipUnless(engine_available(), 'Optional native calls component is absent')
class ProcessEngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []
        self.engines = []

    def engine(self):
        engine = ProcessNativeEngine(lambda *args: self.events.append(args),
            lambda *args: None, lambda *args: None, lambda *args: None)
        self.engines.append(engine)
        return engine

    async def asyncTearDown(self):
        await asyncio.gather(*(engine.stop(engine._peer or 0)
                              for engine in self.engines))

    async def test_constructor_does_not_start_a_process(self):
        engine = self.engine()
        self.assertIsNone(engine._process)
        self.assertFalse(engine._pending)

    async def test_two_helpers_exchange_and_exit_normally(self):
        first, second = self.engine(), self.engine()
        dh = SimpleNamespace(g=2, p=PRIME, random=secrets.token_bytes(256))
        ga_hash = await first.create(2, dh)
        gb = await second.create(1, dh, ga_hash)
        outgoing = await first.exchange(2, gb)
        incoming = await second.exchange(1, outgoing.g_a_or_b,
                                         outgoing.key_fingerprint)
        self.assertEqual(outgoing.key_fingerprint, incoming.key_fingerprint)
        self.assertTrue(first.protocol().library_versions)
        await asyncio.gather(first.stop(2), second.stop(1))
        for engine in (first, second):
            self.assertEqual(engine.exit_code, 0)
            self.assertFalse(engine._pending)
            self.assertTrue(engine._reader.done())

    async def test_child_crash_is_reported_without_crashing_parent(self):
        engine = self.engine()
        dh = SimpleNamespace(g=2, p=PRIME, random=secrets.token_bytes(256))
        await engine.create(11, dh)
        engine._process.kill()
        await asyncio.wait_for(engine._process.wait(), 2)
        await asyncio.wait_for(engine._reader, 2)
        self.assertIn((11, 'FAILED'), self.events)
        self.assertFalse(engine._pending)
        await engine.stop(11)
        self.assertIsNotNone(engine.exit_code)

    async def test_unknown_command_fails_without_leaking_request(self):
        engine = self.engine()
        with self.assertRaises(NativeWorkerError):
            await engine._request('arbitrary_operation')
        self.assertFalse(engine._pending)
        await engine.stop(0)
        self.assertEqual(engine.exit_code, 0)

    @unittest.skipIf(sys.platform == 'win32', 'SIGSTOP is a POSIX fault injection')
    async def test_frozen_helper_is_killed_with_bounded_cleanup(self):
        engine = self.engine()
        dh = SimpleNamespace(g=2, p=PRIME, random=secrets.token_bytes(256))
        await engine.create(11, dh)
        engine._process.send_signal(signal.SIGSTOP)
        began = time.monotonic()
        await asyncio.wait_for(engine.stop(11), 6)
        self.assertLess(time.monotonic() - began, 6)
        self.assertEqual(engine.exit_code, -signal.SIGKILL)
        self.assertFalse(engine._pending)
        self.assertTrue(engine._reader.done())

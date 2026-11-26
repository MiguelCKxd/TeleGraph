"""Loopback recovery tests; no Core, accounts, configuration or Telegram access."""
import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from tg_ascii_mobile.server import Server


class ProbeServer(Server):
    def __init__(self):
        super().__init__(SimpleNamespace())
        self.listeners = []
        self.connections = set()
        self.handlers = set()

    async def start(self, port=0):
        port = await super().start(port)
        self.listeners.append(self.server)
        return port

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        self.connections.add(writer)
        try:
            while data := await reader.read(1024):
                writer.write(data)
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            self.connections.discard(writer)
            self.handlers.discard(task)

    async def close(self):
        for listener in self.listeners:
            listener.close()
        for writer in tuple(self.connections):
            writer.close()
        if self.handlers:
            await asyncio.gather(*tuple(self.handlers), return_exceptions=True)
        await asyncio.gather(*(listener.wait_closed() for listener in self.listeners))


class ServerRecoveryTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = ProbeServer()
        await self.bridge.start()
        self.addAsyncCleanup(self.bridge.close)

    async def stop_listener(self):
        self.bridge.server.close()
        await self.bridge.server.wait_closed()

    async def test_simultaneous_resume_creates_only_one_replacement_listener(self):
        await self.stop_listener()
        alive = self.bridge.alive

        async def slow_health_check():
            result = await alive()
            # Both callers can observe the dead socket before either binds.
            await asyncio.sleep(0.02)
            return result

        with patch.object(self.bridge, 'alive', slow_health_check):
            ports = await asyncio.wait_for(asyncio.gather(
                self.bridge.ensure(), self.bridge.ensure(), self.bridge.ensure()), 2)
        self.assertEqual(len(set(ports)), 1)
        self.assertEqual(len(self.bridge.listeners), 2)  # Initial + one replacement.
        self.assertEqual(sum(item.is_serving() for item in self.bridge.listeners), 1)

    async def test_healthy_resume_does_not_replace_listener(self):
        original = self.bridge.server
        ports = await asyncio.gather(*(self.bridge.ensure() for _ in range(8)))
        self.assertEqual(ports, [self.bridge.port] * 8)
        self.assertIs(self.bridge.server, original)
        self.assertEqual(len(self.bridge.listeners), 1)

    async def test_cancelled_waiter_does_not_cancel_in_progress_repair(self):
        await self.stop_listener()
        entered, release = asyncio.Event(), asyncio.Event()
        start = self.bridge.start

        async def delayed_start(port=0):
            entered.set()
            await release.wait()
            return await start(port)

        with patch.object(self.bridge, 'start', delayed_start):
            repair = asyncio.create_task(self.bridge.ensure())
            await asyncio.wait_for(entered.wait(), 1)
            waiter = asyncio.create_task(self.bridge.ensure())
            await asyncio.sleep(0)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            release.set()
            port = await asyncio.wait_for(repair, 1)
        self.assertEqual(await self.bridge.ensure(), port)
        self.assertEqual(len(self.bridge.listeners), 2)

    async def test_failed_old_port_bind_uses_one_fallback_for_all_callers(self):
        await self.stop_listener()
        original_port, attempts = self.bridge.port, []
        start = self.bridge.start

        async def unavailable_old_port(port=0):
            attempts.append(port)
            if port == original_port:
                raise OSError('simulated unavailable former port')
            return await start(port)

        with patch.object(self.bridge, 'start', unavailable_old_port):
            ports = await asyncio.gather(self.bridge.ensure(), self.bridge.ensure())
        self.assertEqual(attempts, [original_port, 0])
        self.assertEqual(ports, [self.bridge.port] * 2)
        self.assertEqual(sum(item.is_serving() for item in self.bridge.listeners), 1)

    async def test_failed_repair_releases_lock_for_a_later_retry(self):
        await self.stop_listener()

        async def failed_start(port=0):
            raise RuntimeError('synthetic listener setup failure')

        with patch.object(self.bridge, 'start', failed_start):
            with self.assertRaises(RuntimeError):
                await self.bridge.ensure()
        self.assertEqual(await asyncio.wait_for(self.bridge.ensure(), 1), self.bridge.port)
        self.assertTrue(await self.bridge.alive())

    async def test_repair_does_not_wait_for_or_interrupt_existing_connections(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.bridge.port)
        try:
            writer.write(b'before')
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(6), 1), b'before')

            async def reclaimed_listener():
                return False

            # A previously accepted SSE/download connection can remain alive even
            # when the listener must be replaced. wait_closed() would block here.
            with patch.object(self.bridge, 'alive', reclaimed_listener):
                await asyncio.wait_for(self.bridge.ensure(), 1)
            writer.write(b'after')
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(5), 1), b'after')
            self.assertTrue(await self.bridge.alive())
        finally:
            writer.close()
            await writer.wait_closed()

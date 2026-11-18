import unittest
from types import SimpleNamespace
from tg_ascii.calls_source_volume import SourceVolumes


class Proxy:
    def __init__(self):
        self.calls = []
    async def set_source_volume(self, *args):
        self.calls.append(args)


def row(user, source):
    return SimpleNamespace(user_id=user, source=source)


class SourceVolumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_has_no_native_traffic(self):
        proxy = Proxy()
        v = SourceVolumes(proxy, -11)
        await v.sync([row(1, 10), row(2, 20)])
        self.assertEqual(proxy.calls, [])
        self.assertEqual(v.percent(1), 100)

    async def test_gain_is_local_to_source_and_signed_ssrc_normalized(self):
        proxy = Proxy()
        v = SourceVolumes(proxy, -11)
        await v.set(1, 0, [row(1, -1), row(2, 20)])
        self.assertEqual(proxy.calls, [(-11, 4294967295, 0)])
        self.assertEqual(v.percent(2), 100)
        await v.sync([row(1, -1), row(2, 20)])
        self.assertEqual(len(proxy.calls), 1)

    async def test_rejoin_and_departure_restore_old_sources(self):
        proxy = Proxy()
        v = SourceVolumes(proxy, -11)
        await v.set(1, 5000, [row(1, 10)])
        await v.sync([row(1, 30)])
        await v.sync([])
        await v.sync([row(1, 40)])
        await v.set(1, 10000, [row(1, 40)])
        self.assertEqual(proxy.calls, [(-11,10,5000),(-11,10,10000),(-11,30,5000),
            (-11,30,10000),(-11,40,5000),(-11,40,10000)])
        self.assertFalse(v.applied)
        self.assertFalse(v.gains)

    async def test_new_native_connection_reapplies_same_source_gain(self):
        proxy = Proxy()
        v = SourceVolumes(proxy, -11)
        await v.set(1, 5000, [row(1, 10)])
        proxy.volume_generation = 1
        await v.sync([row(1, 10)])
        self.assertEqual(proxy.calls, [(-11,10,5000), (-11,10,5000)])

    async def test_failed_gain_is_not_presented_as_applied_and_can_be_retried(self):
        proxy = Proxy()
        v = SourceVolumes(proxy, -11)
        original = proxy.set_source_volume
        async def fail(*args):
            raise RuntimeError('Native worker unavailable')
        proxy.set_source_volume = fail
        with self.assertRaises(RuntimeError):
            await v.set(1, 5000, [row(1,10)])
        self.assertEqual(v.percent(1), 100)
        proxy.set_source_volume = original
        await v.sync([row(1,10)])
        self.assertEqual(v.percent(1), 50)

    async def test_bad_or_departed_target_never_changes_native_audio(self):
        proxy = Proxy()
        v = SourceVolumes(proxy, -11)
        for gain in (-1, 20001, True, 1.5):
            with self.assertRaises(ValueError):
                await v.set(1, gain, [row(1, 10)])
        with self.assertRaises(ValueError):
            await v.set(2, 5000, [row(1,10)])
        self.assertFalse(proxy.calls)

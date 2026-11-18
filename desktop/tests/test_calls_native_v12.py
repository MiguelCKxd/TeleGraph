"""Optional native checks without accounts, network, microphone or camera."""
import asyncio
import importlib.util
import secrets
from types import SimpleNamespace
import unittest

from tg_ascii.calls_crypto import validate_dh
from tg_ascii.calls_native import engine_available, frame_image
from tg_ascii.calls_process import ProcessNativeEngine, NativeWorkerError


# RFC 3526 MODP group 14, a public 2048-bit safe prime for offline test exchange.
PRIME = bytes.fromhex(''.join('''
FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA6
3B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245
E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F241
17C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F
83655D23DCA3AD961C62F356208552BB9ED529077096966D670C354E4ABC9804F1746C08CA
18217C32905E462E36CE3BE39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE
2BCBF6955817183995497CEA956AE515D2261898FA051015728E5A8AACAA68FFFFFFFFFFFFFFFF
'''.split()))


@unittest.skipUnless(engine_available(), 'Optional native call engine not installed')
class NativeCryptoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await asyncio.to_thread(validate_dh, 2, PRIME)
        # Exercise actual native crypto in the same disposable process used by
        # production; no C++ destructor may hang/abort the test runner itself.
        self.emojis = [None, None]
        self.a, self.b = [ProcessNativeEngine(lambda *x: None, lambda *x: None,
            lambda *x: None, lambda peer, value, i=i: self.emojis.__setitem__(i, value))
            for i in range(2)]
        self.dh = SimpleNamespace(g=2, p=PRIME, random=secrets.token_bytes(256))

    async def asyncTearDown(self):
        await self.a.stop(11)
        await self.b.stop(22)

    async def exchange(self):
        commitment = await self.a.create(11, self.dh)
        gb = await self.b.create(22, self.dh, commitment)
        auth = await self.a.exchange(11, gb)
        return auth

    async def test_real_native_key_exchange_and_emojis_match(self):
        auth_a = await self.exchange()
        auth_b = await self.b.exchange(22, auth_a.g_a_or_b, auth_a.key_fingerprint)
        self.assertEqual(auth_a.key_fingerprint, auth_b.key_fingerprint)
        async with asyncio.timeout(2):
            while not all(self.emojis):
                await asyncio.sleep(0.01)
        self.assertEqual(self.emojis[0], self.emojis[1])
        await self.a.stop(11)
        await self.b.stop(22)
        self.assertFalse(self.a._pending)
        self.assertFalse(self.b._pending)
        self.assertEqual((self.a.exit_code, self.b.exit_code), (0, 0))

    async def test_real_native_rejects_modified_commitment(self):
        commitment = await self.a.create(11, self.dh)
        gb = await self.b.create(22, self.dh, bytes([commitment[0] ^ 1]) + commitment[1:])
        auth_a = await self.a.exchange(11, gb)
        with self.assertRaisesRegex(NativeWorkerError, 'CryptoError'):
            await self.b.exchange(22, auth_a.g_a_or_b, auth_a.key_fingerprint)

    async def test_real_native_rejects_modified_fingerprint(self):
        auth_a = await self.exchange()
        with self.assertRaisesRegex(NativeWorkerError, 'CryptoError'):
            await self.b.exchange(22, auth_a.g_a_or_b, auth_a.key_fingerprint ^ 1)

    async def test_real_native_rejects_out_of_range_public_key(self):
        await self.a.create(11, self.dh)
        with self.assertRaisesRegex(NativeWorkerError, 'CryptoError|InvalidParams'):
            await self.a.exchange(11, b'\x01')


@unittest.skipUnless(importlib.util.find_spec('av') and importlib.util.find_spec('PIL'),
                     'Optional video decoder not installed')
class NativeFrameTests(unittest.TestCase):
    def test_odd_size_i420_stride_and_rotation(self):
        # Neutral chroma and constant luma should produce a uniform grey image.
        frame = dict(width=3, height=5, rotation=90, data=b'\x80' * (15 + 2 * 2 * 3))
        image = frame_image(frame)
        self.assertEqual(image.size, (5, 3))
        self.assertEqual(len({image.getpixel((x, y)) for x in range(5) for y in range(3)}), 1)
        r, g, b = image.getpixel((0, 0))
        self.assertLess(max(r, g, b) - min(r, g, b), 3)

    def test_malformed_video_data_is_rejected(self):
        with self.assertRaises(ValueError):
            frame_image(dict(width=2, height=2, data=b'bad'))

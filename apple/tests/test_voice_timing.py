from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from tg_ascii_mobile import opus_mux
from tg_ascii_mobile.server import playable_caf


class VoiceTimingTests(TestCase):
    def test_both_conversions_preserve_packet_timing(self):
        packets = [bytes.fromhex('f8fffe')] * 250
        for skip, padding in [(312, 311), (0, 0)]:
            with self.subTest(skip=skip, padding=padding), TemporaryDirectory() as directory:
                folder = Path(directory)
                source, message = folder / 'original.caf', folder / 'message.ogg'
                seconds = (960 * len(packets) - skip - padding) / 48000
                source.write_bytes(opus_mux.write_caf(packets, pre_skip=skip, remainder=padding))
                self.assertEqual(opus_mux.caf_to_ogg(source, message), seconds)
                self.assertEqual(opus_mux.duration(message), seconds)
                legacy = folder / 'message-play.caf'
                legacy.write_bytes(b'old timing')
                preview = playable_caf(message)
                self.assertNotEqual(preview, message)
                self.assertEqual(source.read_bytes(), preview.read_bytes())
                self.assertEqual(opus_mux.duration(preview), seconds)

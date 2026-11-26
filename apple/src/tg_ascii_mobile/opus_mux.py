"""Move Opus audio between the Ogg and CAF containers, without re-encoding.

Telegram voice messages are Ogg/Opus. iOS records Opus only into CAF files,
and Safari (the iOS WebView) plays Opus from CAF but not always from Ogg, so:
- caf_to_ogg: a recording made on iOS -> a voice message for Telegram;
- ogg_to_caf: a voice message from Telegram -> something iOS can play.
Pure Python; the audio packets are copied as they are.
"""
import struct
from pathlib import Path

SAMPLE_RATE = 48000


# -- Ogg ----------------------------------------------------------------------
def _crc_table():
    table = []
    for index in range(256):
        value = index << 24
        for _ in range(8):
            value = ((value << 1) ^ 0x04C11DB7) if value & 0x80000000 else (value << 1)
        table.append(value & 0xFFFFFFFF)
    return table


_CRC = _crc_table()


def _ogg_crc(data):
    crc = 0
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC[((crc >> 24) & 0xFF) ^ byte]
    return crc


def _ogg_page(serial, sequence, granule, packets, flags=0):
    """One page holding whole packets (each under 255 * 255 bytes in all)."""
    lacing = bytearray()
    for packet in packets:
        size = len(packet)
        lacing.extend([255] * (size // 255))
        lacing.append(size % 255)
    header = struct.pack('<4sBBqIII', b'OggS', 0, flags, granule, serial, sequence, 0)
    page = bytearray(header + bytes([len(lacing)]) + bytes(lacing) + b''.join(packets))
    struct.pack_into('<I', page, 22, _ogg_crc(page))
    return bytes(page)


def _ogg_packets(data):
    """The packets of the first logical stream of an Ogg file."""
    packets, current, offset, serial = [], bytearray(), 0, None
    previous_granule = remainder = 0
    while offset + 27 <= len(data):
        if data[offset:offset + 4] != b'OggS':
            raise ValueError('not an Ogg file')
        page_serial = struct.unpack_from('<I', data, offset + 14)[0]
        count = data[offset + 26]
        lacing = data[offset + 27:offset + 27 + count]
        body = offset + 27 + count
        if serial is None:
            serial = page_serial
        if body > len(data) or body + sum(lacing) > len(data):
            raise ValueError('incomplete Ogg page')
        first_packet = len(packets)
        for size in lacing:
            if page_serial == serial:
                current.extend(data[body:body + size])
            body += size
            if size < 255 and page_serial == serial:
                packets.append(bytes(current))
                current = bytearray()
        if page_serial == serial and len(packets) > max(2, first_packet):
            granule = struct.unpack_from('<q', data, offset + 6)[0]
            if data[offset + 5] & 4:
                frames = sum(opus_frames(packet) for packet in packets[max(2, first_packet):])
                remainder = max(0, frames - max(0, granule - previous_granule))
            previous_granule = granule
        offset = body
    return packets, remainder


def opus_frames(packet):
    """Samples (at 48 kHz) in one Opus packet, from its TOC byte (RFC 6716 3.1)."""
    if not packet:
        return 0
    config = packet[0] >> 3
    if config < 12:
        size = (480, 960, 1920, 2880)[config % 4]
    elif config < 16:
        size = (480, 960)[config % 2]
    else:
        size = (120, 240, 480, 960)[config % 4]
    code = packet[0] & 3
    if code == 0:
        count = 1
    elif code in (1, 2):
        count = 2
    else:
        count = (packet[1] & 0x3F) if len(packet) > 1 else 0
    return size * count


def _opus_head(channels, pre_skip, rate=SAMPLE_RATE):
    return b'OpusHead' + struct.pack('<BBHIhB', 1, channels, pre_skip, rate, 0, 0)


def _opus_tags(vendor=b'TG-ASCII'):
    return b'OpusTags' + struct.pack('<I', len(vendor)) + vendor + struct.pack('<I', 0)


def write_ogg(packets, channels=1, pre_skip=312, serial=0x54474153, remainder=0):
    """Ogg/Opus bytes for raw Opus packets."""
    out = [_ogg_page(serial, 0, 0, [_opus_head(channels, pre_skip)], flags=2),
           _ogg_page(serial, 1, 0, [_opus_tags()])]
    sequence, granule, page, size = 2, 0, [], 0
    for index, packet in enumerate(packets):
        page.append(packet)
        size += len(packet)
        granule += opus_frames(packet)
        last = index == len(packets) - 1
        # About a second of audio per page; lacing allows 255 segments.
        segments = sum(len(item) // 255 + 1 for item in page)
        if last or size > 4000 or segments > 200:
            out.append(_ogg_page(serial, sequence, granule - (remainder if last else 0), page, flags=4 if last else 0))
            sequence, page, size = sequence + 1, [], 0
    if not packets:
        out.append(_ogg_page(serial, sequence, pre_skip, [], flags=4))
    return b''.join(out)


def _read_ogg(data):
    """(packets, channels, pre_skip) of an Ogg/Opus file."""
    packets, remainder = _ogg_packets(data)
    if not packets or not packets[0].startswith(b'OpusHead'):
        raise ValueError('not Ogg/Opus')
    head = packets[0]
    channels = head[9]
    pre_skip = struct.unpack_from('<H', head, 10)[0]
    audio = [packet for packet in packets[1:] if not packet.startswith(b'OpusTags')]
    return audio, channels, pre_skip, remainder


# -- CAF ----------------------------------------------------------------------
def _varint(value):
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


def _read_varint(data, offset):
    value = 0
    while True:
        byte = data[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, offset


def _read_caf(data):
    """(packets, channels, pre_skip) of a CAF file with Opus audio."""
    if data[:4] != b'caff':
        raise ValueError('not a CAF file')
    offset, desc, table, audio = 8, None, None, None
    while offset + 12 <= len(data):
        kind = data[offset:offset + 4]
        size = struct.unpack_from('>q', data, offset + 4)[0]
        body = offset + 12
        end = len(data) if size < 0 else body + size
        if kind == b'desc':
            desc = struct.unpack_from('>d4sIIIII', data, body)
        elif kind == b'pakt':
            table = data[body:end]
        elif kind == b'data':
            audio = data[body + 4:end]  # after mEditCount
        if size < 0:
            break
        offset = end
    if desc is None or audio is None or desc[1] != b'opus':
        raise ValueError('not Opus in CAF')
    _rate, _format, _flags, bytes_per_packet, frames_per_packet, channels, _bits = desc
    pre_skip = remainder = 0
    if table is not None:
        count, _valid, pre_skip, remainder = struct.unpack_from('>qqii', table, 0)
    if bytes_per_packet:
        sizes = [bytes_per_packet] * (len(audio) // bytes_per_packet)
    else:
        if table is None:
            raise ValueError('CAF without a packet table')
        sizes, position = [], 24
        for _ in range(count):
            size, position = _read_varint(table, position)
            if not frames_per_packet:
                _frames, position = _read_varint(table, position)
            sizes.append(size)
    packets, position = [], 0
    for size in sizes:
        if position + size > len(audio):
            break
        packets.append(bytes(audio[position:position + size]))
        position += size
    return packets, channels or 1, max(0, pre_skip), max(0, remainder)


def write_caf(packets, channels=1, pre_skip=312, remainder=0):
    frames = [opus_frames(packet) for packet in packets]
    constant = frames[0] if frames and all(item == frames[0] for item in frames) else 0
    total = sum(frames)
    valid = max(0, total - pre_skip - remainder)
    desc = struct.pack('>d4sIIIII', float(SAMPLE_RATE), b'opus', 0, 0, constant, channels, 0)
    cookie = struct.pack('>IIIiIII', 0x800, SAMPLE_RATE, constant or 960, -1000, channels, 0, 0)
    entries = bytearray()
    for packet, count in zip(packets, frames):
        entries += _varint(len(packet))
        if not constant:
            entries += _varint(count)
    pakt = struct.pack('>qqii', len(packets), valid, pre_skip, remainder) + bytes(entries)
    audio = struct.pack('>I', 0) + b''.join(packets)

    def chunk(kind, body):
        return kind + struct.pack('>q', len(body)) + body
    return (b'caff' + struct.pack('>HH', 1, 0) + chunk(b'desc', desc) + chunk(b'kuki', cookie)
            + chunk(b'pakt', pakt) + chunk(b'data', audio))


def caf_to_ogg(source, target):
    packets, channels, pre_skip, remainder = _read_caf(Path(source).read_bytes())
    Path(target).write_bytes(write_ogg(packets, channels, pre_skip, remainder=remainder))
    return _seconds(packets, pre_skip, remainder)


def ogg_to_caf(source, target):
    packets, channels, pre_skip, remainder = _read_ogg(Path(source).read_bytes())
    Path(target).write_bytes(write_caf(packets, channels, pre_skip, remainder))
    return _seconds(packets, pre_skip, remainder)


def _seconds(packets, pre_skip, remainder):
    return max(0, sum(map(opus_frames, packets)) - pre_skip - remainder) / SAMPLE_RATE


def duration(path):
    """Seconds of playable Opus audio (0 when unknown)."""
    try:
        data = Path(path).read_bytes()
        packets, _, pre_skip, remainder = _read_caf(data) if data[:4] == b'caff' else _read_ogg(data)
        return _seconds(packets, pre_skip, remainder)
    except (OSError, ValueError, struct.error, IndexError):
        return 0

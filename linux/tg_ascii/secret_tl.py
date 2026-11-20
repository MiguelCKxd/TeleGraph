"""End-to-End Encrypted Secret Chats TL schema (Layers 17..144) and MTProto 2.0 crypto.

Self-contained implementation with zero third-party dependencies beyond Telethon's
AES-256-IGE primitive and Python's standard library (hashlib, hmac, secrets, struct).
"""
from dataclasses import dataclass, field
import hashlib
import hmac
import secrets
import struct
from telethon.crypto import AES
from telethon.extensions import BinaryReader
from telethon.tl import TLObject, types

from .calls_crypto import validate_dh

SECRET_LAYER = 144
VECTOR_ID = 0x1CB5C415

# Telegram for Android, EmojiData.emojiSecret. Index order is part of the protocol.
FINGERPRINT_EMOJIS = (
    '😉', '😍', '😛', '😭', '😱', '😡', '😎', '😴', '😵', '😈', '😬', '😇', '😏', '👮', '👷', '💂',
    '👶', '👨', '👩', '👴', '👵', '😻', '😽', '🙀', '👺', '🙈', '🙉', '🙊', '💀', '👽', '💩', '🔥',
    '💥', '💤', '👂', '👀', '👃', '👅', '👄', '👍', '👎', '👌', '👊', '✌', '✋', '👐', '👆', '👇',
    '👉', '👈', '🙏', '👏', '💪', '🚶', '🏃', '💃', '👫', '👪', '👬', '👭', '💅', '🎩', '👑', '👒',
    '👟', '👞', '👠', '👕', '👗', '👖', '👙', '👜', '👓', '🎀', '💄', '💛', '💙', '💜', '💚', '💍',
    '💎', '🐶', '🐺', '🐱', '🐭', '🐹', '🐰', '🐸', '🐯', '🐨', '🐻', '🐷', '🐮', '🐗', '🐴', '🐑',
    '🐘', '🐼', '🐧', '🐥', '🐔', '🐍', '🐢', '🐛', '🐝', '🐜', '🐞', '🐌', '🐙', '🐚', '🐟', '🐬',
    '🐋', '🐐', '🐊', '🐫', '🍀', '🌹', '🌻', '🍁', '🌾', '🍄', '🌵', '🌴', '🌳', '🌞', '🌚', '🌙',
    '🌎', '🌋', '⚡', '☔', '❄', '⛄', '🌀', '🌈', '🌊', '🎓', '🎆', '🎃', '👻', '🎅', '🎄', '🎁',
    '🎈', '🔮', '🎥', '📷', '💿', '💻', '☎', '📡', '📺', '📻', '🔉', '🔔', '⏳', '⏰', '⌚', '🔒',
    '🔑', '🔎', '💡', '🔦', '🔌', '🔋', '🚿', '🚽', '🔧', '🔨', '🚪', '🚬', '💣', '🔫', '🔪', '💊',
    '💉', '💰', '💵', '💳', '✉', '📫', '📦', '📅', '📁', '✂', '📌', '📎', '✒', '✏', '📐', '📚',
    '🔬', '🔭', '🎨', '🎬', '🎤', '🎧', '🎵', '🎹', '🎻', '🎺', '🎸', '👾', '🎮', '🃏', '🎲', '🎯',
    '🏈', '🏀', '⚽', '⚾', '🎾', '🎱', '🏉', '🎳', '🏁', '🏇', '🏆', '🏊', '🏄', '☕', '🍼', '🍺',
    '🍷', '🍴', '🍕', '🍔', '🍟', '🍗', '🍱', '🍚', '🍜', '🍡', '🍳', '🍞', '🍩', '🍦', '🎂', '🍰',
    '🍪', '🍫', '🍭', '🍯', '🍎', '🍏', '🍊', '🍋', '🍒', '🍇', '🍉', '🍓', '🍑', '🍌', '🍐', '🍍',
    '🍆', '🍅', '🌽', '🏡', '🏥', '🏦', '⛪', '🏰', '⛺', '🏭', '🗻', '🗽', '🎠', '🎡', '⛲', '🎢',
    '🚢', '🚤', '⚓', '🚀', '✈', '🚁', '🚂', '🚋', '🚎', '🚌', '🚙', '🚗', '🚕', '🚛', '🚨', '🚔',
    '🚒', '🚑', '🚲', '🚠', '🚜', '🚦', '⚠', '🚧', '⛽', '🎰', '🗿', '🎪', '🎭', '🇯🇵', '🇰🇷', '🇩🇪',
    '🇨🇳', '🇺🇸', '🇫🇷', '🇪🇸', '🇮🇹', '🇷🇺', '🇬🇧', '1⃣', '2⃣', '3⃣', '4⃣', '5⃣', '6⃣', '7⃣', '8⃣', '9⃣',
    '0⃣', '🔟', '❗', '❓', '♥', '♦', '💯', '🔗', '🔱', '🔴', '🔵', '🔶', '🔷',
)


def tl_bytes(data: bytes | str) -> bytes:
    if isinstance(data, str):
        data = data.encode('utf-8')
    return TLObject.serialize_bytes(bytes(data))


def tl_string(value: str) -> bytes:
    return TLObject.serialize_bytes((value or '').encode('utf-8'))


def read_tl_string(reader: BinaryReader) -> str:
    return reader.tgread_bytes().decode('utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Diffie-Hellman validation & MTProto 2.0 Secret Chat KDF
# ---------------------------------------------------------------------------

def validate_dh_public(g_x: bytes, prime: bytes) -> int:
    """Validate g_a / g_b against Telegram's [2^(2048-64), p - 2^(2048-64)] bounds."""
    if not isinstance(g_x, (bytes, bytearray)) or not isinstance(prime, (bytes, bytearray)) or len(prime) != 256:
        raise ValueError('Invalid DH public parameter length')
    if len(g_x) > 256:
        raise ValueError('Invalid DH public parameter length')
    p = int.from_bytes(prime, 'big')
    val = int.from_bytes(g_x, 'big')
    margin = 1 << (2048 - 64)
    if not (1 < val < p - 1 and margin <= val <= p - margin):
        raise ValueError('Unsafe DH public value outside security bounds')
    return val


def generate_dh_pair(g: int, prime: bytes, server_random: bytes = b'') -> tuple[bytes, bytes]:
    """Generate a 2048-bit private exponent `a` and public `g_a = g^a mod p`."""
    validate_dh(g, bytes(prime))
    p = int.from_bytes(prime, 'big')
    while True:
        raw = bytearray(secrets.token_bytes(256))
        if server_random and len(server_random) == 256:
            for i in range(256):
                raw[i] ^= server_random[i]
        a = int.from_bytes(raw, 'big')
        if not (1 < a < p - 1):
            continue
        g_a_int = pow(g, a, p)
        g_a = g_a_int.to_bytes(256, 'big')
        try:
            validate_dh_public(g_a, prime)
            return bytes(raw), g_a
        except ValueError:
            continue


def compute_shared_key(g_other: bytes, private_exp: bytes, prime: bytes) -> tuple[bytes, int]:
    """Compute 256-byte shared secret `key = g_other^a mod p` and 64-bit `key_fingerprint`."""
    validate_dh_public(g_other, prime)
    p = int.from_bytes(prime, 'big')
    a = int.from_bytes(private_exp, 'big')
    other = int.from_bytes(g_other, 'big')
    key_int = pow(other, a, p)
    if not (1 < key_int < p - 1):
        raise ValueError('Invalid shared Diffie-Hellman key')
    key = key_int.to_bytes(256, 'big')
    fp = struct.unpack('<q', hashlib.sha1(key).digest()[-8:])[0]
    return key, fp


FINGERPRINT_GRID_GLYPHS = ('□', '▤', '▦', '■')


def secret_key_hash(key: bytes) -> bytes:
    """Telegram's visual hash of the initial shared key, retained through rekeying."""
    return hashlib.sha1(key).digest()[:16] + hashlib.sha256(key).digest()[:20]


def key_visual_fingerprint(key_hash: bytes) -> dict:
    """Render the saved visual hash like Telegram Android's IdenticonActivity."""
    if len(key_hash) != 36:
        return {'emojis': '', 'hex': '', 'grid': []}
    emojis = []
    for pos in range(16, 36, 4):
        number = int.from_bytes(key_hash[pos:pos + 4], 'big') & 0x7fffffff
        emojis.append(FINGERPRINT_EMOJIS[number % len(FINGERPRINT_EMOJIS)])
    cells = ''.join(FINGERPRINT_GRID_GLYPHS[(byte >> bit) & 3]
                    for byte in key_hash for bit in (0, 2, 4, 6))
    return {
        'emojis': ' '.join(emojis),
        'hex': key_hash[:32].hex(' ').upper(),
        'grid': [cells[i:i + 12] for i in range(0, len(cells), 12)],
    }


def mtproto2_kdf(key: bytes, msg_key: bytes, x: int) -> tuple[bytes, bytes]:
    if len(key) != 256 or len(msg_key) != 16:
        raise ValueError('Invalid key or msg_key length')
    sha256_a = hashlib.sha256(msg_key + key[x:x + 36]).digest()
    sha256_b = hashlib.sha256(key[40 + x:40 + x + 36] + msg_key).digest()
    aes_key = sha256_a[0:8] + sha256_b[8:24] + sha256_a[24:32]
    aes_iv = sha256_b[0:8] + sha256_a[8:24] + sha256_b[24:32]
    return aes_key, aes_iv


def mtproto1_kdf(key: bytes, msg_key: bytes) -> tuple[bytes, bytes]:
    sha1_a = hashlib.sha1(msg_key + key[0:32]).digest()
    sha1_b = hashlib.sha1(key[32:48] + msg_key + key[48:64]).digest()
    sha1_c = hashlib.sha1(key[64:96] + msg_key).digest()
    sha1_d = hashlib.sha1(msg_key + key[96:128]).digest()
    aes_key = sha1_a[0:8] + sha1_b[8:20] + sha1_c[4:16]
    aes_iv = sha1_a[8:20] + sha1_b[0:8] + sha1_c[16:20] + sha1_d[0:8]
    return aes_key, aes_iv


def mtproto2_encrypt(key: bytes, key_fingerprint: int, is_admin: bool, payload: bytes) -> bytes:
    """Encrypt serialized DecryptedMessageLayer bytes with MTProto 2.0."""
    x = 0 if is_admin else 8
    framed = struct.pack('<I', len(payload)) + payload
    pad_len = (16 - (len(framed) % 16)) % 16
    if pad_len < 12:
        pad_len += 16
    pad_len += 16 * secrets.randbelow(16)  # 12..267 bytes of random padding
    padded = framed + secrets.token_bytes(pad_len)
    msg_key_large = hashlib.sha256(key[88 + x:88 + x + 32] + padded).digest()
    msg_key = msg_key_large[8:24]
    aes_key, aes_iv = mtproto2_kdf(key, msg_key, x)
    ciphertext = AES.encrypt_ige(padded, aes_key, aes_iv)
    return struct.pack('<q', key_fingerprint) + msg_key + ciphertext


def decrypt_secret_message(keys_by_fp: dict[int, bytes], is_admin: bool, wire: bytes,
                           *, allow_legacy: bool) -> tuple[int, bytes, int]:
    """Return the verified key fingerprint, inner payload and transport version."""
    if not isinstance(wire, (bytes, bytearray)) or len(wire) < 40 or (len(wire) - 24) % 16 != 0:
        raise ValueError('Invalid encrypted secret message length')
    fp = struct.unpack('<q', wire[:8])[0]
    key = keys_by_fp.get(fp)
    if key is None:
        raise KeyError(f'Unknown secret chat key fingerprint: {fp}')
    msg_key = bytes(wire[8:24])
    ciphertext = bytes(wire[24:])
    x = 8 if is_admin else 0
    aes_key, aes_iv = mtproto2_kdf(key, msg_key, x)
    padded = AES.decrypt_ige(ciphertext, aes_key, aes_iv)
    expected_msg_key = hashlib.sha256(key[88 + x:88 + x + 32] + padded).digest()[8:24]
    if not hmac.compare_digest(msg_key, expected_msg_key):
        if not allow_legacy:
            raise ValueError('Secret chat message msg_key verification failed')
        # Older peers can send MTProto 1 during initial layer negotiation.
        aes_key1, aes_iv1 = mtproto1_kdf(key, msg_key)
        padded1 = AES.decrypt_ige(ciphertext, aes_key1, aes_iv1)
        msg_len1 = struct.unpack('<I', padded1[:4])[0]
        if msg_len1 >= 4 and 0 <= len(padded1) - 4 - msg_len1 <= 15 and hmac.compare_digest(
            msg_key, hashlib.sha1(padded1[:4 + msg_len1]).digest()[-16:]
        ):
            return fp, padded1[4:4 + msg_len1], 1
        raise ValueError('Secret chat message msg_key verification failed')
    msg_len = struct.unpack('<I', padded[:4])[0]
    pad_len = len(padded) - 4 - msg_len
    if msg_len < 4 or pad_len < 12 or pad_len > 1024:
        raise ValueError('Invalid secret chat payload length or padding')
    return fp, padded[4:4 + msg_len], 2


def mtproto2_decrypt(keys_by_fp: dict[int, bytes], is_admin: bool, wire: bytes) -> tuple[int, bytes]:
    fp, payload, _ = decrypt_secret_message(keys_by_fp, is_admin, wire, allow_legacy=False)
    return fp, payload


def file_key_fingerprint(key: bytes, iv: bytes) -> int:
    if len(key) != 32 or len(iv) != 32:
        raise ValueError('File key and IV must be 32 bytes each')
    digest = hashlib.md5(key + iv).digest()
    xored = bytes(a ^ b for a, b in zip(digest[:4], digest[4:8]))
    return struct.unpack('<i', xored)[0]


def encrypt_file_bytes(raw: bytes) -> tuple[bytes, bytes, bytes, int, str]:
    key = secrets.token_bytes(32)
    iv = secrets.token_bytes(32)
    fp = file_key_fingerprint(key, iv)
    rem = len(raw) % 16
    padded = raw + (secrets.token_bytes(16 - rem) if rem else b'')
    encrypted = AES.encrypt_ige(padded, key, iv) if padded else b''
    md5_hex = hashlib.md5(encrypted).hexdigest()
    return encrypted, key, iv, fp, md5_hex


def decrypt_file_bytes(encrypted: bytes, key: bytes, iv: bytes, size: int,
                       expected_fingerprint: int | None = None) -> bytes:
    if expected_fingerprint is not None and file_key_fingerprint(key, iv) != expected_fingerprint:
        raise ValueError('Encrypted file key fingerprint mismatch')
    if not encrypted:
        return b''
    rem = len(encrypted) % 16
    if rem:
        encrypted = encrypted + b'\x00' * (16 - rem)
    decrypted = AES.decrypt_ige(encrypted, bytes(key), bytes(iv))
    return decrypted[:max(0, int(size))]


# ---------------------------------------------------------------------------
# E2E Nested TL Types (Actions, Media, Attributes, Entities)
# ---------------------------------------------------------------------------

@dataclass
class SecretTypingAction:
    kind: str = 'typing'  # typing | cancel | record_voice | upload_voice | record_video | upload_video | upload_photo | upload_document
    progress: int = 0

    _TO_ID = {
        'typing': 0x16BF744E,
        'cancel': 0xFD5EC8F5,
        'record_video': 0xA187D66F,
        'upload_video': 0x92042FF7,
        'record_voice': 0xD52F73F7,
        'upload_voice': 0xE6AC8A6F,
        'upload_photo': 0x990A3C1A,
        'upload_document': 0x8FAEE98E,
        'geo': 0x176F8BA1,
        'contact': 0x628CBC6F,
        'record_round': 0x88F27FBC,
        'upload_round': 0xBB718624,
    }
    _FROM_ID = {v: k for k, v in _TO_ID.items()}
    _WITH_PROGRESS = {0xE9763AEC, 0xF351D7AB, 0xD1D34A26, 0xAA0CD9E4, 0x243E1C66}

    def to_bytes(self) -> bytes:
        cid = self._TO_ID.get(self.kind, 0x16BF744E)
        return struct.pack('<I', cid)

    @classmethod
    def from_reader(cls, reader: BinaryReader) -> 'SecretTypingAction':
        cid = reader.read_int(signed=False)
        if cid in cls._WITH_PROGRESS:
            prog = reader.read_int()
            mapping = {
                0xE9763AEC: 'upload_video',
                0xF351D7AB: 'upload_voice',
                0xD1D34A26: 'upload_photo',
                0xAA0CD9E4: 'upload_document',
                0x243E1C66: 'upload_round',
            }
            return cls(mapping.get(cid, 'typing'), prog)
        return cls(cls._FROM_ID.get(cid, 'typing'))


@dataclass
class SecretDocAttribute:
    kind: str  # filename | image_size | animated | video | audio | sticker
    file_name: str = ''
    w: int = 0
    h: int = 0
    duration: int = 0
    round_message: bool = False
    voice: bool = False
    title: str = ''
    performer: str = ''
    waveform: bytes = b''
    alt: str = ''
    stickerset_short_name: str = ''

    def to_bytes(self, layer: int = SECRET_LAYER) -> bytes:
        if self.kind == 'filename':
            return struct.pack('<I', 0x15590068) + tl_string(self.file_name)
        if self.kind == 'image_size':
            return struct.pack('<Iii', 0x6C37C15C, int(self.w), int(self.h))
        if self.kind == 'animated':
            return struct.pack('<I', 0x11B58939)
        if self.kind == 'video':
            if layer >= 66:
                flags = 1 if self.round_message else 0
                return struct.pack('<IIiii', 0x0EF02CE6, flags, int(self.duration), int(self.w), int(self.h))
            return struct.pack('<Iiii', 0x5910CCCB, int(self.duration), int(self.w), int(self.h))
        if self.kind == 'audio':
            if layer >= 46:
                flags = (1 << 10) if self.voice else 0
                if self.title:
                    flags |= 1 << 0
                if self.performer:
                    flags |= 1 << 1
                if self.waveform:
                    flags |= 1 << 2
                parts = [struct.pack('<IIi', 0x9852F9C6, flags, int(self.duration))]
                if flags & 1:
                    parts.append(tl_string(self.title))
                if flags & 2:
                    parts.append(tl_string(self.performer))
                if flags & 4:
                    parts.append(tl_bytes(self.waveform))
                return b''.join(parts)
            return struct.pack('<Ii', 0xDED218E0, int(self.duration)) + tl_string(self.title) + tl_string(self.performer)
        if self.kind == 'sticker':
            if self.stickerset_short_name:
                ss = struct.pack('<I', 0x861CC8A0) + tl_string(self.stickerset_short_name)
            else:
                ss = struct.pack('<I', 0xFFB62B95)
            return struct.pack('<I', 0x3A556302) + tl_string(self.alt) + ss
        return struct.pack('<I', 0x15590068) + tl_string(self.file_name or 'file')

    @classmethod
    def from_reader(cls, reader: BinaryReader) -> 'SecretDocAttribute':
        cid = reader.read_int(signed=False)
        if cid == 0x15590068:
            return cls('filename', file_name=read_tl_string(reader))
        if cid == 0x6C37C15C:
            return cls('image_size', w=reader.read_int(), h=reader.read_int())
        if cid == 0x11B58939:
            return cls('animated')
        if cid == 0x5910CCCB:
            return cls('video', duration=reader.read_int(), w=reader.read_int(), h=reader.read_int())
        if cid == 0x0EF02CE6:
            flags = reader.read_int(signed=False)
            return cls('video', round_message=bool(flags & 1), duration=reader.read_int(), w=reader.read_int(), h=reader.read_int())
        if cid == 0xDED218E0:
            return cls('audio', duration=reader.read_int(), title=read_tl_string(reader), performer=read_tl_string(reader))
        if cid in (0x9852F9C6, 0x36C9CA7F):
            flags = reader.read_int(signed=False)
            dur = reader.read_int()
            title = read_tl_string(reader) if (flags & 1) else ''
            perf = read_tl_string(reader) if (flags & 2) else ''
            wf = reader.tgread_bytes() if (flags & 4) else b''
            return cls('audio', voice=bool(flags & (1 << 10)), duration=dur, title=title, performer=perf, waveform=wf)
        if cid == 0x3A556302:
            alt = read_tl_string(reader)
            ss_cid = reader.read_int(signed=False)
            short_name = ''
            if ss_cid == 0x861CC8A0:
                short_name = read_tl_string(reader)
            elif ss_cid == 0x9DE7A269:
                reader.read_long()
                reader.read_long()
            return cls('sticker', alt=alt, stickerset_short_name=short_name)
        # Fallback to Telethon main schema reader if peer encoded a cloud DocumentAttribute
        reader.seek(-4)
        obj = reader.tgread_object()
        if isinstance(obj, types.DocumentAttributeFilename):
            return cls('filename', file_name=obj.file_name)
        if isinstance(obj, types.DocumentAttributeAudio):
            return cls('audio', voice=bool(getattr(obj, 'voice', False)), duration=int(getattr(obj, 'duration', 0) or 0),
                       title=getattr(obj, 'title', '') or '', performer=getattr(obj, 'performer', '') or '')
        if isinstance(obj, types.DocumentAttributeVideo):
            return cls('video', round_message=bool(getattr(obj, 'round_message', False)),
                       duration=int(getattr(obj, 'duration', 0) or 0), w=int(obj.w), h=int(obj.h))
        if isinstance(obj, types.DocumentAttributeSticker):
            return cls('sticker', alt=getattr(obj, 'alt', '') or '')
        if isinstance(obj, types.DocumentAttributeImageSize):
            return cls('image_size', w=int(obj.w), h=int(obj.h))
        if isinstance(obj, types.DocumentAttributeAnimated):
            return cls('animated')
        return cls('filename', file_name='')


def encode_entity(entity) -> bytes:
    """Serialize a Telethon MessageEntity for the E2E schema."""
    if isinstance(entity, types.MessageEntityMentionName):
        # E2E layer 45 uses int32 user_id (0x352dca58) or int64 (0xdc7b1140)
        return struct.pack('<Iiiq', 0xDC7B1140, entity.offset, entity.length, entity.user_id)
    return entity._bytes()


def decode_entity(reader: BinaryReader):
    cid = reader.read_int(signed=False)
    if cid == 0x352DCA58:
        offset = reader.read_int()
        length = reader.read_int()
        user_id = reader.read_int()
        return types.MessageEntityMentionName(offset=offset, length=length, user_id=user_id)
    reader.seek(-4)
    return reader.tgread_object()


def skip_photo_size(reader: BinaryReader) -> bytes:
    """Read an E2E PhotoSize (used in DecryptedMessageMediaExternalDocument) and return cached thumb bytes if any."""
    cid = reader.read_int(signed=False)
    if cid == 0x0E17E23C:  # photoSizeEmpty
        read_tl_string(reader)
        return b''
    if cid == 0x77BFB61B:  # E2E photoSize
        read_tl_string(reader)
        loc_cid = reader.read_int(signed=False)
        if loc_cid == 0x53D69076:
            reader.read_int()
            reader.read_long()
            reader.read_int()
            reader.read_long()
        elif loc_cid == 0x7C596B46:
            reader.read_long()
            reader.read_int()
            reader.read_long()
        reader.read_int()
        reader.read_int()
        reader.read_int()
        return b''
    if cid == 0xE9A734FA:  # E2E photoCachedSize
        read_tl_string(reader)
        loc_cid = reader.read_int(signed=False)
        if loc_cid == 0x53D69076:
            reader.read_int()
            reader.read_long()
            reader.read_int()
            reader.read_long()
        elif loc_cid == 0x7C596B46:
            reader.read_long()
            reader.read_int()
            reader.read_long()
        reader.read_int()
        reader.read_int()
        return reader.tgread_bytes()
    reader.seek(-4)
    obj = reader.tgread_object()
    return getattr(obj, 'bytes', b'') or b''


# ---------------------------------------------------------------------------
# DecryptedMessageMedia
# ---------------------------------------------------------------------------

@dataclass
class SecretMediaPayload:
    kind: str = 'empty'  # empty | photo | video | document | audio | external_document | geo | contact | venue | webpage
    thumb: bytes = b''
    thumb_w: int = 0
    thumb_h: int = 0
    w: int = 0
    h: int = 0
    duration: int = 0
    mime_type: str = ''
    size: int = 0
    key: bytes = b''
    iv: bytes = b''
    caption: str = ''
    file_name: str = ''
    attributes: list[SecretDocAttribute] = field(default_factory=list)
    # external_document fields
    doc_id: int = 0
    access_hash: int = 0
    date: int = 0
    dc_id: int = 0
    # geo / venue / contact / webpage
    lat: float = 0.0
    long: float = 0.0
    title: str = ''
    address: str = ''
    provider: str = ''
    venue_id: str = ''
    phone_number: str = ''
    first_name: str = ''
    last_name: str = ''
    user_id: int = 0
    url: str = ''

    def to_bytes(self, layer: int = SECRET_LAYER) -> bytes:
        if self.kind == 'empty':
            return struct.pack('<I', 0x089F5C4A)
        if self.kind == 'photo':
            return b''.join((
                struct.pack('<I', 0xF1FA8D78),
                tl_bytes(self.thumb),
                struct.pack('<iiiii', int(self.thumb_w), int(self.thumb_h), int(self.w), int(self.h), int(self.size)),
                tl_bytes(self.key),
                tl_bytes(self.iv),
                tl_string(self.caption),
            ))
        if self.kind == 'video':
            return b''.join((
                struct.pack('<I', 0x970C8C0E),
                tl_bytes(self.thumb),
                struct.pack('<iii', int(self.thumb_w), int(self.thumb_h), int(self.duration)),
                tl_string(self.mime_type or 'video/mp4'),
                struct.pack('<iii', int(self.w), int(self.h), int(self.size)),
                tl_bytes(self.key),
                tl_bytes(self.iv),
                tl_string(self.caption),
            ))
        if self.kind == 'audio':
            return b''.join((
                struct.pack('<Ii', 0x57E0A9CB, int(self.duration)),
                tl_string(self.mime_type or 'audio/ogg'),
                struct.pack('<i', int(self.size)),
                tl_bytes(self.key),
                tl_bytes(self.iv),
            ))
        if self.kind == 'document':
            attrs = list(self.attributes)
            if self.file_name and not any(a.kind == 'filename' for a in attrs):
                attrs.append(SecretDocAttribute('filename', file_name=self.file_name))
            attr_bytes = struct.pack('<II', VECTOR_ID, len(attrs)) + b''.join(a.to_bytes(layer) for a in attrs)
            if layer >= 143:
                return b''.join((
                    struct.pack('<I', 0x6ABD9782),
                    tl_bytes(self.thumb),
                    struct.pack('<ii', int(self.thumb_w), int(self.thumb_h)),
                    tl_string(self.mime_type or 'application/octet-stream'),
                    struct.pack('<q', int(self.size)),
                    tl_bytes(self.key),
                    tl_bytes(self.iv),
                    attr_bytes,
                    tl_string(self.caption),
                ))
            return b''.join((
                struct.pack('<I', 0x7AFE8AE2),
                tl_bytes(self.thumb),
                struct.pack('<ii', int(self.thumb_w), int(self.thumb_h)),
                tl_string(self.mime_type or 'application/octet-stream'),
                struct.pack('<i', int(self.size)),
                tl_bytes(self.key),
                tl_bytes(self.iv),
                attr_bytes,
                tl_string(self.caption),
            ))
        if self.kind == 'external_document':
            attrs = list(self.attributes)
            attr_bytes = struct.pack('<II', VECTOR_ID, len(attrs)) + b''.join(a.to_bytes(layer) for a in attrs)
            thumb_bytes = struct.pack('<I', 0x0E17E23C) + tl_string('')
            return b''.join((
                struct.pack('<Iqqi', 0xFA95B0DD, int(self.doc_id), int(self.access_hash), int(self.date)),
                tl_string(self.mime_type or 'application/webp'),
                struct.pack('<i', int(self.size)),
                thumb_bytes,
                struct.pack('<i', int(self.dc_id)),
                attr_bytes,
            ))
        if self.kind == 'geo':
            return struct.pack('<Idd', 0x35480A59, float(self.lat), float(self.long))
        if self.kind == 'contact':
            return b''.join((
                struct.pack('<I', 0x588A0A97),
                tl_string(self.phone_number),
                tl_string(self.first_name),
                tl_string(self.last_name),
                struct.pack('<i', int(self.user_id)),
            ))
        if self.kind == 'venue':
            return b''.join((
                struct.pack('<Idd', 0x8A0DF56F, float(self.lat), float(self.long)),
                tl_string(self.title),
                tl_string(self.address),
                tl_string(self.provider),
                tl_string(self.venue_id),
            ))
        if self.kind == 'webpage':
            return struct.pack('<I', 0xE50511D8) + tl_string(self.url)
        return struct.pack('<I', 0x089F5C4A)

    @classmethod
    def from_reader(cls, reader: BinaryReader) -> 'SecretMediaPayload':
        cid = reader.read_int(signed=False)
        if cid == 0x089F5C4A:
            return cls('empty')
        if cid in (0xF1FA8D78, 0x32798A8C):
            thumb = reader.tgread_bytes()
            tw, th, w, h, size = reader.read_int(), reader.read_int(), reader.read_int(), reader.read_int(), reader.read_int()
            key = reader.tgread_bytes()
            iv = reader.tgread_bytes()
            caption = read_tl_string(reader) if cid == 0xF1FA8D78 else ''
            return cls('photo', thumb=thumb, thumb_w=tw, thumb_h=th, w=w, h=h, size=size, key=key, iv=iv, caption=caption, mime_type='image/jpeg')
        if cid in (0x970C8C0E, 0x524A415D, 0x4CEE6EF3):
            thumb = reader.tgread_bytes()
            tw, th, dur = reader.read_int(), reader.read_int(), reader.read_int()
            mime = read_tl_string(reader) if cid != 0x4CEE6EF3 else 'video/mp4'
            w, h, size = reader.read_int(), reader.read_int(), reader.read_int()
            key = reader.tgread_bytes()
            iv = reader.tgread_bytes()
            caption = read_tl_string(reader) if cid == 0x970C8C0E else ''
            return cls('video', thumb=thumb, thumb_w=tw, thumb_h=th, duration=dur, mime_type=mime, w=w, h=h, size=size, key=key, iv=iv, caption=caption)
        if cid in (0x57E0A9CB, 0x6080758F):
            dur = reader.read_int()
            mime = read_tl_string(reader) if cid == 0x57E0A9CB else 'audio/ogg'
            size = reader.read_int()
            key = reader.tgread_bytes()
            iv = reader.tgread_bytes()
            return cls('audio', duration=dur, mime_type=mime, size=size, key=key, iv=iv)
        if cid == 0xB095434B:
            thumb = reader.tgread_bytes()
            tw, th = reader.read_int(), reader.read_int()
            fname = read_tl_string(reader)
            mime = read_tl_string(reader)
            size = reader.read_int()
            key = reader.tgread_bytes()
            iv = reader.tgread_bytes()
            attrs = [SecretDocAttribute('filename', file_name=fname)] if fname else []
            return cls('document', thumb=thumb, thumb_w=tw, thumb_h=th, file_name=fname, mime_type=mime, size=size, key=key, iv=iv, attributes=attrs)
        if cid in (0x7AFE8AE2, 0x6ABD9782):
            thumb = reader.tgread_bytes()
            tw, th = reader.read_int(), reader.read_int()
            mime = read_tl_string(reader)
            size = reader.read_long() if cid == 0x6ABD9782 else reader.read_int()
            key = reader.tgread_bytes()
            iv = reader.tgread_bytes()
            vec_id = reader.read_int(signed=False)
            if vec_id != VECTOR_ID:
                raise ValueError(f'Expected Vector ID in DecryptedMessageMediaDocument, got 0x{vec_id:08x}')
            count = reader.read_int()
            attrs = [SecretDocAttribute.from_reader(reader) for _ in range(max(0, min(count, 64)))]
            caption = read_tl_string(reader)
            fname = next((a.file_name for a in attrs if a.kind == 'filename' and a.file_name), '')
            return cls('document', thumb=thumb, thumb_w=tw, thumb_h=th, file_name=fname, mime_type=mime, size=size, key=key, iv=iv, attributes=attrs, caption=caption)
        if cid == 0xFA95B0DD:
            doc_id = reader.read_long()
            access_hash = reader.read_long()
            date = reader.read_int()
            mime = read_tl_string(reader)
            size = reader.read_int()
            thumb = skip_photo_size(reader)
            dc_id = reader.read_int()
            vec_id = reader.read_int(signed=False)
            if vec_id != VECTOR_ID:
                raise ValueError(f'Expected Vector ID in DecryptedMessageMediaExternalDocument, got 0x{vec_id:08x}')
            count = reader.read_int()
            attrs = [SecretDocAttribute.from_reader(reader) for _ in range(max(0, min(count, 64)))]
            fname = next((a.file_name for a in attrs if a.kind == 'filename' and a.file_name), '')
            return cls('external_document', doc_id=doc_id, access_hash=access_hash, date=date, mime_type=mime, size=size, thumb=thumb, dc_id=dc_id, attributes=attrs, file_name=fname)
        if cid == 0x35480A59:
            return cls('geo', lat=reader.read_double(), long=reader.read_double())
        if cid == 0x588A0A97:
            return cls('contact', phone_number=read_tl_string(reader), first_name=read_tl_string(reader), last_name=read_tl_string(reader), user_id=reader.read_int())
        if cid == 0x8A0DF56F:
            return cls('venue', lat=reader.read_double(), long=reader.read_double(), title=read_tl_string(reader), address=read_tl_string(reader), provider=read_tl_string(reader), venue_id=read_tl_string(reader))
        if cid == 0xE50511D8:
            return cls('webpage', url=read_tl_string(reader))
        raise ValueError(f'Unsupported DecryptedMessageMedia constructor: 0x{cid:08x}')


# ---------------------------------------------------------------------------
# DecryptedMessageAction
# ---------------------------------------------------------------------------

@dataclass
class SecretAction:
    kind: str  # set_ttl | read | delete | screenshot | flush | resend | notify_layer | typing | request_key | accept_key | commit_key | abort_key | noop
    ttl_seconds: int = 0
    random_ids: list[int] = field(default_factory=list)
    start_seq_no: int = 0
    end_seq_no: int = 0
    layer: int = SECRET_LAYER
    typing: SecretTypingAction | None = None
    exchange_id: int = 0
    g_a: bytes = b''
    g_b: bytes = b''
    key_fingerprint: int = 0

    def to_bytes(self) -> bytes:
        if self.kind == 'set_ttl':
            return struct.pack('<Ii', 0xA1733AEC, int(self.ttl_seconds))
        if self.kind == 'read':
            return struct.pack('<III', 0x0C4F40BE, VECTOR_ID, len(self.random_ids)) + b''.join(
                struct.pack('<q', int(rid)) for rid in self.random_ids
            )
        if self.kind == 'delete':
            return struct.pack('<III', 0x65614304, VECTOR_ID, len(self.random_ids)) + b''.join(
                struct.pack('<q', int(rid)) for rid in self.random_ids
            )
        if self.kind == 'screenshot':
            return struct.pack('<III', 0x8AC1F475, VECTOR_ID, len(self.random_ids)) + b''.join(
                struct.pack('<q', int(rid)) for rid in self.random_ids
            )
        if self.kind == 'flush':
            return struct.pack('<I', 0x6719E45C)
        if self.kind == 'resend':
            return struct.pack('<Iii', 0x511110B0, int(self.start_seq_no), int(self.end_seq_no))
        if self.kind == 'notify_layer':
            return struct.pack('<Ii', 0xF3048883, int(self.layer))
        if self.kind == 'typing':
            act = self.typing or SecretTypingAction('typing')
            return struct.pack('<I', 0xCCB27641) + act.to_bytes()
        if self.kind == 'request_key':
            return struct.pack('<Iq', 0xF3C9611B, int(self.exchange_id)) + tl_bytes(self.g_a)
        if self.kind == 'accept_key':
            return struct.pack('<Iq', 0x6FE1735B, int(self.exchange_id)) + tl_bytes(self.g_b) + struct.pack('<q', int(self.key_fingerprint))
        if self.kind == 'commit_key':
            return struct.pack('<Iqq', 0xEC2E0B9B, int(self.exchange_id), int(self.key_fingerprint))
        if self.kind == 'abort_key':
            return struct.pack('<Iq', 0xDD05EC6B, int(self.exchange_id))
        if self.kind == 'noop':
            return struct.pack('<I', 0xA82FDD63)
        raise ValueError(f'Unknown SecretAction kind: {self.kind}')

    @classmethod
    def from_reader(cls, reader: BinaryReader) -> 'SecretAction':
        cid = reader.read_int(signed=False)
        if cid == 0xA1733AEC:
            return cls('set_ttl', ttl_seconds=reader.read_int())
        if cid in (0x0C4F40BE, 0x65614304, 0x8AC1F475):
            vec_id = reader.read_int(signed=False)
            if vec_id != VECTOR_ID:
                raise ValueError(f'Expected Vector<long>, got 0x{vec_id:08x}')
            count = max(0, min(reader.read_int(), 4096))
            rids = [reader.read_long() for _ in range(count)]
            kind = {0x0C4F40BE: 'read', 0x65614304: 'delete', 0x8AC1F475: 'screenshot'}[cid]
            return cls(kind, random_ids=rids)
        if cid == 0x6719E45C:
            return cls('flush')
        if cid == 0x511110B0:
            return cls('resend', start_seq_no=reader.read_int(), end_seq_no=reader.read_int())
        if cid == 0xF3048883:
            return cls('notify_layer', layer=reader.read_int())
        if cid == 0xCCB27641:
            return cls('typing', typing=SecretTypingAction.from_reader(reader))
        if cid == 0xF3C9611B:
            return cls('request_key', exchange_id=reader.read_long(), g_a=reader.tgread_bytes())
        if cid == 0x6FE1735B:
            return cls('accept_key', exchange_id=reader.read_long(), g_b=reader.tgread_bytes(), key_fingerprint=reader.read_long())
        if cid == 0xEC2E0B9B:
            return cls('commit_key', exchange_id=reader.read_long(), key_fingerprint=reader.read_long())
        if cid == 0xDD05EC6B:
            return cls('abort_key', exchange_id=reader.read_long())
        if cid in (0xA82FDD63, 0xB82F752F):
            return cls('noop')
        raise ValueError(f'Unsupported DecryptedMessageAction constructor: 0x{cid:08x}')


# ---------------------------------------------------------------------------
# DecryptedMessage & DecryptedMessageService & DecryptedMessageLayer
# ---------------------------------------------------------------------------

@dataclass
class SecretMessageData:
    random_id: int
    ttl: int = 0
    message: str = ''
    media: SecretMediaPayload | None = None
    entities: list = field(default_factory=list)
    via_bot_name: str = ''
    reply_to_random_id: int | None = None
    grouped_id: int | None = None
    no_webpage: bool = False
    silent: bool = False
    action: SecretAction | None = None  # If set, serializes as DecryptedMessageService

    @property
    def is_service(self) -> bool:
        return self.action is not None

    def to_bytes(self, layer: int = SECRET_LAYER) -> bytes:
        if self.action is not None:
            return struct.pack('<Iq', 0x73164160, int(self.random_id)) + self.action.to_bytes()
        flags = 0
        if self.no_webpage:
            flags |= 1 << 1
        if self.reply_to_random_id is not None:
            flags |= 1 << 3
        if self.silent:
            flags |= 1 << 5
        if self.entities:
            flags |= 1 << 7
        if self.media is not None and self.media.kind != 'empty':
            flags |= 1 << 9
        if self.via_bot_name:
            flags |= 1 << 11
        if self.grouped_id is not None:
            flags |= 1 << 17
        parts = [
            struct.pack('<IIqi', 0x91CC4674, flags, int(self.random_id), int(self.ttl)),
            tl_string(self.message),
        ]
        if flags & (1 << 9):
            parts.append(self.media.to_bytes(layer))
        if flags & (1 << 7):
            parts.append(struct.pack('<II', VECTOR_ID, len(self.entities)))
            parts.extend(encode_entity(e) for e in self.entities)
        if flags & (1 << 11):
            parts.append(tl_string(self.via_bot_name))
        if flags & (1 << 3):
            parts.append(struct.pack('<q', int(self.reply_to_random_id)))
        if flags & (1 << 17):
            parts.append(struct.pack('<q', int(self.grouped_id)))
        return b''.join(parts)

    @classmethod
    def from_reader(cls, reader: BinaryReader) -> 'SecretMessageData':
        cid = reader.read_int(signed=False)
        if cid == 0x73164160:
            rid = reader.read_long()
            return cls(random_id=rid, action=SecretAction.from_reader(reader))
        if cid == 0xAA48327D:
            rid = reader.read_long()
            reader.tgread_bytes()  # random_bytes in Layer 8
            return cls(random_id=rid, action=SecretAction.from_reader(reader))
        if cid == 0x1F814F1F:
            rid = reader.read_long()
            reader.tgread_bytes()
            msg = read_tl_string(reader)
            media = SecretMediaPayload.from_reader(reader)
            return cls(random_id=rid, message=msg, media=None if media.kind == 'empty' else media)
        if cid == 0x204D3878:
            rid = reader.read_long()
            ttl = reader.read_int()
            msg = read_tl_string(reader)
            media = SecretMediaPayload.from_reader(reader)
            return cls(random_id=rid, ttl=ttl, message=msg, media=None if media.kind == 'empty' else media)
        if cid in (0x36B091DE, 0x91CC4674):
            flags = reader.read_int(signed=False)
            rid = reader.read_long()
            ttl = reader.read_int()
            msg = read_tl_string(reader)
            media = SecretMediaPayload.from_reader(reader) if (flags & (1 << 9)) else None
            entities = []
            if flags & (1 << 7):
                vec_id = reader.read_int(signed=False)
                if vec_id != VECTOR_ID:
                    raise ValueError(f'Expected Vector<MessageEntity>, got 0x{vec_id:08x}')
                count = max(0, min(reader.read_int(), 512))
                entities = [decode_entity(reader) for _ in range(count)]
            via_bot = read_tl_string(reader) if (flags & (1 << 11)) else ''
            reply_to = reader.read_long() if (flags & (1 << 3)) else None
            grouped_id = reader.read_long() if (cid == 0x91CC4674 and (flags & (1 << 17))) else None
            return cls(
                random_id=rid,
                ttl=ttl,
                message=msg,
                media=None if (media is None or media.kind == 'empty') else media,
                entities=entities,
                via_bot_name=via_bot,
                reply_to_random_id=reply_to,
                grouped_id=grouped_id,
                no_webpage=bool(flags & (1 << 1)),
                silent=bool(flags & (1 << 5)),
            )
        raise ValueError(f'Unsupported DecryptedMessage constructor: 0x{cid:08x}')


@dataclass
class SecretLayerPacket:
    message: SecretMessageData
    in_seq_no: int = 0
    out_seq_no: int = 0
    layer: int = SECRET_LAYER
    random_bytes: bytes = field(default_factory=lambda: secrets.token_bytes(16 + secrets.randbelow(16)))

    def to_bytes(self) -> bytes:
        rnd = self.random_bytes if len(self.random_bytes) >= 15 else secrets.token_bytes(16)
        return b''.join((
            struct.pack('<I', 0x1BE31789),
            tl_bytes(rnd),
            struct.pack('<iii', int(self.layer), int(self.in_seq_no), int(self.out_seq_no)),
            self.message.to_bytes(self.layer),
        ))

    @classmethod
    def from_bytes(cls, data: bytes) -> 'SecretLayerPacket':
        with BinaryReader(data) as reader:
            cid = reader.read_int(signed=False)
            if cid == 0x1BE31789:
                rnd = reader.tgread_bytes()
                if len(rnd) < 15:
                    raise ValueError('Invalid random_bytes in secret message layer')
                layer = reader.read_int()
                in_seq = reader.read_int()
                out_seq = reader.read_int()
                msg = SecretMessageData.from_reader(reader)
                return cls(message=msg, in_seq_no=in_seq, out_seq_no=out_seq, layer=layer, random_bytes=rnd)
            # Legacy layer-less fallback
            reader.seek(0)
            msg = SecretMessageData.from_reader(reader)
            return cls(message=msg, in_seq_no=0, out_seq_no=0, layer=17, random_bytes=b'')

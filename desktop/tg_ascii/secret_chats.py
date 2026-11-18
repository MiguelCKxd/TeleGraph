"""End-to-End Encrypted Secret Chats manager and encrypted local store (3.0).

Implements:
- DH handshake (messages.getDhConfig, requestEncryption, acceptEncryption, discardEncryption)
- MTProto 2.0 encryption/decryption and Layer 73/144 DecryptedMessageLayer framing
- Monotonic sequence numbers (in_seq_no / out_seq_no) with parity verification and Resend recovery
- Perfect Forward Secrecy (PFS) automatic key rotation every 100 messages or 7 days
  (requestKey / acceptKey / commitKey / abortKey / noop)
- Service actions: notifyLayer, typing, readMessages, deleteMessages, flushHistory,
  setMessageTTL, screenshotMessages
- One-time AES-256-IGE file encryption/decryption with MD5 key fingerprint verification
- At-rest AES-256-IGE + HMAC-SHA256 local storage for chat state, keys, and media
- Automatic self-destruct (TTL) timer after messages are read
"""
import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import struct
import time
import uuid

from telethon import functions as f, types as t, utils
from telethon.crypto import AES

from .i18n import tr
from .secret_tl import (
    SECRET_LAYER,
    SecretAction,
    SecretDocAttribute,
    SecretLayerPacket,
    SecretMediaPayload,
    SecretMessageData,
    SecretTypingAction,
    compute_shared_key,
    decrypt_file_bytes,
    encrypt_file_bytes,
    generate_dh_pair,
    key_visual_fingerprint,
    secret_key_hash,
    decrypt_secret_message,
    mtproto2_encrypt,
    validate_dh_public,
)

log = logging.getLogger(__name__)

SECRET_PEER_OFFSET = -2_000_000_000_000
REKEY_MESSAGE_LIMIT = 100
REKEY_AGE_SECONDS = 7 * 86400
MAX_STORED_SENT_LAYERS = 120

TTL_CHOICES = (
    (0, 'Off'),
    (1, '1s'),
    (5, '5s'),
    (10, '10s'),
    (30, '30s'),
    (60, '1m'),
    (3600, '1h'),
    (86400, '1d'),
    (604800, '1w'),
)


def secret_peer_id(chat_id: int) -> int:
    return SECRET_PEER_OFFSET - abs(int(chat_id))


def is_secret_peer(peer_id) -> bool:
    try:
        return isinstance(peer_id, int) and not isinstance(peer_id, bool) and peer_id < SECRET_PEER_OFFSET
    except Exception:
        return False


def secret_chat_id(peer_id: int) -> int:
    val = int(peer_id)
    if val < SECRET_PEER_OFFSET:
        return abs(val - SECRET_PEER_OFFSET)
    return abs(val)


def format_ttl(seconds: int) -> str:
    seconds = int(seconds or 0)
    if seconds <= 0:
        return tr('Desactivado')
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds // 60}m'
    if seconds < 86400:
        return f'{seconds // 3600}h'
    if seconds < 604800:
        return f'{seconds // 86400}d'
    return f'{seconds // 604800}w'


@dataclass
class SecretMedia:
    """Media descriptor attached to Message.media for secret chat attachments."""
    chat_id: int
    msg_id: int
    random_id: int
    kind: str  # image | video | audio | voice | sticker | file
    file_name: str = ''
    mime_type: str = 'application/octet-stream'
    size: int = 0
    duration: int = 0
    w: int = 0
    h: int = 0
    voice: bool = False
    sticker: bool = False
    local_token: str = ''
    file_id: int = 0
    access_hash: int = 0
    dc_id: int = 0
    key: bytes = b''
    iv: bytes = b''
    key_fingerprint: int = 0
    thumb: bytes = b''
    external: bool = False

    def to_dict(self) -> dict:
        return {
            'chat_id': self.chat_id,
            'msg_id': self.msg_id,
            'random_id': self.random_id,
            'kind': self.kind,
            'file_name': self.file_name,
            'mime_type': self.mime_type,
            'size': self.size,
            'duration': self.duration,
            'w': self.w,
            'h': self.h,
            'voice': self.voice,
            'sticker': self.sticker,
            'local_token': self.local_token,
            'file_id': self.file_id,
            'access_hash': self.access_hash,
            'dc_id': self.dc_id,
            'key': base64.b64encode(self.key).decode('ascii') if self.key else '',
            'iv': base64.b64encode(self.iv).decode('ascii') if self.iv else '',
            'key_fingerprint': self.key_fingerprint,
            'thumb': base64.b64encode(self.thumb).decode('ascii') if self.thumb else '',
            'external': self.external,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'SecretMedia':
        return cls(
            chat_id=int(data.get('chat_id', 0)),
            msg_id=int(data.get('msg_id', 0)),
            random_id=int(data.get('random_id', 0)),
            kind=str(data.get('kind', 'file')),
            file_name=str(data.get('file_name', '')),
            mime_type=str(data.get('mime_type', 'application/octet-stream')),
            size=int(data.get('size', 0)),
            duration=int(data.get('duration', 0)),
            w=int(data.get('w', 0)),
            h=int(data.get('h', 0)),
            voice=bool(data.get('voice', False)),
            sticker=bool(data.get('sticker', False)),
            local_token=str(data.get('local_token', '')),
            file_id=int(data.get('file_id', 0)),
            access_hash=int(data.get('access_hash', 0)),
            dc_id=int(data.get('dc_id', 0)),
            key=base64.b64decode(data['key']) if data.get('key') else b'',
            iv=base64.b64decode(data['iv']) if data.get('iv') else b'',
            key_fingerprint=int(data.get('key_fingerprint', 0)),
            thumb=base64.b64decode(data['thumb']) if data.get('thumb') else b'',
            external=bool(data.get('external', False)),
        )


# ---------------------------------------------------------------------------
# At-rest Encrypted Local Store
# ---------------------------------------------------------------------------

class SecretStore:
    """Encrypts secret chat keys, sequence numbers, messages, and media at rest."""

    MAGIC = b'TGS3'

    def __init__(self, root: Path | None, account: str = 'account', session_salt: bytes = b''):
        self.root = Path(root) if root is not None else None
        self.account = str(account or 'account')
        self._session_salt = bytes(session_salt or b'')
        self._enc_key: bytes | None = None
        self._mac_key: bytes | None = None

    @property
    def base_dir(self) -> Path | None:
        return (self.root / 'secret-chats') if self.root is not None else None

    @property
    def state_path(self) -> Path | None:
        return (self.base_dir / f'{self.account}.bin') if self.base_dir is not None else None

    @property
    def key_path(self) -> Path | None:
        return (self.base_dir / f'{self.account}.key') if self.base_dir is not None else None

    @property
    def files_dir(self) -> Path | None:
        return (self.base_dir / f'{self.account}-files') if self.base_dir is not None else None

    def _ensure_keys(self) -> tuple[bytes, bytes]:
        if self._enc_key is not None and self._mac_key is not None:
            return self._enc_key, self._mac_key
        if self.key_path is None:
            raw = secrets.token_bytes(32)
        else:
            self.base_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(self.base_dir, 0o700)
            except OSError:
                pass
            if self.key_path.exists():
                raw = self.key_path.read_bytes()
                if len(raw) != 32:
                    raw = hashlib.sha256(raw).digest()
            else:
                raw = secrets.token_bytes(32)
                self._atomic_write(self.key_path, raw)
        material = hashlib.sha512(raw + b'|tg-secret-store-v3|' + self._session_salt).digest()
        self._enc_key = material[:32]
        self._mac_key = material[32:64]
        return self._enc_key, self._mac_key

    @staticmethod
    def _atomic_write(path: Path, data: bytes):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def encrypt_blob(self, plaintext: bytes) -> bytes:
        enc_key, mac_key = self._ensure_keys()
        iv = secrets.token_bytes(32)
        framed = struct.pack('<I', len(plaintext)) + plaintext
        rem = len(framed) % 16
        padded = framed + (secrets.token_bytes(16 - rem) if rem else b'')
        ciphertext = AES.encrypt_ige(padded, enc_key, iv)
        body = self.MAGIC + iv + ciphertext
        tag = hmac.new(mac_key, body, hashlib.sha256).digest()
        return body + tag

    def decrypt_blob(self, blob: bytes) -> bytes:
        if len(blob) < 4 + 32 + 16 + 32 or blob[:4] != self.MAGIC:
            raise ValueError('Invalid encrypted secret store header')
        enc_key, mac_key = self._ensure_keys()
        body, tag = blob[:-32], blob[-32:]
        expected = hmac.new(mac_key, body, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError('Secret store authentication tag mismatch')
        iv = body[4:36]
        ciphertext = body[36:]
        if len(ciphertext) % 16 != 0:
            raise ValueError('Invalid secret store ciphertext alignment')
        padded = AES.decrypt_ige(ciphertext, enc_key, iv)
        length = struct.unpack('<I', padded[:4])[0]
        if length > len(padded) - 4:
            raise ValueError('Corrupted secret store payload length')
        return padded[4:4 + length]

    def load_state(self) -> dict:
        if self.state_path is None or not self.state_path.exists():
            return {}
        try:
            raw = self.decrypt_blob(self.state_path.read_bytes())
            data = json.loads(raw.decode('utf-8'))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            log.warning('Could not read secret chat store: %s', type(exc).__name__)
            return {}

    def save_state(self, state: dict):
        if self.state_path is None:
            return
        raw = json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self._atomic_write(self.state_path, self.encrypt_blob(raw))

    def save_file(self, data: bytes, token: str = '') -> str:
        token = token or uuid.uuid4().hex
        if self.files_dir is None:
            return ''
        target = self.files_dir / f'{token}.bin'
        self._atomic_write(target, self.encrypt_blob(data))
        return token

    def load_file(self, token: str) -> bytes | None:
        if not token or self.files_dir is None:
            return None
        target = self.files_dir / f'{token}.bin'
        if not target.exists():
            return None
        try:
            return self.decrypt_blob(target.read_bytes())
        except Exception:
            return None

    def delete_file(self, token: str):
        if not token or self.files_dir is None:
            return
        target = self.files_dir / f'{token}.bin'
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass


def purge(root: Path, account: str):
    """Delete all secret chat keys, state, and encrypted media for a logged-out account."""
    base = Path(root) / 'secret-chats'
    for suffix in ('.bin', '.key'):
        path = base / f'{account}{suffix}'
        try:
            if path.exists():
                # Overwrite key file with random bytes before unlinking
                if suffix == '.key':
                    path.write_bytes(secrets.token_bytes(32))
                path.unlink()
        except OSError:
            pass
    files_dir = base / f'{account}-files'
    if files_dir.exists() and not files_dir.is_symlink():
        shutil.rmtree(files_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Secret Chat Session State
# ---------------------------------------------------------------------------

@dataclass
class SecretChatSession:
    chat_id: int
    access_hash: int = 0
    user_id: int = 0
    user_name: str = ''
    is_admin: bool = True
    state: str = 'waiting'  # requested | waiting | active | discarded
    created_at: float = field(default_factory=time.time)
    layer: int = SECRET_LAYER
    peer_layer: int = 73
    ttl: int = 0
    dh_g: int = 0
    dh_p: bytes = b''
    private_a: bytes = b''
    g_a: bytes = b''
    g_b: bytes = b''
    key: bytes = b''
    key_fingerprint: int = 0
    key_created_at: float = 0.0
    key_use_count: int = 0
    old_keys: dict[int, bytes] = field(default_factory=dict)
    rekey_state: dict | None = None
    in_seq_no: int = 0
    out_seq_no: int = 0
    sent_layers: dict[int, bytes] = field(default_factory=dict)
    pending_in: dict[int, bytes] = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)
    next_msg_id: int = 1
    unread: int = 0
    pinned: bool = False
    archived: bool = False
    muted: bool = False
    visual_hash: bytes = b''
    # First incoming sequence index which must use MTProto 2. Earlier gaps
    # may still contain the peer's original, pre-negotiation messages.
    mtproto2_from: int | None = None
    pending_v2: set[int] = field(default_factory=set)

    @property
    def peer_id(self) -> int:
        return secret_peer_id(self.chat_id)

    @property
    def x_out(self) -> int:
        return 1 if self.is_admin else 0

    @property
    def x_in(self) -> int:
        return 0 if self.is_admin else 1

    def wire_out_seq(self) -> int:
        return 2 * self.out_seq_no + self.x_out

    def wire_in_seq(self) -> int:
        return 2 * self.in_seq_no + self.x_in

    def accept_transport(self, packet: SecretLayerPacket, version: int) -> bool:
        seq = packet.out_seq_no // 2
        if self.mtproto2_from is not None:
            if not packet.random_bytes or (version == 1 and seq >= self.mtproto2_from):
                return False
        if version == 2:
            first_v2 = seq
        else:
            action = packet.message.action
            if packet.layer < 73 and not (action and action.kind == 'notify_layer' and action.layer >= 73):
                return True
            first_v2 = seq + 1
        if self.mtproto2_from is None or first_v2 < self.mtproto2_from:
            self.mtproto2_from = first_v2
            # Earlier arrivals were buffered before we knew the cutover.
            for pending in list(self.pending_in):
                if pending >= first_v2 and pending not in self.pending_v2:
                    del self.pending_in[pending]
        return True

    def keys_by_fingerprint(self) -> dict[int, bytes]:
        result = dict(self.old_keys)
        if self.key and self.key_fingerprint:
            result[self.key_fingerprint] = self.key
        if self.rekey_state and self.rekey_state.get('new_key') and self.rekey_state.get('new_fp'):
            result[int(self.rekey_state['new_fp'])] = bytes(self.rekey_state['new_key'])
        return result

    def to_dict(self) -> dict:
        rekey_serialized = None
        if self.rekey_state:
            rekey_serialized = {
                k: (base64.b64encode(v).decode('ascii') if isinstance(v, (bytes, bytearray)) else v)
                for k, v in self.rekey_state.items()
            }
        return {
            'chat_id': self.chat_id,
            'access_hash': self.access_hash,
            'user_id': self.user_id,
            'user_name': self.user_name,
            'is_admin': self.is_admin,
            'state': self.state,
            'created_at': self.created_at,
            'layer': self.layer,
            'peer_layer': self.peer_layer,
            'ttl': self.ttl,
            'dh_g': self.dh_g,
            'dh_p': base64.b64encode(self.dh_p).decode('ascii') if self.dh_p else '',
            'private_a': base64.b64encode(self.private_a).decode('ascii') if self.private_a else '',
            'g_a': base64.b64encode(self.g_a).decode('ascii') if self.g_a else '',
            'g_b': base64.b64encode(self.g_b).decode('ascii') if self.g_b else '',
            'key': base64.b64encode(self.key).decode('ascii') if self.key else '',
            'key_fingerprint': self.key_fingerprint,
            'key_created_at': self.key_created_at,
            'key_use_count': self.key_use_count,
            'visual_hash': self.visual_hash.hex(),
            'mtproto2_from': self.mtproto2_from,
            'pending_v2': sorted(self.pending_v2),
            'old_keys': {str(fp): base64.b64encode(k).decode('ascii') for fp, k in self.old_keys.items()},
            'rekey_state': rekey_serialized,
            'in_seq_no': self.in_seq_no,
            'out_seq_no': self.out_seq_no,
            'sent_layers': {str(seq): base64.b64encode(raw).decode('ascii') for seq, raw in self.sent_layers.items()},
            'pending_in': {str(seq): base64.b64encode(raw).decode('ascii') for seq, raw in self.pending_in.items()},
            'messages': self.messages,
            'next_msg_id': self.next_msg_id,
            'unread': self.unread,
            'pinned': self.pinned,
            'archived': self.archived,
            'muted': self.muted,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'SecretChatSession':
        rekey = data.get('rekey_state')
        if isinstance(rekey, dict):
            rekey = dict(rekey)
            for bkey in ('a', 'b', 'g_a', 'g_b', 'new_key'):
                if rekey.get(bkey) and isinstance(rekey[bkey], str):
                    rekey[bkey] = base64.b64decode(rekey[bkey])
        else:
            rekey = None
        session = cls(
            chat_id=int(data['chat_id']),
            access_hash=int(data.get('access_hash', 0)),
            user_id=int(data.get('user_id', 0)),
            user_name=str(data.get('user_name', '')),
            is_admin=bool(data.get('is_admin', True)),
            state=str(data.get('state', 'waiting')),
            created_at=float(data.get('created_at', time.time())),
            layer=int(data.get('layer', SECRET_LAYER)),
            peer_layer=int(data.get('peer_layer', 73)),
            ttl=int(data.get('ttl', 0)),
            dh_g=int(data.get('dh_g', 0)),
            dh_p=base64.b64decode(data['dh_p']) if data.get('dh_p') else b'',
            private_a=base64.b64decode(data['private_a']) if data.get('private_a') else b'',
            g_a=base64.b64decode(data['g_a']) if data.get('g_a') else b'',
            g_b=base64.b64decode(data['g_b']) if data.get('g_b') else b'',
            key=base64.b64decode(data['key']) if data.get('key') else b'',
            key_fingerprint=int(data.get('key_fingerprint', 0)),
            key_created_at=float(data.get('key_created_at', 0.0)),
            key_use_count=int(data.get('key_use_count', 0)),
            old_keys={int(fp): base64.b64decode(b64) for fp, b64 in (data.get('old_keys') or {}).items()},
            rekey_state=rekey,
            in_seq_no=int(data.get('in_seq_no', 0)),
            out_seq_no=int(data.get('out_seq_no', 0)),
            sent_layers={int(seq): base64.b64decode(b64) for seq, b64 in (data.get('sent_layers') or {}).items()},
            pending_in={int(seq): base64.b64decode(b64) for seq, b64 in (data.get('pending_in') or {}).items()},
            messages=list(data.get('messages') or []),
            next_msg_id=int(data.get('next_msg_id', 1)),
            unread=int(data.get('unread', 0)),
            pinned=bool(data.get('pinned', False)),
            archived=bool(data.get('archived', False)),
            muted=bool(data.get('muted', False)),
        )
        if 'mtproto2_from' in data:
            cutoff = data['mtproto2_from']
            session.mtproto2_from = None if cutoff is None else max(0, int(cutoff))
            session.pending_v2 = {int(seq) for seq in data.get('pending_v2', ()) if int(seq) in session.pending_in}
        elif session.in_seq_no and session.peer_layer >= 73:
            # Old stores recorded the negotiated layer but not the envelope
            # version of buffered packets. Let sequence-gap recovery request
            # fresh copies instead of delivering unknown versions across it.
            session.mtproto2_from = session.in_seq_no
            session.pending_in.clear()
        if 'visual_hash' in data:
            try:
                saved_hash = bytes.fromhex(data['visual_hash'])
            except (ValueError, TypeError):
                saved_hash = b''
            session.visual_hash = saved_hash if len(saved_hash) == 36 else b''
        elif session.state == 'active' and len(session.key) == 256:
            session.visual_hash = session._legacy_visual_hash()
        return session

    def _legacy_visual_hash(self) -> bytes:
        # Each replacement key appears in the outbound accept or commit.
        # Use the original only when the complete sequence still proves which
        # one it was. Older clients may already have erased it after rotation.
        if self.out_seq_no != len(self.sent_layers) or any(
            2 * n + self.x_out not in self.sent_layers for n in range(self.out_seq_no)
        ):
            return b''
        candidates = dict(self.old_keys)
        candidates[self.key_fingerprint] = self.key
        try:
            for raw in self.sent_layers.values():
                action = SecretLayerPacket.from_bytes(raw).message.action
                if action and action.kind in ('accept_key', 'commit_key'):
                    candidates.pop(action.key_fingerprint, None)
        except Exception:
            # An unreadable old packet must not prevent opening the chat.
            return b''
        if len(candidates) == 1:
            return secret_key_hash(next(iter(candidates.values())))
        return b''


# ---------------------------------------------------------------------------
# SecretChatManager
# ---------------------------------------------------------------------------

class SecretChatManager:
    def __init__(self, backend, root: Path | None = None, account: str = 'account'):
        self.backend = backend
        self.client = backend.client
        session_key = getattr(getattr(getattr(self.client, 'session', None), 'auth_key', None), 'key', b'')
        salt = hashlib.sha256(session_key).digest() if isinstance(session_key, (bytes, bytearray)) and session_key else b''
        self.store = SecretStore(root, account, session_salt=salt)
        self.sessions: dict[int, SecretChatSession] = {}
        self.dh_version: int = 0
        self.dh_g: int = 0
        self.dh_p: bytes = b''
        self._lock = asyncio.Lock()
        self._ttl_task: asyncio.Task | None = None
        self._background_tasks: set[asyncio.Task] = set()
        self._closed = False
        self._load()

    def configure(self, root: Path, account: str):
        session_key = getattr(getattr(getattr(self.client, 'session', None), 'auth_key', None), 'key', b'')
        salt = hashlib.sha256(session_key).digest() if isinstance(session_key, (bytes, bytearray)) and session_key else b''
        self.store = SecretStore(root, account, session_salt=salt)
        self._load()

    def _load(self):
        data = self.store.load_state()
        self.dh_version = int(data.get('dh_version', 0))
        self.dh_g = int(data.get('dh_g', 0))
        self.dh_p = base64.b64decode(data['dh_p']) if data.get('dh_p') else b''
        self.sessions.clear()
        for raw in data.get('sessions', ()):
            try:
                sess = SecretChatSession.from_dict(raw)
                self.sessions[sess.chat_id] = sess
            except Exception as exc:
                log.warning('Skipping damaged secret chat entry: %s', type(exc).__name__)
        self._prune_expired_sync()

    def _save(self):
        if self._closed:
            return
        state = {
            'dh_version': self.dh_version,
            'dh_g': self.dh_g,
            'dh_p': base64.b64encode(self.dh_p).decode('ascii') if self.dh_p else '',
            'sessions': [s.to_dict() for s in self.sessions.values()],
        }
        try:
            self.store.save_state(state)
        except Exception as exc:
            log.warning('Failed to persist secret chat state: %s', type(exc).__name__)

    def _spawn(self, coro):
        if self._closed:
            coro.close()
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return
        task = loop.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def close(self):
        self._closed = True
        if self._ttl_task is not None:
            self._ttl_task.cancel()
            self._ttl_task = None
        if self._background_tasks:
            for task in tuple(self._background_tasks):
                task.cancel()
            await asyncio.gather(*tuple(self._background_tasks), return_exceptions=True)
            self._background_tasks.clear()

    def session_for_peer(self, peer_or_chat_id: int) -> SecretChatSession:
        cid = secret_chat_id(peer_or_chat_id)
        sess = self.sessions.get(cid)
        if sess is None:
            raise ValueError(tr('Este chat secreto ya no existe en este dispositivo.'))
        return sess

    # -- DH Parameters -------------------------------------------------------

    async def _fetch_dh(self) -> tuple[int, bytes, bytes]:
        res = await self.client(f.messages.GetDhConfigRequest(version=self.dh_version, random_length=256))
        if isinstance(res, t.messages.DhConfig):
            from .calls_crypto import validate_dh
            await asyncio.to_thread(validate_dh, res.g, bytes(res.p))
            self.dh_version = int(res.version)
            self.dh_g = int(res.g)
            self.dh_p = bytes(res.p)
            self._save()
        elif not self.dh_p or not self.dh_g:
            res = await self.client(f.messages.GetDhConfigRequest(version=0, random_length=256))
            from .calls_crypto import validate_dh
            await asyncio.to_thread(validate_dh, res.g, bytes(res.p))
            self.dh_version = int(res.version)
            self.dh_g = int(res.g)
            self.dh_p = bytes(res.p)
            self._save()
        return self.dh_g, self.dh_p, bytes(getattr(res, 'random', b''))

    # -- Starting, Accepting & Discarding Secret Chats -----------------------

    async def start_chat(self, user_peer) -> object:
        entity = await self.client.get_entity(user_peer)
        if not isinstance(entity, t.User) or entity.bot or entity.is_self or getattr(entity, 'deleted', False):
            raise ValueError(tr('Los chats secretos solo están disponibles con otras personas.'))
        user_name = utils.get_display_name(entity) or str(entity.id)
        self.backend.cache_name(entity.id, user_name)
        g, p, srv_rand = await self._fetch_dh()
        a_bytes, g_a = await asyncio.to_thread(generate_dh_pair, g, p, srv_rand)
        random_id = secrets.randbits(31) or 1
        while random_id in self.sessions:
            random_id = secrets.randbits(31) or 1
        sess = SecretChatSession(
            chat_id=random_id,
            access_hash=0,
            user_id=int(entity.id),
            user_name=user_name,
            is_admin=True,
            state='waiting',
            dh_g=g,
            dh_p=p,
            private_a=a_bytes,
            g_a=g_a,
        )
        self._append_service_message(
            sess,
            tr('Chat secreto solicitado. Esperando a que {name} se conecte…').format(name=user_name),
            outgoing=True,
        )
        self.sessions[random_id] = sess
        input_user = t.InputUser(entity.id, entity.access_hash)
        try:
            encrypted_chat = await self.client(f.messages.RequestEncryptionRequest(
                user_id=input_user, random_id=random_id, g_a=g_a
            ))
        except Exception:
            self.sessions.pop(random_id, None)
            raise
        chat_id = int(encrypted_chat.id)
        access_hash = int(getattr(encrypted_chat, 'access_hash', 0))
        if chat_id != random_id:
            self.sessions.pop(random_id, None)
            sess.chat_id = chat_id
            self.sessions[chat_id] = sess
        if access_hash:
            sess.access_hash = access_hash
        self._save()
        self._emit_dialogs()
        return self._to_chat_object(sess)

    async def accept_chat(self, peer_or_chat_id: int) -> object:
        sess = self.session_for_peer(peer_or_chat_id)
        if sess.state == 'active':
            return self._to_chat_object(sess)
        if sess.state != 'requested' or not sess.g_a:
            raise ValueError(tr('Este chat secreto no se puede aceptar ahora.'))
        g, p, srv_rand = await self._fetch_dh()
        b_bytes, g_b = await asyncio.to_thread(generate_dh_pair, g, p, srv_rand)
        key, fp = await asyncio.to_thread(compute_shared_key, sess.g_a, b_bytes, p)
        sess.dh_g, sess.dh_p = g, p
        sess.g_b = g_b
        sess.private_a = b''
        sess.key = key
        sess.visual_hash = secret_key_hash(key)
        sess.key_fingerprint = fp
        sess.key_created_at = time.time()
        sess.key_use_count = 0
        sess.state = 'active'
        input_chat = t.InputEncryptedChat(sess.chat_id, sess.access_hash)
        try:
            confirmed = await self.client(f.messages.AcceptEncryptionRequest(
                peer=input_chat, g_b=g_b, key_fingerprint=fp
            ))
        except Exception:
            sess.state = 'requested'
            sess.key = b''
            sess.visual_hash = b''
            sess.key_fingerprint = 0
            raise
        sess.access_hash = int(getattr(confirmed, 'access_hash', sess.access_hash))
        self._append_service_message(
            sess,
            tr('🔒 Chat secreto establecido (cifrado de extremo a extremo).'),
            outgoing=False,
        )
        self._save()
        self._emit_dialogs()
        # Notify supported secret layer immediately
        await self._send_service_action(sess, SecretAction('notify_layer', layer=SECRET_LAYER))
        return self._to_chat_object(sess)

    async def discard(self, peer_or_chat_id: int, delete_history: bool = False):
        chat_id = secret_chat_id(peer_or_chat_id)
        if chat_id not in self.sessions:
            return
        confirmed = await self.client(f.messages.DiscardEncryptionRequest(
            chat_id=chat_id, delete_history=delete_history or None
        ))
        if not confirmed:
            raise ValueError(tr('Could not complete the operation ({error}).').format(error='DiscardEncryption'))
        self._discard_local(chat_id, delete_history, outgoing=True)

    async def _abort(self, chat_id: int):
        # A protocol violation invalidates the local keys even if Telegram
        # cannot be reached to notify the other participant.
        self._discard_local(chat_id, False, outgoing=True)
        try:
            await self.client(f.messages.DiscardEncryptionRequest(chat_id=chat_id))
        except Exception as exc:
            log.warning('Could not notify Telegram of secret chat abort: %s', type(exc).__name__)

    def _discard_local(self, chat_id: int, delete_history: bool, *, outgoing: bool):
        sess = self.sessions.get(chat_id)
        if sess is None or (sess.state == 'discarded' and not delete_history):
            return
        self.store.delete_file(f'draft-{chat_id}')
        self._wipe_session_keys(sess)
        if delete_history:
            for msg in sess.messages:
                meta = msg.get('media')
                if isinstance(meta, dict) and meta.get('local_token'):
                    self.store.delete_file(meta['local_token'])
            self.sessions.pop(chat_id, None)
        else:
            sess.state = 'discarded'
            message = self._append_service_message(sess, tr('Chat secreto cerrado.'), outgoing=outgoing)
            if not outgoing and self.backend.callback:
                self.backend.callback(sess.peer_id, self._record_to_message(sess, message))
        self._save()
        self._emit_dialogs()

    def local_draft(self, peer: int) -> dict:
        chat_id = secret_chat_id(peer)
        session = self.sessions.get(chat_id)
        if session is None or session.state == 'discarded':
            return {}
        blob = self.store.load_file(f'draft-{chat_id}')
        if blob is None:
            return {}
        try:
            record = json.loads(blob)
        except (UnicodeError, ValueError):
            return {}
        return record if isinstance(record, dict) else {}

    def save_local_draft(self, peer: int, record: dict):
        chat_id = secret_chat_id(peer)
        session = self.sessions.get(chat_id)
        if session is None or session.state == 'discarded':
            return
        token = f'draft-{chat_id}'
        if record.get('text') or record.get('reply'):
            # Keep this separate from the conversation log so edits do not
            # rewrite every secret message and its metadata.
            local = {name: record[name] for name in ('text', 'formats', 'custom', 'reply') if name in record}
            self.store.save_file(json.dumps(local, ensure_ascii=False).encode('utf-8'), token)
        else:
            self.store.delete_file(token)

    @staticmethod
    def _wipe_session_keys(sess: SecretChatSession):
        sess.private_a = b''
        sess.key = b''
        sess.visual_hash = b''
        sess.key_fingerprint = 0
        sess.old_keys.clear()
        sess.rekey_state = None
        sess.sent_layers.clear()
        sess.pending_in.clear()
        sess.pending_v2.clear()

    # -- Incoming Updates (UpdateEncryption, UpdateNewEncryptedMessage, etc.) --

    def handle_raw_update(self, update) -> bool:
        if isinstance(update, (t.UpdateEncryption, t.UpdateNewEncryptedMessage,
                              t.UpdateEncryptedChatTyping, t.UpdateEncryptedMessagesRead)):
            self._spawn(self._process_update(update))
            return True
        return False

    async def _process_update(self, update):
        if isinstance(update, t.UpdateEncryption):
            await self._on_encryption_update(update.chat)
        elif isinstance(update, t.UpdateNewEncryptedMessage):
            await self._on_encrypted_message(update.message)
        elif isinstance(update, t.UpdateEncryptedChatTyping):
            sess = self.sessions.get(int(update.chat_id))
            if sess is not None and self.backend.on_change:
                self.backend.on_change('activity', (sess.peer_id, tr('Typing…')))
        elif isinstance(update, t.UpdateEncryptedMessagesRead):
            await self._on_messages_read(int(update.chat_id), getattr(update, 'max_date', None))

    async def _resolve_user_name(self, user_id: int) -> str:
        cached = self.backend.names.get(user_id)
        if cached:
            return cached
        try:
            ent = await self.client.get_entity(user_id)
            name = utils.get_display_name(ent) or str(user_id)
            self.backend.cache_name(user_id, name)
            return name
        except Exception:
            return str(user_id)

    async def _on_encryption_update(self, chat):
        cid = int(chat.id)
        if isinstance(chat, t.EncryptedChatRequested):
            user_id = int(chat.admin_id)
            user_name = await self._resolve_user_name(user_id)
            sess = SecretChatSession(
                chat_id=cid,
                access_hash=int(chat.access_hash),
                user_id=user_id,
                user_name=user_name,
                is_admin=False,
                state='requested',
                g_a=bytes(chat.g_a),
            )
            self.sessions[cid] = sess
            self._save()
            # Automatically complete the DH handshake so the secret chat is ready immediately
            try:
                await self.accept_chat(cid)
            except Exception as exc:
                log.warning('Failed to auto-accept secret chat %s: %s', cid, type(exc).__name__)
                self._emit_dialogs()
        elif isinstance(chat, t.EncryptedChatWaiting):
            sess = self.sessions.get(cid)
            if sess is not None:
                sess.access_hash = int(chat.access_hash)
                self._save()
                self._emit_dialogs()
        elif isinstance(chat, t.EncryptedChat):
            sess = self.sessions.get(cid)
            if sess is None:
                return
            sess.access_hash = int(chat.access_hash)
            if sess.is_admin and sess.state == 'waiting' and sess.private_a:
                try:
                    g_b = bytes(chat.g_a_or_b)
                    key, fp = await asyncio.to_thread(compute_shared_key, g_b, sess.private_a, sess.dh_p)
                    if fp != int(chat.key_fingerprint):
                        raise ValueError('Key fingerprint mismatch in EncryptedChat')
                    sess.g_b = g_b
                    sess.private_a = b''
                    sess.key = key
                    sess.visual_hash = secret_key_hash(key)
                    sess.key_fingerprint = fp
                    sess.key_created_at = time.time()
                    sess.key_use_count = 0
                    sess.state = 'active'
                    msg_dict = self._append_service_message(
                        sess,
                        tr('🔒 {name} se unió al chat secreto.').format(name=sess.user_name),
                        outgoing=False,
                    )
                    self._save()
                    self._emit_dialogs()
                    if self.backend.callback:
                        self.backend.callback(sess.peer_id, self._record_to_message(sess, msg_dict))
                    await self._send_service_action(sess, SecretAction('notify_layer', layer=SECRET_LAYER))
                except Exception as exc:
                    log.warning('Aborted secret chat %s on invalid DH confirmation: %s', cid, type(exc).__name__)
                    await self._abort(cid)
        elif isinstance(chat, t.EncryptedChatDiscarded):
            self._discard_local(cid, bool(getattr(chat, 'history_deleted', False)), outgoing=False)

    async def _on_encrypted_message(self, enc_msg):
        cid = int(enc_msg.chat_id)
        sess = self.sessions.get(cid)
        if sess is None or sess.state != 'active':
            return
        keys = sess.keys_by_fingerprint()
        if not keys:
            return
        try:
            allow_legacy = sess.mtproto2_from is None or sess.in_seq_no < sess.mtproto2_from
            used_fp, payload, version = decrypt_secret_message(keys, sess.is_admin, bytes(enc_msg.bytes),
                                                               allow_legacy=allow_legacy)
            packet = SecretLayerPacket.from_bytes(payload)
        except Exception as exc:
            log.warning('Failed to decrypt secret message in chat %s: %s', cid, type(exc).__name__)
            return
        # Verify sequence number parity when layer wraps sequence numbers
        sequenced = bool(packet.random_bytes)
        if sequenced:
            if (packet.out_seq_no & 1) != sess.x_in or (packet.in_seq_no & 1) != sess.x_out:
                log.warning('Sequence parity violation in secret chat %s; discarding chat', cid)
                await self._abort(cid)
                return
            peer_raw_seq = packet.out_seq_no // 2
            if peer_raw_seq < sess.in_seq_no:
                # Duplicate message already processed
                return
        if not sess.accept_transport(packet, version):
            return
        if sess.rekey_state and sess.rekey_state.get('new_fp') == used_fp and sess.rekey_state.get('new_key'):
            self._activate_new_key(sess)
        if packet.layer >= 17:
            sess.peer_layer = max(sess.peer_layer, int(packet.layer))
        if sequenced:
            if peer_raw_seq > sess.in_seq_no:
                # Gap detected: buffer and request resend
                sess.pending_in[peer_raw_seq] = payload
                if version == 2:
                    sess.pending_v2.add(peer_raw_seq)
                else:
                    sess.pending_v2.discard(peer_raw_seq)
                start_wire = 2 * sess.in_seq_no + sess.x_in
                end_wire = 2 * (peer_raw_seq - 1) + sess.x_in
                self._save()
                await self._send_service_action(
                    sess, SecretAction('resend', start_seq_no=start_wire, end_seq_no=end_wire)
                )
                return
            sess.in_seq_no += 1
        msg_date = getattr(enc_msg, 'date', None) or datetime.now(timezone.utc)
        enc_file = getattr(enc_msg, 'file', None)
        await self._apply_decrypted_packet(sess, packet, msg_date, enc_file)
        # Drain any contiguous buffered packets
        while sess.in_seq_no in sess.pending_in:
            buffered_bytes = sess.pending_in.pop(sess.in_seq_no)
            sess.pending_v2.discard(sess.in_seq_no)
            sess.in_seq_no += 1
            try:
                buffered_pkt = SecretLayerPacket.from_bytes(buffered_bytes)
                await self._apply_decrypted_packet(sess, buffered_pkt, msg_date, None)
            except Exception:
                break
        self._save()

    async def _apply_decrypted_packet(self, sess: SecretChatSession, packet: SecretLayerPacket,
                                      msg_date: datetime, enc_file):
        inner = packet.message
        if inner.action is not None:
            await self._handle_service_action(sess, inner.action, inner.random_id, msg_date)
            return
        # Deduplicate by random_id
        if any(m.get('random_id') == inner.random_id for m in sess.messages):
            return
        msg_id = sess.next_msg_id
        sess.next_msg_id += 1
        reply_id = None
        if inner.reply_to_random_id is not None:
            target = next((m for m in sess.messages if m.get('random_id') == inner.reply_to_random_id), None)
            if target is not None:
                reply_id = target['id']
        media_dict = None
        media_kind = ''
        filename = ''
        size = 0
        text = inner.message or ''
        if inner.media is not None and inner.media.kind != 'empty':
            media_obj = self._build_incoming_media(sess, msg_id, inner.random_id, inner.media, enc_file)
            if media_obj is not None:
                media_dict = media_obj.to_dict()
                media_kind = media_obj.kind
                filename = media_obj.file_name
                size = media_obj.size
                if not text and inner.media.caption:
                    text = inner.media.caption
        entities_serialized = [
            {'_': type(e).__name__, 'offset': e.offset, 'length': e.length,
             'url': getattr(e, 'url', ''), 'document_id': getattr(e, 'document_id', 0),
             'collapsed': bool(getattr(e, 'collapsed', False))}
            for e in (inner.entities or ())
        ]
        stamp = msg_date.astimezone() if msg_date.tzinfo else msg_date.replace(tzinfo=timezone.utc).astimezone()
        ttl = int(inner.ttl or sess.ttl or 0)
        record = {
            'id': msg_id,
            'random_id': int(inner.random_id),
            'sender_id': sess.user_id,
            'sender': sess.user_name or str(sess.user_id),
            'text': text,
            'raw_text': text,
            'time': stamp.strftime('%H:%M'),
            'date': stamp.timestamp(),
            'outgoing': False,
            'read': False,
            'ttl': ttl,
            'expires_at': None,
            'service': False,
            'media_kind': media_kind,
            'filename': filename,
            'size': size,
            'media': media_dict,
            'entities': entities_serialized,
            'reply_to_id': reply_id,
            'reply_to_random_id': inner.reply_to_random_id,
        }
        sess.messages.append(record)
        sess.messages = sess.messages[-500:]
        sess.unread += 1
        self._save()
        msg_obj = self._record_to_message(sess, record)
        if self.backend.callback:
            self.backend.callback(sess.peer_id, msg_obj)
        self._emit_dialogs()

    def _build_incoming_media(self, sess: SecretChatSession, msg_id: int, random_id: int,
                              payload: SecretMediaPayload, enc_file) -> SecretMedia | None:
        file_id = int(getattr(enc_file, 'id', 0) or payload.doc_id or 0)
        access_hash = int(getattr(enc_file, 'access_hash', 0) or payload.access_hash or 0)
        dc_id = int(getattr(enc_file, 'dc_id', 0) or payload.dc_id or 0)
        fp = int(getattr(enc_file, 'key_fingerprint', 0) or 0)
        size = int(payload.size or getattr(enc_file, 'size', 0) or 0)
        is_voice = any(a.kind == 'audio' and a.voice for a in payload.attributes)
        is_sticker = any(a.kind == 'sticker' for a in payload.attributes) or payload.kind == 'external_document'
        if payload.kind == 'photo':
            kind = 'image'
            fname = payload.file_name or 'photo.jpg'
        elif payload.kind == 'video':
            kind = 'video'
            fname = payload.file_name or 'video.mp4'
        elif payload.kind == 'audio':
            kind = 'audio'
            is_voice = True
            fname = payload.file_name or 'voice.ogg'
        elif is_sticker:
            kind = 'sticker'
            fname = payload.file_name or 'sticker.webp'
        elif is_voice:
            kind = 'audio'
            fname = payload.file_name or 'voice.ogg'
        else:
            mime = payload.mime_type or ''
            kind = 'image' if mime.startswith('image/') else 'video' if mime.startswith('video/') else 'audio' if mime.startswith('audio/') else 'file'
            fname = payload.file_name or tr('Archivo cifrado')
        dur = payload.duration or next((a.duration for a in payload.attributes if a.duration), 0)
        return SecretMedia(
            chat_id=sess.chat_id,
            msg_id=msg_id,
            random_id=random_id,
            kind=kind,
            file_name=fname,
            mime_type=payload.mime_type or 'application/octet-stream',
            size=size,
            duration=int(dur),
            w=int(payload.w),
            h=int(payload.h),
            voice=bool(is_voice),
            sticker=bool(is_sticker),
            file_id=file_id,
            access_hash=access_hash,
            dc_id=dc_id,
            key=bytes(payload.key),
            iv=bytes(payload.iv),
            key_fingerprint=fp,
            thumb=bytes(payload.thumb),
            external=(payload.kind == 'external_document'),
        )

    async def _handle_service_action(self, sess: SecretChatSession, action: SecretAction,
                                     random_id: int, msg_date: datetime):
        if action.kind == 'notify_layer':
            sess.peer_layer = max(sess.peer_layer, int(action.layer))
            self._save()
            return
        if action.kind == 'typing':
            status = ''
            if action.typing and action.typing.kind != 'cancel':
                status = tr('Typing…') if action.typing.kind == 'typing' else tr('Sending media…')
            if self.backend.on_change:
                self.backend.on_change('activity', (sess.peer_id, status))
            return
        if action.kind == 'set_ttl':
            sess.ttl = max(0, int(action.ttl_seconds))
            text = (
                tr('{name} desactivó el temporizador de autodestrucción.').format(name=sess.user_name)
                if sess.ttl == 0
                else tr('{name} fijó la autodestrucción en {ttl}.').format(name=sess.user_name, ttl=format_ttl(sess.ttl))
            )
            rec = self._append_service_message(sess, text, outgoing=False, random_id=random_id)
            self._save()
            if self.backend.callback:
                self.backend.callback(sess.peer_id, self._record_to_message(sess, rec))
            if self.backend.on_change:
                self.backend.on_change('secret_chat', sess.peer_id)
            return
        if action.kind == 'read':
            now = time.time()
            rset = set(action.random_ids)
            max_read_id = 0
            for m in sess.messages:
                if m.get('random_id') in rset or (m.get('outgoing') and not m.get('read')):
                    if not rset or m.get('random_id') in rset:
                        m['read'] = True
                        max_read_id = max(max_read_id, m['id'])
                        if m.get('ttl', 0) > 0 and not m.get('expires_at'):
                            m['expires_at'] = now + int(m['ttl'])
            self._save()
            self._schedule_ttl_timer()
            if max_read_id and self.backend.on_change:
                self.backend.on_change('read', (sess.peer_id, max_read_id))
            return
        if action.kind == 'delete':
            rset = set(action.random_ids)
            deleted_ids = []
            kept = []
            for m in sess.messages:
                if m.get('random_id') in rset:
                    deleted_ids.append(m['id'])
                    meta = m.get('media')
                    if isinstance(meta, dict) and meta.get('local_token'):
                        self.store.delete_file(meta['local_token'])
                else:
                    kept.append(m)
            if deleted_ids:
                sess.messages = kept
                self._save()
                if self.backend.on_change:
                    self.backend.on_change('delete', (sess.peer_id, tuple(deleted_ids)))
            return
        if action.kind == 'flush':
            deleted_ids = [m['id'] for m in sess.messages]
            for m in sess.messages:
                meta = m.get('media')
                if isinstance(meta, dict) and meta.get('local_token'):
                    self.store.delete_file(meta['local_token'])
            sess.messages.clear()
            sess.unread = 0
            self._save()
            if deleted_ids and self.backend.on_change:
                self.backend.on_change('delete', (sess.peer_id, tuple(deleted_ids)))
            self._emit_dialogs()
            return
        if action.kind == 'screenshot':
            rec = self._append_service_message(
                sess,
                tr('📸 {name} hizo una captura de pantalla.').format(name=sess.user_name),
                outgoing=False,
                random_id=random_id,
            )
            self._save()
            if self.backend.callback:
                self.backend.callback(sess.peer_id, self._record_to_message(sess, rec))
            return
        if action.kind == 'resend':
            await self._handle_resend_request(sess, action.start_seq_no, action.end_seq_no)
            return
        if action.kind in ('request_key', 'accept_key', 'commit_key', 'abort_key', 'noop'):
            await self._handle_rekey_action(sess, action)

    async def _on_messages_read(self, chat_id: int, max_date):
        sess = self.sessions.get(chat_id)
        if sess is None:
            return
        now = time.time()
        cutoff = max_date.timestamp() if isinstance(max_date, datetime) else now
        max_read_id = 0
        for m in sess.messages:
            if m.get('outgoing') and m.get('date', 0) <= cutoff + 1:
                m['read'] = True
                max_read_id = max(max_read_id, m['id'])
                if m.get('ttl', 0) > 0 and not m.get('expires_at'):
                    m['expires_at'] = now + int(m['ttl'])
        self._save()
        self._schedule_ttl_timer()
        if max_read_id and self.backend.on_change:
            self.backend.on_change('read', (sess.peer_id, max_read_id))

    # -- Perfect Forward Secrecy (PFS Rekeying) ------------------------------

    def _needs_rekey(self, sess: SecretChatSession) -> bool:
        if sess.state != 'active' or sess.rekey_state is not None or not sess.key:
            return False
        if sess.key_use_count >= REKEY_MESSAGE_LIMIT:
            return True
        if sess.key_created_at > 0 and (time.time() - sess.key_created_at) >= REKEY_AGE_SECONDS:
            return True
        return False

    async def request_rekey(self, peer_or_chat_id: int):
        sess = self.session_for_peer(peer_or_chat_id)
        if sess.state != 'active' or sess.rekey_state is not None:
            return
        g, p, srv_rand = await self._fetch_dh()
        sess.dh_g, sess.dh_p = g, p
        a_bytes, g_a = await asyncio.to_thread(generate_dh_pair, g, p, srv_rand)
        exchange_id = secrets.randbits(62) or 1
        sess.rekey_state = {
            'exchange_id': exchange_id,
            'role': 'initiator',
            'a': a_bytes,
            'g_a': g_a,
        }
        self._save()
        await self._send_service_action(
            sess, SecretAction('request_key', exchange_id=exchange_id, g_a=g_a), check_rekey=False
        )

    def _activate_new_key(self, sess: SecretChatSession):
        if not sess.rekey_state or not sess.rekey_state.get('new_key'):
            return
        if sess.key and sess.key_fingerprint:
            sess.old_keys[sess.key_fingerprint] = sess.key
            while len(sess.old_keys) > 4:
                sess.old_keys.pop(next(iter(sess.old_keys)))
        sess.key = bytes(sess.rekey_state['new_key'])
        sess.key_fingerprint = int(sess.rekey_state['new_fp'])
        sess.key_created_at = time.time()
        sess.key_use_count = 0
        sess.rekey_state = None
        self._save()

    async def _handle_rekey_action(self, sess: SecretChatSession, action: SecretAction):
        if action.kind == 'request_key':
            if sess.rekey_state is not None:
                our_id = int(sess.rekey_state.get('exchange_id', 0))
                if our_id > action.exchange_id:
                    return  # Peer will abort its lower exchange_id
                if our_id == action.exchange_id:
                    sess.rekey_state = None
                    await self._send_service_action(
                        sess, SecretAction('abort_key', exchange_id=action.exchange_id), check_rekey=False
                    )
                    return
                sess.rekey_state = None
            g, p, srv_rand = await self._fetch_dh()
            b_bytes, g_b = await asyncio.to_thread(generate_dh_pair, g, p, srv_rand)
            new_key, new_fp = await asyncio.to_thread(compute_shared_key, action.g_a, b_bytes, p)
            sess.rekey_state = {
                'exchange_id': action.exchange_id,
                'role': 'responder',
                'new_key': new_key,
                'new_fp': new_fp,
            }
            self._save()
            await self._send_service_action(
                sess,
                SecretAction('accept_key', exchange_id=action.exchange_id, g_b=g_b, key_fingerprint=new_fp),
                check_rekey=False,
            )
        elif action.kind == 'accept_key':
            if not sess.rekey_state or sess.rekey_state.get('exchange_id') != action.exchange_id:
                await self._send_service_action(
                    sess, SecretAction('abort_key', exchange_id=action.exchange_id), check_rekey=False
                )
                return
            try:
                p = sess.dh_p or (await self._fetch_dh())[1]
                new_key, new_fp = await asyncio.to_thread(
                    compute_shared_key, action.g_b, sess.rekey_state['a'], p
                )
                if new_fp != action.key_fingerprint:
                    raise ValueError('Rekey fingerprint mismatch')
                sess.rekey_state['new_key'] = new_key
                sess.rekey_state['new_fp'] = new_fp
                self._activate_new_key(sess)
                await self._send_service_action(
                    sess,
                    SecretAction('commit_key', exchange_id=action.exchange_id, key_fingerprint=new_fp),
                    check_rekey=False,
                )
                await self._send_service_action(sess, SecretAction('noop'), check_rekey=False)
            except Exception:
                sess.rekey_state = None
                self._save()
                await self._send_service_action(
                    sess, SecretAction('abort_key', exchange_id=action.exchange_id), check_rekey=False
                )
        elif action.kind == 'commit_key':
            if (not sess.rekey_state or sess.rekey_state.get('exchange_id') != action.exchange_id
                    or sess.rekey_state.get('new_fp') != action.key_fingerprint):
                sess.rekey_state = None
                self._save()
                await self._send_service_action(
                    sess, SecretAction('abort_key', exchange_id=action.exchange_id), check_rekey=False
                )
                return
            self._activate_new_key(sess)
            await self._send_service_action(sess, SecretAction('noop'), check_rekey=False)
        elif action.kind == 'abort_key':
            if sess.rekey_state and sess.rekey_state.get('exchange_id') == action.exchange_id:
                sess.rekey_state = None
                self._save()
        elif action.kind == 'noop':
            # Peer confirmed new key is active; old keys can be safely retired
            sess.old_keys.clear()
            self._save()

    async def _handle_resend_request(self, sess: SecretChatSession, start_seq: int, end_seq: int):
        if start_seq < 0 or end_seq < start_seq or (end_seq - start_seq) > 200:
            return
        input_chat = t.InputEncryptedChat(sess.chat_id, sess.access_hash)
        for wire_seq in range(start_seq, end_seq + 1, 2):
            layer_bytes = sess.sent_layers.get(wire_seq)
            if not layer_bytes:
                # Send a Noop wrapped in that sequence number so peer is not stuck
                noop_msg = SecretMessageData(random_id=secrets.randbits(63) or 1, action=SecretAction('noop'))
                pkt = SecretLayerPacket(
                    message=noop_msg, in_seq_no=sess.wire_in_seq(), out_seq_no=wire_seq, layer=SECRET_LAYER
                )
                layer_bytes = pkt.to_bytes()
            encrypted = mtproto2_encrypt(sess.key, sess.key_fingerprint, sess.is_admin, layer_bytes)
            try:
                await self.client(f.messages.SendEncryptedServiceRequest(
                    peer=input_chat, random_id=secrets.randbits(63) or 1, data=encrypted
                ))
            except Exception:
                break

    # -- Sending Encrypted Messages, Media & Service Actions -----------------

    def _pack_layer(self, sess: SecretChatSession, msg_data: SecretMessageData) -> tuple[int, bytes, bytes]:
        wire_in = sess.wire_in_seq()
        wire_out = sess.wire_out_seq()
        sess.out_seq_no += 1
        if msg_data.action is None or msg_data.action.kind not in ('request_key', 'accept_key', 'commit_key', 'abort_key', 'noop'):
            sess.key_use_count += 1
        pkt = SecretLayerPacket(
            message=msg_data,
            in_seq_no=wire_in,
            out_seq_no=wire_out,
            layer=min(SECRET_LAYER, max(73, sess.peer_layer)),
        )
        layer_bytes = pkt.to_bytes()
        sess.sent_layers[wire_out] = layer_bytes
        while len(sess.sent_layers) > MAX_STORED_SENT_LAYERS:
            sess.sent_layers.pop(next(iter(sess.sent_layers)))
        encrypted = mtproto2_encrypt(sess.key, sess.key_fingerprint, sess.is_admin, layer_bytes)
        return wire_out, layer_bytes, encrypted

    async def _send_service_action(self, sess: SecretChatSession, action: SecretAction,
                                   check_rekey: bool = True):
        if sess.state != 'active' or not sess.key:
            return
        random_id = secrets.randbits(63) or 1
        msg_data = SecretMessageData(random_id=random_id, action=action)
        _, _, encrypted = self._pack_layer(sess, msg_data)
        self._save()
        input_chat = t.InputEncryptedChat(sess.chat_id, sess.access_hash)
        try:
            await self.client(f.messages.SendEncryptedServiceRequest(
                peer=input_chat, random_id=random_id, data=encrypted
            ))
        except Exception as exc:
            log.warning('Failed to send secret service action %s: %s', action.kind, type(exc).__name__)
        if check_rekey and self._needs_rekey(sess):
            self._spawn(self.request_rekey(sess.chat_id))

    async def send_text(self, peer_or_chat_id: int, text: str) -> object:
        return await self.send_formatted(peer_or_chat_id, text, (), ())

    async def send_formatted(self, peer_or_chat_id: int, text: str, spans=(), emojis=(),
                             path=None, progress=None, reply_to=None, as_photo=False,
                             silent=False, schedule=None) -> object:
        if path is not None:
            return await self.send_file(
                peer_or_chat_id, path, progress=progress, caption=text,
                spans=spans, emojis=emojis, reply_to=reply_to, as_photo=as_photo, silent=silent
            )
        sess = self.session_for_peer(peer_or_chat_id)
        if sess.state != 'active' or not sess.key:
            raise ValueError(tr('El chat secreto aún no está activo. Espera a que la otra persona se conecte.'))
        from .message_tools import formatted_entities
        from .emoji_usage import note
        entities = formatted_entities(text, spans, emojis) if (spans or emojis) else []
        note(self.backend, emojis, text)
        reply_random_id = None
        if reply_to is not None:
            target = next((m for m in sess.messages if m['id'] == reply_to), None)
            if target is not None:
                reply_random_id = target.get('random_id')
        random_id = secrets.randbits(63) or 1
        msg_data = SecretMessageData(
            random_id=random_id,
            ttl=sess.ttl,
            message=text,
            entities=entities,
            reply_to_random_id=reply_random_id,
            silent=bool(silent),
        )
        _, _, encrypted = self._pack_layer(sess, msg_data)
        input_chat = t.InputEncryptedChat(sess.chat_id, sess.access_hash)
        sent = await self.client(f.messages.SendEncryptedRequest(
            peer=input_chat, random_id=random_id, data=encrypted, silent=True if silent else None
        ))
        sent_date = getattr(sent, 'date', None) or datetime.now(timezone.utc)
        stamp = sent_date.astimezone() if sent_date.tzinfo else sent_date.replace(tzinfo=timezone.utc).astimezone()
        msg_id = sess.next_msg_id
        sess.next_msg_id += 1
        entities_serialized = [
            {'_': type(e).__name__, 'offset': e.offset, 'length': e.length,
             'url': getattr(e, 'url', ''), 'document_id': getattr(e, 'document_id', 0),
             'collapsed': bool(getattr(e, 'collapsed', False))}
            for e in entities
        ]
        record = {
            'id': msg_id,
            'random_id': random_id,
            'sender_id': getattr(self.backend.account_profile, 'user_id', None),
            'sender': tr('Tu'),
            'text': text,
            'raw_text': text,
            'time': stamp.strftime('%H:%M'),
            'date': stamp.timestamp(),
            'outgoing': True,
            'read': False,
            'ttl': sess.ttl,
            'expires_at': None,
            'service': False,
            'media_kind': '',
            'filename': '',
            'size': 0,
            'media': None,
            'entities': entities_serialized,
            'reply_to_id': reply_to,
            'reply_to_random_id': reply_random_id,
        }
        sess.messages.append(record)
        sess.messages = sess.messages[-500:]
        self._save()
        if self._needs_rekey(sess):
            self._spawn(self.request_rekey(sess.chat_id))
        self._emit_dialogs()
        return self._record_to_message(sess, record)

    async def send_file(self, peer_or_chat_id: int, path, progress=None, caption: str = '',
                        spans=(), emojis=(), voice: bool = False, duration: float = 0,
                        reply_to=None, as_photo: bool = False, silent: bool = False,
                        grouped_id: int | None = None) -> object:
        from .backend import attachment_path
        sess = self.session_for_peer(peer_or_chat_id)
        if sess.state != 'active' or not sess.key:
            raise ValueError(tr('El chat secreto aún no está activo. Espera a que la otra persona se conecte.'))
        file_path = attachment_path(path)
        raw_bytes = await asyncio.to_thread(file_path.read_bytes)
        size = len(raw_bytes)
        encrypted_bytes, key, iv, fp, md5_hex = await asyncio.to_thread(encrypt_file_bytes, raw_bytes)
        local_token = await asyncio.to_thread(self.store.save_file, raw_bytes)
        mime, _ = mimetypes.guess_type(file_path.name)
        mime = 'audio/ogg' if voice else (mime or 'application/octet-stream')
        uploaded = await self.client.upload_file(
            encrypted_bytes, file_name=file_path.name, progress_callback=progress
        )
        if isinstance(uploaded, t.InputFileBig):
            input_enc_file = t.InputEncryptedFileBigUploaded(
                id=uploaded.id, parts=uploaded.parts, key_fingerprint=fp
            )
        else:
            input_enc_file = t.InputEncryptedFileUploaded(
                id=uploaded.id, parts=uploaded.parts, md5_checksum=md5_hex, key_fingerprint=fp
            )
        w, h, thumb_bytes, tw, th = 0, 0, b'', 0, 0
        if as_photo or mime.startswith('image/'):
            try:
                from PIL import Image
                import io
                with Image.open(io.BytesIO(raw_bytes)) as img:
                    w, h = img.size
                    thumb_img = img.copy()
                    thumb_img.thumbnail((90, 90))
                    tw, th = thumb_img.size
                    buf = io.BytesIO()
                    thumb_img.convert('RGB').save(buf, format='JPEG', quality=65)
                    thumb_bytes = buf.getvalue()
            except Exception:
                pass
        if voice:
            media_payload = SecretMediaPayload(
                kind='document',
                mime_type='audio/ogg',
                size=size,
                key=key,
                iv=iv,
                file_name=file_path.name,
                caption=caption,
                attributes=[
                    SecretDocAttribute('audio', voice=True, duration=max(1, round(duration or 1))),
                    SecretDocAttribute('filename', file_name=file_path.name),
                ],
            )
            media_kind = 'audio'
        elif as_photo and w and h:
            media_payload = SecretMediaPayload(
                kind='photo',
                thumb=thumb_bytes,
                thumb_w=tw,
                thumb_h=th,
                w=w,
                h=h,
                size=size,
                key=key,
                iv=iv,
                caption=caption,
                file_name=file_path.name,
                mime_type=mime,
            )
            media_kind = 'image'
        else:
            attrs = [SecretDocAttribute('filename', file_name=file_path.name)]
            if w and h:
                attrs.append(SecretDocAttribute('image_size', w=w, h=h))
            media_payload = SecretMediaPayload(
                kind='document',
                thumb=thumb_bytes,
                thumb_w=tw,
                thumb_h=th,
                mime_type=mime,
                size=size,
                key=key,
                iv=iv,
                file_name=file_path.name,
                attributes=attrs,
                caption=caption,
            )
            media_kind = 'image' if mime.startswith('image/') else 'video' if mime.startswith('video/') else 'audio' if mime.startswith('audio/') else 'file'
        from .message_tools import formatted_entities
        entities = formatted_entities(caption, spans, emojis) if (caption and (spans or emojis)) else []
        reply_random_id = None
        if reply_to is not None:
            target = next((m for m in sess.messages if m['id'] == reply_to), None)
            if target is not None:
                reply_random_id = target.get('random_id')
        random_id = secrets.randbits(63) or 1
        msg_data = SecretMessageData(
            random_id=random_id,
            ttl=sess.ttl,
            message=caption,
            media=media_payload,
            entities=entities,
            reply_to_random_id=reply_random_id,
            grouped_id=grouped_id,
            silent=bool(silent),
        )
        _, _, encrypted_msg = self._pack_layer(sess, msg_data)
        input_chat = t.InputEncryptedChat(sess.chat_id, sess.access_hash)
        sent = await self.client(f.messages.SendEncryptedFileRequest(
            peer=input_chat,
            random_id=random_id,
            data=encrypted_msg,
            file=input_enc_file,
            silent=True if silent else None,
        ))
        sent_file = getattr(sent, 'file', None)
        sent_date = getattr(sent, 'date', None) or datetime.now(timezone.utc)
        stamp = sent_date.astimezone() if sent_date.tzinfo else sent_date.replace(tzinfo=timezone.utc).astimezone()
        msg_id = sess.next_msg_id
        sess.next_msg_id += 1
        media_obj = SecretMedia(
            chat_id=sess.chat_id,
            msg_id=msg_id,
            random_id=random_id,
            kind=media_kind,
            file_name=file_path.name,
            mime_type=mime,
            size=size,
            duration=max(1, round(duration)) if voice else 0,
            w=w,
            h=h,
            voice=bool(voice),
            local_token=local_token,
            file_id=int(getattr(sent_file, 'id', 0) or 0),
            access_hash=int(getattr(sent_file, 'access_hash', 0) or 0),
            dc_id=int(getattr(sent_file, 'dc_id', 0) or 0),
            key=key,
            iv=iv,
            key_fingerprint=fp,
            thumb=thumb_bytes,
        )
        entities_serialized = [
            {'_': type(e).__name__, 'offset': e.offset, 'length': e.length,
             'url': getattr(e, 'url', ''), 'document_id': getattr(e, 'document_id', 0),
             'collapsed': bool(getattr(e, 'collapsed', False))}
            for e in entities
        ]
        record = {
            'id': msg_id,
            'random_id': random_id,
            'sender_id': getattr(self.backend.account_profile, 'user_id', None),
            'sender': tr('Tu'),
            'text': caption,
            'raw_text': caption,
            'time': stamp.strftime('%H:%M'),
            'date': stamp.timestamp(),
            'outgoing': True,
            'read': False,
            'ttl': sess.ttl,
            'expires_at': None,
            'service': False,
            'media_kind': media_kind,
            'filename': file_path.name,
            'size': size,
            'media': media_obj.to_dict(),
            'entities': entities_serialized,
            'reply_to_id': reply_to,
            'reply_to_random_id': reply_random_id,
        }
        sess.messages.append(record)
        sess.messages = sess.messages[-500:]
        self._save()
        if self._needs_rekey(sess):
            self._spawn(self.request_rekey(sess.chat_id))
        self._emit_dialogs()
        return self._record_to_message(sess, record)

    async def send_sticker(self, peer_or_chat_id: int, document, reply_to=None) -> object:
        sess = self.session_for_peer(peer_or_chat_id)
        if sess.state != 'active' or not sess.key:
            raise ValueError(tr('El chat secreto aún no está activo.'))
        alt = '◈'
        short_name = ''
        for attr in getattr(document, 'attributes', ()):
            if isinstance(attr, t.DocumentAttributeSticker):
                alt = getattr(attr, 'alt', '') or '◈'
                ss = getattr(attr, 'stickerset', None)
                short_name = getattr(ss, 'short_name', '') or ''
        attrs = [SecretDocAttribute('sticker', alt=alt, stickerset_short_name=short_name)]
        doc_date = getattr(document, 'date', None)
        ts = int(doc_date.timestamp()) if isinstance(doc_date, datetime) else int(time.time())
        media_payload = SecretMediaPayload(
            kind='external_document',
            doc_id=int(document.id),
            access_hash=int(document.access_hash),
            date=ts,
            mime_type=getattr(document, 'mime_type', 'image/webp') or 'image/webp',
            size=int(getattr(document, 'size', 0) or 0),
            dc_id=int(getattr(document, 'dc_id', 1) or 1),
            attributes=attrs,
        )
        reply_random_id = None
        if reply_to is not None:
            target = next((m for m in sess.messages if m['id'] == reply_to), None)
            if target is not None:
                reply_random_id = target.get('random_id')
        random_id = secrets.randbits(63) or 1
        msg_data = SecretMessageData(
            random_id=random_id,
            ttl=sess.ttl,
            message='',
            media=media_payload,
            reply_to_random_id=reply_random_id,
        )
        _, _, encrypted = self._pack_layer(sess, msg_data)
        input_chat = t.InputEncryptedChat(sess.chat_id, sess.access_hash)
        sent = await self.client(f.messages.SendEncryptedRequest(
            peer=input_chat, random_id=random_id, data=encrypted
        ))
        sent_date = getattr(sent, 'date', None) or datetime.now(timezone.utc)
        stamp = sent_date.astimezone() if sent_date.tzinfo else sent_date.replace(tzinfo=timezone.utc).astimezone()
        msg_id = sess.next_msg_id
        sess.next_msg_id += 1
        media_obj = SecretMedia(
            chat_id=sess.chat_id,
            msg_id=msg_id,
            random_id=random_id,
            kind='sticker',
            file_name='sticker.webp',
            mime_type=media_payload.mime_type,
            size=media_payload.size,
            sticker=True,
            file_id=media_payload.doc_id,
            access_hash=media_payload.access_hash,
            dc_id=media_payload.dc_id,
            external=True,
        )
        record = {
            'id': msg_id,
            'random_id': random_id,
            'sender_id': getattr(self.backend.account_profile, 'user_id', None),
            'sender': tr('Tu'),
            'text': alt,
            'raw_text': '',
            'time': stamp.strftime('%H:%M'),
            'date': stamp.timestamp(),
            'outgoing': True,
            'read': False,
            'ttl': sess.ttl,
            'expires_at': None,
            'service': False,
            'media_kind': 'sticker',
            'filename': 'sticker.webp',
            'size': media_payload.size,
            'media': media_obj.to_dict(),
            'entities': [],
            'reply_to_id': reply_to,
            'reply_to_random_id': reply_random_id,
        }
        sess.messages.append(record)
        sess.messages = sess.messages[-500:]
        self._save()
        return self._record_to_message(sess, record)

    async def download_media(self, media: SecretMedia, destination, progress=None, thumbnail: bool = False) -> str | None:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if thumbnail and media.thumb:
            await asyncio.to_thread(target.write_bytes, media.thumb)
            return str(target)
        if media.local_token:
            cached = await asyncio.to_thread(self.store.load_file, media.local_token)
            if cached is not None:
                await asyncio.to_thread(target.write_bytes, cached)
                return str(target)
        if media.external and media.file_id and media.access_hash:
            loc = t.InputDocumentFileLocation(
                id=media.file_id, access_hash=media.access_hash, file_reference=b'', thumb_size=''
            )
            data = await self.client.download_file(loc, file=bytes, progress_callback=progress)
            if data:
                await asyncio.to_thread(target.write_bytes, data)
                return str(target)
            return None
        if not media.file_id or not media.access_hash or not media.key or not media.iv:
            if media.thumb:
                await asyncio.to_thread(target.write_bytes, media.thumb)
                return str(target)
            return None
        loc = t.InputEncryptedFileLocation(id=media.file_id, access_hash=media.access_hash)
        encrypted_bytes = await self.client.download_file(loc, file=bytes, progress_callback=progress)
        decrypted = await asyncio.to_thread(
            decrypt_file_bytes, encrypted_bytes, media.key, media.iv, media.size, media.key_fingerprint or None
        )
        token = await asyncio.to_thread(self.store.save_file, decrypted, media.local_token)
        if token and not media.local_token:
            media.local_token = token
            sess = self.sessions.get(media.chat_id)
            if sess is not None:
                for m in sess.messages:
                    if m['id'] == media.msg_id and isinstance(m.get('media'), dict):
                        m['media']['local_token'] = token
                self._save()
        await asyncio.to_thread(target.write_bytes, decrypted)
        return str(target)

    # -- Chat & History Queries ----------------------------------------------

    async def set_ttl(self, peer_or_chat_id: int, seconds: int) -> dict:
        sess = self.session_for_peer(peer_or_chat_id)
        sess.ttl = max(0, int(seconds))
        text = (
            tr('Desactivaste el temporizador de autodestrucción.')
            if sess.ttl == 0
            else tr('Fijaste la autodestrucción en {ttl}.').format(ttl=format_ttl(sess.ttl))
        )
        rec = self._append_service_message(sess, text, outgoing=True)
        self._save()
        if sess.state == 'active':
            await self._send_service_action(sess, SecretAction('set_ttl', ttl_seconds=sess.ttl))
        if self.backend.callback:
            self.backend.callback(sess.peer_id, self._record_to_message(sess, rec))
        if self.backend.on_change:
            self.backend.on_change('secret_chat', sess.peer_id)
        return self.chat_info(sess.peer_id)

    async def notify_screenshot(self, peer_or_chat_id: int):
        sess = self.session_for_peer(peer_or_chat_id)
        rids = [m['random_id'] for m in sess.messages[-5:] if m.get('random_id')]
        rec = self._append_service_message(sess, tr('📸 Hiciste una captura de pantalla.'), outgoing=True)
        self._save()
        if sess.state == 'active':
            await self._send_service_action(sess, SecretAction('screenshot', random_ids=rids))
        if self.backend.callback:
            self.backend.callback(sess.peer_id, self._record_to_message(sess, rec))

    async def mark_read(self, peer_or_chat_id: int, max_id: int | None = None):
        sess = self.sessions.get(secret_chat_id(peer_or_chat_id))
        if sess is None:
            return
        now = time.time()
        unread_rids = []
        for m in sess.messages:
            if not m.get('outgoing') and not m.get('read') and (max_id is None or m['id'] <= max_id):
                m['read'] = True
                if m.get('random_id') and not m.get('service'):
                    unread_rids.append(m['random_id'])
                if m.get('ttl', 0) > 0 and not m.get('expires_at'):
                    m['expires_at'] = now + int(m['ttl'])
        sess.unread = sum(1 for m in sess.messages if not m.get('outgoing') and not m.get('read'))
        self._save()
        self._schedule_ttl_timer()
        if sess.state == 'active':
            try:
                input_chat = t.InputEncryptedChat(sess.chat_id, sess.access_hash)
                await self.client(f.messages.ReadEncryptedHistoryRequest(
                    peer=input_chat, max_date=datetime.now(timezone.utc)
                ))
            except Exception:
                pass
            if unread_rids:
                await self._send_service_action(sess, SecretAction('read', random_ids=unread_rids))

    async def set_typing(self, peer_or_chat_id: int, active: bool = True):
        sess = self.sessions.get(secret_chat_id(peer_or_chat_id))
        if sess is None or sess.state != 'active':
            return
        try:
            input_chat = t.InputEncryptedChat(sess.chat_id, sess.access_hash)
            await self.client(f.messages.SetEncryptedTypingRequest(peer=input_chat, typing=bool(active)))
        except Exception:
            pass

    async def delete_messages(self, peer_or_chat_id: int, ids: list[int]):
        sess = self.session_for_peer(peer_or_chat_id)
        target_ids = set(int(i) for i in ids)
        rids = []
        kept = []
        deleted = []
        for m in sess.messages:
            if m['id'] in target_ids:
                deleted.append(m['id'])
                if m.get('random_id'):
                    rids.append(m['random_id'])
                meta = m.get('media')
                if isinstance(meta, dict) and meta.get('local_token'):
                    self.store.delete_file(meta['local_token'])
            else:
                kept.append(m)
        sess.messages = kept
        self._save()
        if rids and sess.state == 'active':
            await self._send_service_action(sess, SecretAction('delete', random_ids=rids))
        if deleted and self.backend.on_change:
            self.backend.on_change('delete', (sess.peer_id, tuple(deleted)))

    async def flush_history(self, peer_or_chat_id: int) -> int:
        sess = self.session_for_peer(peer_or_chat_id)
        max_id = sess.messages[-1]['id'] if sess.messages else 0
        deleted = [m['id'] for m in sess.messages]
        for m in sess.messages:
            meta = m.get('media')
            if isinstance(meta, dict) and meta.get('local_token'):
                self.store.delete_file(meta['local_token'])
        sess.messages.clear()
        sess.unread = 0
        self._save()
        if sess.state == 'active':
            await self._send_service_action(sess, SecretAction('flush'))
        if deleted and self.backend.on_change:
            self.backend.on_change('delete', (sess.peer_id, tuple(deleted)))
        self._emit_dialogs()
        return max_id

    def chats(self) -> list:
        self._prune_expired_sync()
        result = []
        for sess in sorted(
            self.sessions.values(),
            key=lambda s: (s.messages[-1]['date'] if s.messages else s.created_at),
            reverse=True,
        ):
            result.append(self._to_chat_object(sess))
        return result

    def history(self, peer_or_chat_id: int) -> list:
        self._prune_expired_sync()
        sess = self.session_for_peer(peer_or_chat_id)
        return [self._record_to_message(sess, r) for r in sess.messages[-80:]]

    def older_messages(self, peer_or_chat_id: int, before: int) -> list:
        self._prune_expired_sync()
        sess = self.session_for_peer(peer_or_chat_id)
        older = [r for r in sess.messages if r['id'] < int(before)]
        return [self._record_to_message(sess, r) for r in older[-60:]]

    def message_context(self, peer_or_chat_id: int, ident: int) -> list:
        self._prune_expired_sync()
        sess = self.session_for_peer(peer_or_chat_id)
        idx = next((i for i, r in enumerate(sess.messages) if r['id'] == int(ident)), None)
        if idx is None:
            raise ValueError(tr('This message is no longer available in this chat.'))
        window = sess.messages[max(0, idx - 30):idx + 31]
        return [self._record_to_message(sess, r) for r in window]

    def reply_contexts(self, peer_or_chat_id: int, ids) -> dict:
        sess = self.sessions.get(secret_chat_id(peer_or_chat_id))
        if sess is None:
            return {}
        wanted = set(int(i) for i in ids)
        return {
            r['id']: self._record_to_message(sess, r)
            for r in sess.messages if r['id'] in wanted
        }

    def search_messages(self, peer_or_chat_id: int, query: str = '', kind: str = 'all', offset: int = 0) -> list:
        self._prune_expired_sync()
        sess = self.session_for_peer(peer_or_chat_id)
        q = (query or '').strip().lower()
        results = []
        for r in reversed(sess.messages):
            if offset and r['id'] >= int(offset):
                continue
            mk = r.get('media_kind', '')
            if kind == 'photos' and mk != 'image':
                continue
            if kind == 'files' and mk != 'file':
                continue
            if kind in ('audio', 'voice') and mk != 'audio':
                continue
            if kind == 'links' and 'http' not in (r.get('text') or '').lower():
                continue
            if q and q not in (r.get('text') or '').lower() and q not in (r.get('filename') or '').lower():
                continue
            results.append(self._record_to_message(sess, r))
            if len(results) >= 50:
                break
        return results

    def chat_header(self, peer_or_chat_id: int) -> dict:
        sess = self.session_for_peer(peer_or_chat_id)
        vis = key_visual_fingerprint(sess.visual_hash)
        state_labels = {
            'requested': tr('Solicitud de chat secreto'),
            'waiting': tr('Esperando conexión…'),
            'active': tr('Cifrado de extremo a extremo'),
            'discarded': tr('Chat secreto cerrado'),
        }
        status = '🔒 ' + state_labels.get(sess.state, tr('Cifrado de extremo a extremo'))
        if sess.ttl > 0:
            status += f' · ⏱ {format_ttl(sess.ttl)}'
        if vis['emojis']:
            status += f" · {vis['emojis']}"
        return {
            'name': f'🔒 {sess.user_name or sess.user_id}',
            'status': status,
            'activity_entity': None,
            'emoji': None,
            'commands': [],
            'mini': False,
            'secret': self.chat_info(sess.peer_id),
        }

    def chat_info(self, peer_or_chat_id: int) -> dict:
        sess = self.session_for_peer(peer_or_chat_id)
        vis = key_visual_fingerprint(sess.visual_hash)
        return {
            'chat_id': sess.chat_id,
            'peer_id': sess.peer_id,
            'user_id': sess.user_id,
            'user_name': sess.user_name,
            'is_admin': sess.is_admin,
            'state': sess.state,
            'ttl': sess.ttl,
            'ttl_label': format_ttl(sess.ttl),
            'layer': max(sess.layer, sess.peer_layer),
            'peer_layer': sess.peer_layer,
            'key_fingerprint': f'{sess.key_fingerprint & 0xFFFFFFFFFFFFFFFF:016X}' if sess.key_fingerprint else '',
            'emojis': vis['emojis'],
            'hex': vis['hex'],
            'grid': vis['grid'],
            'in_seq_no': sess.in_seq_no,
            'out_seq_no': sess.out_seq_no,
            'key_use_count': sess.key_use_count,
        }

    # -- TTL Self-Destruct Timer ---------------------------------------------

    def _prune_expired_sync(self) -> list[tuple[int, list[int]]]:
        now = time.time()
        expired_events = []
        changed = False
        for sess in self.sessions.values():
            kept = []
            deleted_ids = []
            for m in sess.messages:
                exp = m.get('expires_at')
                if exp is not None and exp <= now:
                    deleted_ids.append(m['id'])
                    meta = m.get('media')
                    if isinstance(meta, dict) and meta.get('local_token'):
                        self.store.delete_file(meta['local_token'])
                else:
                    kept.append(m)
            if deleted_ids:
                sess.messages = kept
                changed = True
                expired_events.append((sess.peer_id, deleted_ids))
        if changed:
            self._save()
        return expired_events

    def _schedule_ttl_timer(self):
        if self._closed:
            return
        earliest = None
        for sess in self.sessions.values():
            for m in sess.messages:
                exp = m.get('expires_at')
                if exp is not None and (earliest is None or exp < earliest):
                    earliest = exp
        if self._ttl_task is not None:
            self._ttl_task.cancel()
            self._ttl_task = None
        if earliest is None:
            return
        delay = max(0.1, earliest - time.time() + 0.05)

        async def waiter():
            await asyncio.sleep(delay)
            events = self._prune_expired_sync()
            for peer_id, ids in events:
                if self.backend.on_change:
                    self.backend.on_change('delete', (peer_id, tuple(ids)))
            if events:
                self._emit_dialogs()
            self._schedule_ttl_timer()

        try:
            loop = asyncio.get_running_loop()
            self._ttl_task = loop.create_task(waiter())
        except RuntimeError:
            pass

    # -- Conversions to Backend Dataclasses ----------------------------------

    def _append_service_message(self, sess: SecretChatSession, text: str,
                                outgoing: bool = False, random_id: int | None = None) -> dict:
        now = datetime.now().astimezone()
        msg_id = sess.next_msg_id
        sess.next_msg_id += 1
        record = {
            'id': msg_id,
            'random_id': int(random_id if random_id is not None else (secrets.randbits(63) or 1)),
            'sender_id': getattr(self.backend.account_profile, 'user_id', None) if outgoing else sess.user_id,
            'sender': tr('Tu') if outgoing else (sess.user_name or str(sess.user_id)),
            'text': text,
            'raw_text': text,
            'time': now.strftime('%H:%M'),
            'date': now.timestamp(),
            'outgoing': outgoing,
            'read': True,
            'ttl': 0,
            'expires_at': None,
            'service': True,
            'media_kind': '',
            'filename': '',
            'size': 0,
            'media': None,
            'entities': [],
            'reply_to_id': None,
            'reply_to_random_id': None,
        }
        sess.messages.append(record)
        sess.messages = sess.messages[-500:]
        return record

    def _to_chat_object(self, sess: SecretChatSession):
        from .backend import Chat
        title = f'🔒 {sess.user_name or sess.user_id}'
        return Chat(
            id=sess.peer_id,
            name=title,
            unread=sess.unread,
            pinned=sess.pinned,
            kind='secret',
            contact=True,
            archived=sess.archived,
            muted=sess.muted,
            emoji_status_id=None,
            unread_mark=False,
            member=sess.state == 'active',
            entity=None,
        )

    def _record_to_message(self, sess: SecretChatSession, record: dict):
        from .backend import Message
        media_obj = SecretMedia.from_dict(record['media']) if isinstance(record.get('media'), dict) else None
        raw_text = record.get('raw_text') or record.get('text') or ''
        display_text = raw_text
        if media_obj is not None and media_obj.kind != 'sticker':
            detail = tr('[Archivo] ') + (media_obj.file_name or tr('Archivo adjunto')) + (
                f' ({media_obj.size:,} bytes)' if media_obj.size else ''
            )
            display_text = detail + ('\n' + raw_text if raw_text else '')
        ttl = int(record.get('ttl') or 0)
        if ttl > 0 and not record.get('service'):
            display_text = (display_text + f' [⏱ {format_ttl(ttl)}]').strip()
        entities = []
        custom_emojis = []
        raw_utf16 = None
        for ent in record.get('entities') or ():
            ename = ent.get('_')
            off, length = int(ent.get('offset', 0)), int(ent.get('length', 0))
            cls = getattr(t, ename, None)
            if cls is t.MessageEntityCustomEmoji:
                doc_id = int(ent.get('document_id', 0))
                entities.append(t.MessageEntityCustomEmoji(off, length, doc_id))
                if raw_utf16 is None:
                    raw_utf16 = raw_text.encode('utf-16-le')
                try:
                    alt = raw_utf16[off * 2:(off + length) * 2].decode('utf-16-le')
                    custom_emojis.append((doc_id, alt))
                except UnicodeDecodeError:
                    pass
            elif cls is t.MessageEntityTextUrl:
                entities.append(t.MessageEntityTextUrl(off, length, str(ent.get('url', ''))))
            elif cls is t.MessageEntityBlockquote:
                entities.append(t.MessageEntityBlockquote(off, length, collapsed=bool(ent.get('collapsed', False))))
            elif cls is not None:
                try:
                    entities.append(cls(off, length))
                except Exception:
                    pass
        msg_dt = datetime.fromtimestamp(float(record.get('date', time.time())), tz=timezone.utc).astimezone()
        return Message(
            id=int(record['id']),
            sender=str(record.get('sender') or sess.user_name or ''),
            text=display_text or tr('[Mensaje cifrado]'),
            time=str(record.get('time') or msg_dt.strftime('%H:%M')),
            outgoing=bool(record.get('outgoing', False)),
            media=media_obj,
            media_kind=str(record.get('media_kind') or ''),
            filename=str(record.get('filename') or ''),
            size=int(record.get('size') or 0),
            custom_emojis=tuple(custom_emojis),
            raw_text=raw_text,
            entities=tuple(entities),
            reply_to_id=record.get('reply_to_id'),
            read=bool(record.get('read', False)),
            reactions=(),
            sender_id=record.get('sender_id'),
            date=msg_dt,
            protected=True,  # Secret chat messages cannot be forwarded to cloud chats
            service=bool(record.get('service', False)),
        )

    def _emit_dialogs(self):
        if self.backend.on_change:
            self.backend.on_change('dialogs', None)

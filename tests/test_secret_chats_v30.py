"""End-to-End Encrypted Secret Chats (MTProto 2.0, Layer 73/144, PFS, TTL, encrypted store) tests (3.0)."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from telethon import functions as f, types as t

from tg_ascii.backend import DemoBackend, TelegramBackend
from tg_ascii.chat_capabilities import capabilities_for, chat_capabilities
from tg_ascii.secret_chats import (
    REKEY_AGE_SECONDS,
    REKEY_MESSAGE_LIMIT,
    SECRET_PEER_OFFSET,
    SecretChatManager,
    SecretChatSession,
    SecretMedia,
    SecretStore,
    format_ttl,
    is_secret_peer,
    purge,
    secret_chat_id,
    secret_peer_id,
)
from tg_ascii.secret_tl import (
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
    file_key_fingerprint,
    generate_dh_pair,
    key_visual_fingerprint,
    secret_key_hash,
    mtproto1_kdf,
    mtproto2_decrypt,
    mtproto2_encrypt,
    mtproto2_kdf,
    validate_dh_public,
)


# Standard 2048-bit MODP safe prime for fast, deterministic tests
_TEST_DH_P = int(
    'FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1'
    '29024E088A67CC74020BBEA63B139B22514A08798E3404DD'
    'EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245'
    'E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED'
    'EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D'
    'C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F'
    '83655D23DCA3AD961C62F356208552BB9ED529077096966D'
    '670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B'
    'E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9'
    'DE2BCBF6955817183995497CEA956AE515D2261898FA0510'
    '15728E5A8AACAA68FFFFFFFFFFFFFFFF',
    16,
).to_bytes(256, 'big')
_TEST_DH_G = 2


class FakeSecretWire:
    """In-memory Telegram relay connecting two SecretChatManager instances (Alice & Bob)."""

    def __init__(self):
        self.clients: dict[int, 'FakeSecretClient'] = {}
        self.files: dict[int, bytes] = {}
        self.access_hashes: dict[int, int] = {}

    def register(self, user_id: int, first_name: str) -> 'FakeSecretClient':
        client = FakeSecretClient(self, user_id, first_name)
        self.clients[user_id] = client
        return client


class FakeSecretClient:
    def __init__(self, wire: FakeSecretWire, user_id: int, first_name: str):
        self.wire = wire
        self.user_id = user_id
        self.first_name = first_name
        self.session = NS(auth_key=NS(key=secrets.token_bytes(256)))
        self.handlers = []
        self.manager: SecretChatManager | None = None
        self.sent_service_actions = []

    def add_event_handler(self, callback, event=None):
        self.handlers.append((callback, event))

    async def get_entity(self, peer):
        uid = int(getattr(peer, 'user_id', peer))
        other = self.wire.clients.get(uid)
        name = other.first_name if other else f'User {uid}'
        return t.User(id=uid, is_self=(uid == self.user_id), first_name=name, access_hash=uid * 111)

    async def get_input_entity(self, peer):
        uid = int(getattr(peer, 'user_id', peer))
        return t.InputPeerUser(uid, uid * 111)

    async def upload_file(self, data: bytes, file_name: str = 'file.bin', progress_callback=None):
        fid = secrets.randbits(62) or 1
        self.wire.files[fid] = bytes(data)
        if progress_callback:
            progress_callback(len(data), len(data))
        return t.InputFile(id=fid, parts=1, name=file_name, md5_checksum='')

    async def download_file(self, location, file=bytes, progress_callback=None):
        fid = int(location.id)
        raw = self.wire.files.get(fid, b'')
        if progress_callback:
            progress_callback(len(raw), len(raw))
        return raw

    async def __call__(self, request):
        if isinstance(request, f.messages.GetDhConfigRequest):
            return t.messages.DhConfig(
                g=_TEST_DH_G,
                p=_TEST_DH_P,
                version=1,
                random=secrets.token_bytes(256),
            )
        if isinstance(request, f.messages.RequestEncryptionRequest):
            chat_id = int(request.random_id)
            ah = secrets.randbits(62) or 1
            self.wire.access_hashes[chat_id] = ah
            target_uid = int(request.user_id.user_id)
            other = self.wire.clients[target_uid]
            # Deliver EncryptedChatRequested to responder
            req_chat = t.EncryptedChatRequested(
                id=chat_id,
                access_hash=ah,
                date=datetime.now(timezone.utc),
                admin_id=self.user_id,
                participant_id=target_uid,
                g_a=request.g_a,
            )
            await other.manager._process_update(t.UpdateEncryption(chat=req_chat, date=datetime.now(timezone.utc)))
            return t.EncryptedChatWaiting(
                id=chat_id,
                access_hash=ah,
                date=datetime.now(timezone.utc),
                admin_id=self.user_id,
                participant_id=target_uid,
            )
        if isinstance(request, f.messages.AcceptEncryptionRequest):
            chat_id = int(request.peer.chat_id)
            ah = self.wire.access_hashes.get(chat_id, int(request.peer.access_hash))
            sess = self.manager.sessions[chat_id]
            admin_client = self.wire.clients[sess.user_id]
            confirmed = t.EncryptedChat(
                id=chat_id,
                access_hash=ah,
                date=datetime.now(timezone.utc),
                admin_id=sess.user_id,
                participant_id=self.user_id,
                g_a_or_b=request.g_b,
                key_fingerprint=request.key_fingerprint,
            )
            await admin_client.manager._process_update(
                t.UpdateEncryption(chat=confirmed, date=datetime.now(timezone.utc))
            )
            return confirmed
        if isinstance(request, f.messages.DiscardEncryptionRequest):
            chat_id = int(request.chat_id)
            for uid, cl in self.wire.clients.items():
                if uid != self.user_id and cl.manager and chat_id in cl.manager.sessions:
                    disc = t.EncryptedChatDiscarded(
                        id=chat_id, history_deleted=bool(request.delete_history)
                    )
                    await cl.manager._process_update(
                        t.UpdateEncryption(chat=disc, date=datetime.now(timezone.utc))
                    )
            return True
        if isinstance(request, f.messages.SendEncryptedServiceRequest):
            chat_id = int(request.peer.chat_id)
            sess = self.manager.sessions[chat_id]
            other = self.wire.clients[sess.user_id]
            enc_msg = t.EncryptedMessageService(
                random_id=request.random_id,
                chat_id=chat_id,
                date=datetime.now(timezone.utc),
                bytes=request.data,
            )
            await other.manager._process_update(t.UpdateNewEncryptedMessage(message=enc_msg, qts=1))
            return t.messages.SentEncryptedMessage(date=datetime.now(timezone.utc))
        if isinstance(request, f.messages.SendEncryptedRequest):
            chat_id = int(request.peer.chat_id)
            sess = self.manager.sessions[chat_id]
            other = self.wire.clients[sess.user_id]
            enc_msg = t.EncryptedMessage(
                random_id=request.random_id,
                chat_id=chat_id,
                date=datetime.now(timezone.utc),
                bytes=request.data,
                file=t.EncryptedFileEmpty(),
            )
            await other.manager._process_update(t.UpdateNewEncryptedMessage(message=enc_msg, qts=1))
            return t.messages.SentEncryptedMessage(date=datetime.now(timezone.utc))
        if isinstance(request, f.messages.SendEncryptedFileRequest):
            chat_id = int(request.peer.chat_id)
            sess = self.manager.sessions[chat_id]
            other = self.wire.clients[sess.user_id]
            fid = int(request.file.id)
            raw = self.wire.files.get(fid, b'')
            enc_file = t.EncryptedFile(
                id=fid,
                access_hash=fid ^ 0x12345678,
                size=len(raw),
                dc_id=2,
                key_fingerprint=int(request.file.key_fingerprint),
            )
            enc_msg = t.EncryptedMessage(
                random_id=request.random_id,
                chat_id=chat_id,
                date=datetime.now(timezone.utc),
                bytes=request.data,
                file=enc_file,
            )
            await other.manager._process_update(t.UpdateNewEncryptedMessage(message=enc_msg, qts=1))
            return t.messages.SentEncryptedFile(date=datetime.now(timezone.utc), file=enc_file)
        if isinstance(request, f.messages.ReadEncryptedHistoryRequest):
            chat_id = int(request.peer.chat_id)
            sess = self.manager.sessions[chat_id]
            other = self.wire.clients[sess.user_id]
            await other.manager._process_update(
                t.UpdateEncryptedMessagesRead(chat_id=chat_id, max_date=request.max_date, date=datetime.now(timezone.utc))
            )
            return True
        if isinstance(request, f.messages.SetEncryptedTypingRequest):
            chat_id = int(request.peer.chat_id)
            sess = self.manager.sessions[chat_id]
            other = self.wire.clients[sess.user_id]
            if request.typing:
                await other.manager._process_update(t.UpdateEncryptedChatTyping(chat_id=chat_id))
            return True
        return True


class SecretTLAndCryptoTests(unittest.TestCase):
    def test_dh_key_exchange_and_visual_fingerprint(self):
        a_priv, g_a = generate_dh_pair(_TEST_DH_G, _TEST_DH_P, secrets.token_bytes(256))
        b_priv, g_b = generate_dh_pair(_TEST_DH_G, _TEST_DH_P, secrets.token_bytes(256))
        validate_dh_public(g_a, _TEST_DH_P)
        validate_dh_public(g_b, _TEST_DH_P)

        key_a, fp_a = compute_shared_key(g_b, a_priv, _TEST_DH_P)
        key_b, fp_b = compute_shared_key(g_a, b_priv, _TEST_DH_P)
        self.assertEqual(key_a, key_b)
        self.assertEqual(fp_a, fp_b)

        vis = key_visual_fingerprint(secret_key_hash(key_a))
        self.assertEqual(len(vis['emojis'].split()), 5)
        self.assertEqual(len(vis['hex'].split()), 32)
        self.assertEqual(len(vis['grid']), 12)
        self.assertTrue(all(len(row) == 12 for row in vis['grid']))

    def test_android_visual_key_reference(self):
        # Independently generated with the Android IdenticonActivity and
        # IdenticonDrawable algorithms and EmojiData.emojiSecret.
        vis = key_visual_fingerprint(secret_key_hash(bytes(range(256))))
        self.assertEqual(vis['hex'],
                         '49 16 D6 BD B7 F7 8E 68 03 69 8C AB 32 D1 58 6E '
                         '40 AF F2 E9 D2 D8 92 2E 47 AF D4 64 8E 69 67 49')
        self.assertEqual(vis['emojis'], '🔧 🍕 🐭 🐚 🍓')
        self.assertEqual(vis['grid'][0], '▤▦□▤▦▤▤□▦▤▤■')
        self.assertEqual(vis['grid'][-1], '□▦▤▤□▦■▤■■▤▤')

    def test_legacy_visual_hash_migration(self):
        initial, rotated = bytes(range(256)), bytes(reversed(range(256)))
        session = SecretChatSession(chat_id=7, key=initial, key_fingerprint=11, state='active')

        def legacy():
            record = session.to_dict()
            del record['visual_hash']
            return SecretChatSession.from_dict(record).visual_hash

        expected = secret_key_hash(initial)
        self.assertEqual(legacy(), expected)
        session.key = rotated
        session.key_fingerprint = 22
        session.old_keys[11] = initial
        session.sent_layers[1] = SecretLayerPacket(
            message=SecretMessageData(random_id=123, action=SecretAction('commit_key', exchange_id=5, key_fingerprint=22)),
            in_seq_no=0, out_seq_no=1, layer=SECRET_LAYER).to_bytes()
        session.out_seq_no = 1
        self.assertEqual(legacy(), expected)
        session.old_keys.clear()
        self.assertEqual(legacy(), b'')
        session.old_keys[11] = initial
        session.sent_layers.clear()
        self.assertEqual(legacy(), b'')

    def test_received_transport_cutover_follows_sequence_and_survives_restarts(self):
        session = SecretChatSession(chat_id=42, state='active')

        def packet(seq, layer):
            return SecretLayerPacket(message=SecretMessageData(random_id=7, message='Test'),
                                     in_seq_no=1, out_seq_no=2 * seq, layer=layer,
                                     random_bytes=bytes(16))

        self.assertTrue(session.accept_transport(packet(0, 46), 1))
        session.pending_in = {3: b'legacy', 4: b'modern'}
        session.pending_v2 = {4}
        self.assertTrue(session.accept_transport(packet(2, 73), 2))
        self.assertTrue(session.accept_transport(packet(1, 46), 1))
        self.assertFalse(session.accept_transport(packet(3, 46), 1))
        self.assertEqual(session.pending_in, {4: b'modern'})
        restored = SecretChatSession.from_dict(session.to_dict())
        self.assertEqual(restored.mtproto2_from, 2)
        self.assertEqual(restored.pending_v2, {4})
        self.assertFalse(restored.accept_transport(packet(4, 46), 1))
        self.assertTrue(restored.accept_transport(packet(1, 73), 2))
        self.assertEqual(restored.mtproto2_from, 1)
        self.assertFalse(restored.accept_transport(packet(1, 46), 1))

    def test_first_layer_notification_and_existing_modern_chat(self):
        session = SecretChatSession(chat_id=42)
        announcing = SecretLayerPacket(
            message=SecretMessageData(random_id=7, action=SecretAction('notify_layer', layer=73)),
            in_seq_no=1, out_seq_no=0, layer=46, random_bytes=bytes(16))
        self.assertTrue(session.accept_transport(announcing, 1))
        self.assertEqual(session.mtproto2_from, 1)
        session.in_seq_no = 8
        session.pending_in[10] = b'unknown'
        previous = session.to_dict()
        del previous['mtproto2_from'], previous['pending_v2']
        restored = SecretChatSession.from_dict(previous)
        self.assertEqual(restored.mtproto2_from, 8)
        self.assertFalse(restored.pending_in)

    def test_mtproto2_encrypt_decrypt_and_direction_separation(self):
        key = secrets.token_bytes(256)
        fp = -1234567890123456789
        pkt = SecretLayerPacket(
            message=SecretMessageData(
                random_id=42,
                ttl=15,
                message='Hola desde chat secreto E2E',
                entities=[t.MessageEntityBold(0, 4), t.MessageEntityTextUrl(5, 5, 'https://telegram.org')],
                reply_to_random_id=99,
            ),
            in_seq_no=0,
            out_seq_no=1,
            layer=SECRET_LAYER,
        )
        raw = pkt.to_bytes()
        # Admin sends -> Responder decrypts
        ciphertext = mtproto2_encrypt(key, fp, True, raw)
        used_fp, decrypted = mtproto2_decrypt({fp: key}, False, ciphertext)
        self.assertEqual(used_fp, fp)
        decoded = SecretLayerPacket.from_bytes(decrypted)
        self.assertEqual(decoded.layer, SECRET_LAYER)
        self.assertEqual(decoded.in_seq_no, 0)
        self.assertEqual(decoded.out_seq_no, 1)
        self.assertEqual(decoded.message.random_id, 42)
        self.assertEqual(decoded.message.ttl, 15)
        self.assertEqual(decoded.message.message, 'Hola desde chat secreto E2E')
        self.assertEqual(decoded.message.reply_to_random_id, 99)
        self.assertEqual(len(decoded.message.entities), 2)

        # Direction separation: admin cannot decrypt its own outgoing packet as incoming
        with self.assertRaises(ValueError):
            mtproto2_decrypt({fp: key}, True, ciphertext)

        # MTProto 1.0 KDF fallback is also functional
        k1, iv1 = mtproto1_kdf(key, ciphertext[8:24])
        self.assertEqual(len(k1), 32)
        self.assertEqual(len(iv1), 32)
        k2, iv2 = mtproto2_kdf(key, ciphertext[8:24], 0)
        self.assertEqual(( len(k2), len(iv2) ), (32, 32))

    def test_all_secret_service_actions_and_media_roundtrip(self):
        actions = [
            SecretAction('set_ttl', ttl_seconds=60),
            SecretAction('read', random_ids=[101, 202, -303]),
            SecretAction('delete', random_ids=[555]),
            SecretAction('screenshot', random_ids=[777, 888]),
            SecretAction('flush'),
            SecretAction('resend', start_seq_no=2, end_seq_no=6),
            SecretAction('notify_layer', layer=144),
            SecretAction('typing', typing=SecretTypingAction('typing')),
            SecretAction('request_key', exchange_id=987654321, g_a=secrets.token_bytes(256)),
            SecretAction('accept_key', exchange_id=987654321, g_b=secrets.token_bytes(256), key_fingerprint=-42),
            SecretAction('commit_key', exchange_id=987654321, key_fingerprint=-42),
            SecretAction('abort_key', exchange_id=987654321),
            SecretAction('noop'),
        ]
        for act in actions:
            pkt = SecretLayerPacket(
                message=SecretMessageData(random_id=1234, action=act),
                in_seq_no=2,
                out_seq_no=3,
            )
            parsed = SecretLayerPacket.from_bytes(pkt.to_bytes()).message.action
            self.assertEqual(parsed.kind, act.kind)
            self.assertEqual(parsed.ttl_seconds, act.ttl_seconds)
            self.assertEqual(parsed.random_ids, act.random_ids)
            self.assertEqual(parsed.start_seq_no, act.start_seq_no)
            self.assertEqual(parsed.end_seq_no, act.end_seq_no)
            self.assertEqual(parsed.exchange_id, act.exchange_id)
            self.assertEqual(parsed.key_fingerprint, act.key_fingerprint)

        # Document media with voice + sticker attributes roundtrip
        doc_media = SecretMediaPayload(
            kind='document',
            thumb=b'thumb',
            thumb_w=32,
            thumb_h=32,
            mime_type='audio/ogg',
            size=123456,
            key=secrets.token_bytes(32),
            iv=secrets.token_bytes(32),
            attributes=[
                SecretDocAttribute('audio', voice=True, duration=12),
                SecretDocAttribute('filename', file_name='voice.ogg'),
            ],
            caption='Nota de voz cifrada',
        )
        pkt_doc = SecretLayerPacket(
            message=SecretMessageData(random_id=77, message='Nota de voz cifrada', media=doc_media)
        )
        decoded_media = SecretLayerPacket.from_bytes(pkt_doc.to_bytes()).message.media
        self.assertEqual(decoded_media.kind, 'document')
        self.assertEqual(decoded_media.size, 123456)
        self.assertEqual(decoded_media.file_name, 'voice.ogg')
        self.assertEqual(decoded_media.key, doc_media.key)
        self.assertEqual(decoded_media.iv, doc_media.iv)

    def test_aes256_ige_file_encryption_and_fingerprint(self):
        original = b'Contenido confidencial adjunto en chat secreto ' * 100 + b'123'
        encrypted, key, iv, fp, md5_hex = encrypt_file_bytes(original)
        self.assertEqual(len(encrypted) % 16, 0)
        self.assertNotIn(b'Contenido confidencial', encrypted)
        self.assertEqual(fp, file_key_fingerprint(key, iv))
        self.assertEqual(len(md5_hex), 32)

        decrypted = decrypt_file_bytes(encrypted, key, iv, len(original), fp)
        self.assertEqual(decrypted, original)

        with self.assertRaises(ValueError):
            decrypt_file_bytes(encrypted, key, iv, len(original), fp ^ 1)


class SecretChatInteroperabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root_alice = Path(self.tmp.name) / 'alice'
        self.root_bob = Path(self.tmp.name) / 'bob'
        self.wire = FakeSecretWire()
        self.client_alice = self.wire.register(1001, 'Alice')
        self.client_bob = self.wire.register(2002, 'Bob')

        self.backend_alice = NS(
            client=self.client_alice,
            names={},
            cache_name=lambda pid, name: None,
            account_profile=NS(user_id=1001),
            callback=None,
            on_change=None,
        )
        self.backend_bob = NS(
            client=self.client_bob,
            names={},
            cache_name=lambda pid, name: None,
            account_profile=NS(user_id=2002),
            callback=None,
            on_change=None,
        )
        self.mgr_alice = SecretChatManager(self.backend_alice, self.root_alice, 'account')
        self.mgr_bob = SecretChatManager(self.backend_bob, self.root_bob, 'account')
        self.client_alice.manager = self.mgr_alice
        self.client_bob.manager = self.mgr_bob

    async def asyncTearDown(self):
        await self.mgr_alice.close()
        await self.mgr_bob.close()
        self.tmp.cleanup()

    async def test_discard_waits_for_confirmation_and_purges_remote_cached_files(self):
        chat_id = 71
        for manager in (self.mgr_alice, self.mgr_bob):
            token = manager.store.save_file(b'private attachment')
            manager.sessions[chat_id] = SecretChatSession(
                chat_id, state='active', key=b'local chat key', messages=[{'media': {'local_token': token}}],
            )
            manager.save_local_draft(secret_peer_id(chat_id), {'text': 'private draft'})
        with patch.object(self.mgr_alice, 'client', AsyncMock(side_effect=OSError)):
            with self.assertRaises(OSError):
                await self.mgr_alice.discard(chat_id, delete_history=True)
        self.assertEqual(self.mgr_alice.sessions[chat_id].key, b'local chat key')
        self.assertEqual(self.mgr_alice.local_draft(secret_peer_id(chat_id))['text'], 'private draft')

        await self.mgr_alice.discard(chat_id, delete_history=True)
        for manager in (self.mgr_alice, self.mgr_bob):
            self.assertNotIn(chat_id, manager.sessions)
            self.assertEqual(list(manager.store.files_dir.iterdir()), [])

    async def test_handshake_bidirectional_messaging_files_ttl_and_pfs_rekey(self):
        # 1. Alice starts secret chat with Bob (DH handshake auto-completes on Bob's side)
        chat_alice = await self.mgr_alice.start_chat(2002)
        self.assertTrue(is_secret_peer(chat_alice.id))
        cid = secret_chat_id(chat_alice.id)
        sess_a = self.mgr_alice.sessions[cid]
        sess_b = self.mgr_bob.sessions[cid]
        self.assertEqual(sess_a.state, 'active')
        self.assertEqual(sess_b.state, 'active')
        self.assertEqual(sess_a.key, sess_b.key)
        self.assertEqual(sess_a.key_fingerprint, sess_b.key_fingerprint)

        info_a = self.mgr_alice.chat_info(chat_alice.id)
        info_b = self.mgr_bob.chat_info(chat_alice.id)
        self.assertEqual(info_a['emojis'], info_b['emojis'])
        self.assertEqual(info_a['hex'], info_b['hex'])

        # 2. Bidirectional E2E encrypted text messages and sequence numbers
        sent_1 = await self.mgr_alice.send_formatted(
            chat_alice.id, 'Hola Bob, esto es E2E', [(0, 4, 'bold', '')], ()
        )
        self.assertEqual(sent_1.text, 'Hola Bob, esto es E2E')
        hist_bob = self.mgr_bob.history(chat_alice.id)
        self.assertTrue(any(m.text == 'Hola Bob, esto es E2E' and not m.outgoing for m in hist_bob))

        sent_2 = await self.mgr_bob.send_text(chat_alice.id, 'Recibido Alice, 100% cifrado')
        hist_alice = self.mgr_alice.history(chat_alice.id)
        self.assertTrue(any(m.text == 'Recibido Alice, 100% cifrado' and not m.outgoing for m in hist_alice))

        # 3. Encrypted attachment upload & download
        sample_file = Path(self.tmp.name) / 'secreto.txt'
        sample_file.write_bytes(b'Documento cifrado con clave efimera AES-256-IGE')
        await self.mgr_alice.send_file(chat_alice.id, sample_file, caption='Adjunto secreto')
        bob_msg = self.mgr_bob.history(chat_alice.id)[-1]
        self.assertIsInstance(bob_msg.media, SecretMedia)
        dest_file = Path(self.tmp.name) / 'descargado.txt'
        downloaded = await self.mgr_bob.download_media(bob_msg.media, dest_file)
        self.assertIsNotNone(downloaded)
        self.assertEqual(dest_file.read_bytes(), b'Documento cifrado con clave efimera AES-256-IGE')

        # 4. Out-of-order gap detection and automatic Resend recovery
        # Simulate a message from Alice with raw seq = sess_a.out_seq_no + 1 arriving before seq = sess_a.out_seq_no
        missing_seq = sess_a.out_seq_no
        missing_wire = 2 * missing_seq + sess_a.x_out
        pkt_missing = SecretLayerPacket(
            message=SecretMessageData(random_id=9001, message='Mensaje perdido en red'),
            in_seq_no=sess_a.wire_in_seq(),
            out_seq_no=missing_wire,
            layer=SECRET_LAYER,
        )
        sess_a.sent_layers[missing_wire] = pkt_missing.to_bytes()
        sess_a.out_seq_no += 1

        # Now Alice sends the next message (seq = missing_seq + 1); Bob detects the gap, buffers it,
        # sends ResendAction to Alice, Alice resends pkt_missing, and Bob processes both in order!
        await self.mgr_alice.send_text(chat_alice.id, 'Mensaje posterior al hueco')
        await asyncio.sleep(0.05)
        bob_texts = [m.raw_text for m in self.mgr_bob.history(chat_alice.id) if not m.service]
        self.assertIn('Mensaje perdido en red', bob_texts)
        self.assertIn('Mensaje posterior al hueco', bob_texts)
        self.assertLess(
            bob_texts.index('Mensaje perdido en red'),
            bob_texts.index('Mensaje posterior al hueco'),
        )

        # 5. Perfect Forward Secrecy (PFS) key rotation at 100 messages
        old_fp = sess_a.key_fingerprint
        sess_a.key_use_count = REKEY_MESSAGE_LIMIT
        await self.mgr_alice.send_text(chat_alice.id, 'Disparando rotacion PFS')
        # Wait for background rekey tasks to complete
        for _ in range(20):
            if sess_a.key_fingerprint != old_fp and sess_b.key_fingerprint == sess_a.key_fingerprint:
                break
            await asyncio.sleep(0.02)
        self.assertNotEqual(sess_a.key_fingerprint, old_fp)
        self.assertEqual(sess_a.key_fingerprint, sess_b.key_fingerprint)
        self.assertEqual(sess_a.key, sess_b.key)
        self.assertEqual(sess_a.key_use_count, 0)
        for manager in (self.mgr_alice, self.mgr_bob):
            rotated_info = manager.chat_info(chat_alice.id)
            for field in ('emojis', 'hex', 'grid'):
                self.assertEqual(rotated_info[field], info_a[field])
            saved = SecretChatSession.from_dict(manager.sessions[cid].to_dict())
            self.assertEqual(saved.visual_hash, sess_a.visual_hash)

        # Verify messaging continues seamlessly with the rotated key
        await self.mgr_bob.send_text(chat_alice.id, 'Mensaje con clave nueva PFS')
        self.assertEqual(self.mgr_alice.history(chat_alice.id)[-1].raw_text, 'Mensaje con clave nueva PFS')

        # 6. Self-Destruct Timer (TTL) and message expiration
        await self.mgr_alice.set_ttl(chat_alice.id, 1)
        self.assertEqual(sess_b.ttl, 1)
        ttl_msg = await self.mgr_alice.send_text(chat_alice.id, 'Se autodestruira en 1s')
        await self.mgr_bob.mark_read(chat_alice.id)
        # Force expiration timestamp slightly in the past and prune
        for s in (sess_a, sess_b):
            for m in s.messages:
                if m.get('raw_text') == 'Se autodestruira en 1s':
                    m['expires_at'] = time.time() - 0.1
        self.mgr_alice._prune_expired_sync()
        self.mgr_bob._prune_expired_sync()
        self.assertFalse(any(m.raw_text == 'Se autodestruira en 1s' for m in self.mgr_alice.history(chat_alice.id)))
        self.assertFalse(any(m.raw_text == 'Se autodestruira en 1s' for m in self.mgr_bob.history(chat_alice.id)))

    async def test_encrypted_local_store_at_rest_and_logout_purge(self):
        chat_alice = await self.mgr_alice.start_chat(2002)
        await self.mgr_alice.send_text(chat_alice.id, 'Texto ultrasecreto en disco')
        state_file = self.root_alice / 'secret-chats' / 'account.bin'
        self.assertTrue(state_file.exists())
        raw_disk_bytes = state_file.read_bytes()
        self.assertTrue(raw_disk_bytes.startswith(SecretStore.MAGIC))
        self.assertNotIn(b'Texto ultrasecreto en disco', raw_disk_bytes)

        # Reload into a new SecretChatManager and verify decryption
        reloaded = SecretChatManager(self.backend_alice, self.root_alice, 'account')
        try:
            msgs = reloaded.history(chat_alice.id)
            self.assertTrue(any(m.raw_text == 'Texto ultrasecreto en disco' for m in msgs))
        finally:
            await reloaded.close()

        # Purge on logout removes all state and keys
        purge(self.root_alice, 'account')
        self.assertFalse(state_file.exists())


class SecretChatBackendAndCapabilitiesTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_backend_and_capabilities_for_secret_chats(self):
        demo = DemoBackend()
        secret_chat = await demo.start_secret_chat(2)
        self.assertEqual(secret_chat.kind, 'secret')
        self.assertTrue(is_secret_peer(secret_chat.id))

        caps = capabilities_for(secret_chat)
        self.assertEqual(caps.kind, 'secret')
        self.assertTrue(caps.readable)
        self.assertTrue(caps.writable)
        self.assertTrue(caps.allows('send_text'))
        self.assertTrue(caps.allows('send_photos'))
        self.assertFalse(caps.allows('forward'))
        self.assertFalse(caps.allows('schedule'))
        self.assertFalse(caps.allows('pin_message'))

        info = await demo.secret_chat_info(secret_chat.id)
        self.assertEqual(len(info['emojis'].split()), 5)
        self.assertEqual(len(info['grid']), 12)
        updated = await demo.set_secret_ttl(secret_chat.id, 30)
        self.assertEqual(updated['ttl'], 30)
        self.assertEqual(updated['ttl_label'], '30s')


if __name__ == '__main__':
    unittest.main()

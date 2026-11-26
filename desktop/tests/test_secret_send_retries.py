"""Delivery ambiguity must preserve the secret message and its encrypted file."""
import unittest
import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, patch

from telethon import functions as f, types as t

from tg_ascii.outbox import with_random_ids
from tg_ascii.secret_chats import SecretChatManager, SecretChatSession, SecretStore, secret_chat_id
from tg_ascii.secret_tl import decrypt_file_bytes, encrypt_file_bytes
from tests import test_secret_chats_v30 as fixtures


class ReplyLostClient:
    def __init__(self, client, manager):
        self.client, self.manager = client, manager
        self.requests = []
        self.uploads = 0

    def __getattr__(self, name):
        return getattr(self.client, name)

    async def upload_file(self, *args, **kwargs):
        self.uploads += 1
        return await self.client.upload_file(*args, **kwargs)

    async def __call__(self, request):
        user_send = isinstance(request, (f.messages.SendEncryptedRequest,
                                        f.messages.SendEncryptedFileRequest))
        if user_send:
            state = self.manager.store.load_state()
            saved = next(row for row in state['sessions'] if row['chat_id'] == request.peer.chat_id)
            assert str(request.random_id) in saved['pending_outgoing']
            assert saved['out_seq_no'] == self.manager.sessions[request.peer.chat_id].out_seq_no
            self.requests.append(request)
        result = await self.client(request)
        if user_send and len(self.requests) == 1:
            raise ConnectionError('Reply lost after the peer received the message')
        return result


class SecretRetryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.SecretChatInteroperabilityTests.asyncSetUp
    asyncTearDown = fixtures.SecretChatInteroperabilityTests.asyncTearDown

    async def start(self):
        chat = await self.mgr_alice.start_chat(2002)
        session = self.mgr_alice.sessions[secret_chat_id(chat.id)]
        proxy = ReplyLostClient(self.client_alice, self.mgr_alice)
        self.mgr_alice.client = proxy
        return chat, session, proxy

    async def test_lost_text_reply_reuses_exact_ciphertext_and_sequence(self):
        chat, session, proxy = await self.start()
        with self.assertRaises(ConnectionError):
            await with_random_ids([411], self.mgr_alice.send_text(chat.id, 'One message'))
        sequence = session.out_seq_no
        sent = await with_random_ids([411], self.mgr_alice.send_text(chat.id, 'Changed UI text'))
        self.assertEqual(sent.text, 'One message')
        self.assertEqual(session.out_seq_no, sequence)
        self.assertEqual(proxy.requests[0].data, proxy.requests[1].data)
        self.assertEqual(proxy.requests[0].random_id, proxy.requests[1].random_id)
        self.assertEqual(sum(m['random_id'] == 411 for m in session.messages), 1)
        self.assertEqual(sum(m['random_id'] == 411 for m in self.mgr_bob.sessions[session.chat_id].messages), 1)
        self.assertFalse(session.pending_outgoing)
        await with_random_ids([411], self.mgr_alice.send_text(chat.id, 'Retry again'))
        self.assertEqual(len(proxy.requests), 2)

    async def test_file_retry_does_not_reupload_or_reread_changed_source(self):
        chat, session, proxy = await self.start()
        path = self.root_alice / 'file.txt'
        original = b'Original private bytes' * 20
        path.write_bytes(original)
        with self.assertRaises(ConnectionError):
            await with_random_ids([412], self.mgr_alice.send_file(chat.id, path))
        sequence = session.out_seq_no
        path.unlink()
        sent = await with_random_ids([412], self.mgr_alice.send_file(chat.id, path))
        self.assertEqual(proxy.uploads, 1)
        self.assertEqual(session.out_seq_no, sequence)
        self.assertEqual(proxy.requests[0].data, proxy.requests[1].data)
        self.assertEqual(bytes(proxy.requests[0].file), bytes(proxy.requests[1].file))
        self.assertGreater(sent.media.file_id, 0)
        self.assertEqual(self.mgr_alice.store.load_file(sent.media.local_token), original)
        self.assertFalse(session.pending_outgoing)

    async def test_disk_failure_prevents_rpc_and_retry_keeps_sequence(self):
        chat, session, proxy = await self.start()
        with patch.object(self.mgr_alice.store, 'save_state', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                await with_random_ids([413], self.mgr_alice.send_text(chat.id, 'Persist first'))
        self.assertFalse(proxy.requests)
        sequence = session.out_seq_no
        with self.assertRaises(ConnectionError):
            await with_random_ids([413], self.mgr_alice.send_text(chat.id, 'Persist first'))
        self.assertEqual(session.out_seq_no, sequence)

    async def test_encrypted_pending_snapshot_survives_reload(self):
        chat, session, proxy = await self.start()
        with self.assertRaises(ConnectionError):
            await with_random_ids([414], self.mgr_alice.send_text(chat.id, 'Encrypted pending'))
        raw = self.mgr_alice.store.load_state()
        roundtrip = SecretChatSession.from_dict(next(row for row in raw['sessions']
                                                    if row['chat_id'] == session.chat_id))
        self.assertEqual(roundtrip.pending_outgoing, session.pending_outgoing)
        await self.mgr_alice.close()
        self.mgr_alice = SecretChatManager(self.backend_alice, self.root_alice, 'account')
        self.client_alice.manager = self.mgr_alice
        proxy.manager = self.mgr_alice
        self.mgr_alice.client = proxy
        await with_random_ids([414], self.mgr_alice.send_text(chat.id, 'Encrypted pending'))
        self.assertEqual(proxy.requests[0].data, proxy.requests[1].data)

    async def test_discard_clears_pending_encrypted_attachments(self):
        chat, session, proxy = await self.start()
        path = self.root_alice / 'file.txt'
        path.write_bytes(b'Pending private bytes')
        with self.assertRaises(ConnectionError):
            await with_random_ids([415], self.mgr_alice.send_file(chat.id, path))
        token = session.pending_outgoing['415']['record']['media']['local_token']
        self.assertIsNotNone(self.mgr_alice.store.load_file(token))
        await self.mgr_alice.discard(chat.id)
        self.assertFalse(session.pending_outgoing)
        self.assertIsNone(self.mgr_alice.store.load_file(token))

    async def test_reordered_file_keeps_its_reference_when_gap_is_filled(self):
        chat = await self.mgr_alice.start_chat(2002)
        held = []
        original = self.client_alice

        class ReorderingClient:
            def __getattr__(self, name):
                return getattr(original, name)

            async def __call__(self, request):
                if isinstance(request, f.messages.SendEncryptedRequest):
                    held.append(request)
                    return t.messages.SentEncryptedMessage(date=datetime.now(timezone.utc))
                return await original(request)

        self.mgr_alice.client = ReorderingClient()
        path = self.root_alice / 'delayed.txt'
        path.write_bytes(b'Keep the encrypted file reference')
        with patch.object(self.mgr_alice, '_handle_resend_request', AsyncMock()):
            await self.mgr_alice.send_text(chat.id, 'Arrives second')
            sent = await self.mgr_alice.send_file(chat.id, path)
        receiver = self.mgr_bob.sessions[secret_chat_id(chat.id)]
        self.assertEqual(len(receiver.pending_in), 1)
        restored = SecretChatSession.from_dict(receiver.to_dict())
        self.assertEqual(restored.pending_metadata, receiver.pending_metadata)
        await original(held[0])
        received = next(row for row in self.mgr_bob.history(chat.id)
                        if row.media and row.media.file_name == 'delayed.txt')
        self.assertEqual(received.media.file_id, sent.media.file_id)
        self.assertEqual(received.media.access_hash, sent.media.access_hash)
        self.assertFalse(receiver.pending_metadata)

    async def test_resend_of_file_preserves_its_encrypted_file_reference(self):
        chat = await self.mgr_alice.start_chat(2002)
        session = self.mgr_alice.sessions[secret_chat_id(chat.id)]
        wire_sequence = session.wire_out_seq()
        path = self.root_alice / 'resend.txt'
        path.write_bytes(b'Keep attachment when recovering sequence gap')
        sent = await self.mgr_alice.send_file(chat.id, path)
        with patch.object(self.mgr_alice, 'client', AsyncMock()) as transport:
            await self.mgr_alice._handle_resend_request(session, wire_sequence, wire_sequence)
        request = transport.call_args.args[0]
        self.assertIsInstance(request, f.messages.SendEncryptedFileRequest)
        self.assertEqual(request.file.id, sent.media.file_id)
        self.assertEqual(request.file.access_hash, sent.media.access_hash)

    async def test_reload_rearms_saved_expiry_without_opening_the_chat(self):
        chat = await self.mgr_alice.start_chat(2002)
        sent = await self.mgr_alice.send_text(chat.id, 'Expires after restart')
        session = self.mgr_alice.sessions[secret_chat_id(chat.id)]
        row = next(row for row in session.messages if row['id'] == sent.id)
        row['expires_at'] = time.time() + .05
        self.mgr_alice._save()
        await self.mgr_alice.close()
        self.mgr_alice = SecretChatManager(self.backend_alice, self.root_alice, 'account')
        self.client_alice.manager = self.mgr_alice
        self.assertIsNotNone(self.mgr_alice._ttl_task)
        await asyncio.sleep(.25)
        self.assertFalse(any(row['id'] == sent.id for row in self.mgr_alice.sessions[session.chat_id].messages))


class SecretFileLengthTests(unittest.TestCase):
    def test_file_store_format_is_unchanged_for_every_alignment(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SecretStore(Path(folder), 'format')
            for size in (0, 1, 11, 12, 15, 16, 4096, 4097):
                with self.subTest(size=size):
                    raw = b'x' * size
                    token = store.save_file(raw)
                    blob = (store.files_dir / f'{token}.bin').read_bytes()
                    self.assertEqual(store.decrypt_blob(blob), raw)
                    self.assertEqual(store.load_file(token), raw)

    def test_truncated_extra_and_partial_ciphertext_are_rejected(self):
        original = b'x' * 99
        encrypted, key, iv, fp, _ = encrypt_file_bytes(original)
        self.assertEqual(decrypt_file_bytes(encrypted, key, iv, len(original), fp), original)
        for bad in (b'', encrypted[:-1], encrypted[:-16], encrypted + bytes(16)):
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                decrypt_file_bytes(bad, key, iv, len(original), fp)

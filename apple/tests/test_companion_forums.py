import datetime
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from telethon import functions, types, utils
from tg_ascii_mobile.core import Core
from tg_ascii_mobile.tv import share_chat
from tg_ascii_watch.app import TgAsciiWatch

WATCH = Path(__file__).resolve().parents[1] / "watch" / "python"
GROUP = types.PeerChannel(141)
PEER = utils.get_peer_id(GROUP)
NOW = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)


def topic(ident):
    return types.ForumTopic(
        ident,
        NOW,
        GROUP,
        "General" if ident == 1 else "Diseño",
        1,
        98,
        0,
        20,
        2,
        0,
        0,
        0,
        types.PeerUser(14),
        types.PeerNotifySettings(),
    )


def row(ident, root=1):
    reply = None if root == 1 else types.MessageReplyHeader(forum_topic=True, reply_to_msg_id=root)
    return types.Message(
        ident, GROUP, date=NOW, message=f"Mensaje {ident}", from_id=types.PeerUser(14), reply_to=reply
    )


class ForumTransport:
    def __init__(self):
        self.group = types.Channel(
            141,
            "Proyecto",
            types.ChatPhotoEmpty(),
            NOW,
            creator=True,
            megagroup=True,
            forum=True,
            access_hash=1,
        )
        self.person = types.User(14, first_name="Luz")
        self.closed_topics = set()
        self.topic_pages = None
        self.raw_handlers = []
        self.requests = []
        self.sent = []
        self.read = []
        self.rows = [row(80, 7), row(77, 1), row(76, 7)]
        self.chat = AsyncMock()

    def add_event_handler(self, handler, kind):
        self.raw_handlers.append(handler)

    async def get_entity(self, peer):
        return self.person if utils.get_peer_id(peer) == 14 else self.group

    async def get_input_entity(self, peer):
        return utils.get_input_peer(await self.get_entity(peer))

    async def iter_messages(self, entity, **params):
        self.iter_params = params
        if "ids" in params:
            latest = {m.id: m for m in self.rows}
            for ident in params["ids"]:
                yield latest.get(ident)
        else:
            for m in self.rows:
                yield m

    async def __call__(self, q):
        self.requests.append(q)
        if isinstance(q, functions.channels.GetFullChannelRequest):
            return NS(chats=[self.group], full_chat=NS(linked_chat_id=None))
        if isinstance(
            q, (functions.messages.GetForumTopicsRequest, functions.messages.GetForumTopicsByIDRequest)
        ):
            ids = getattr(q, "topics", [1, 7])
            if self.topic_pages is not None and isinstance(q, functions.messages.GetForumTopicsRequest):
                ids = self.topic_pages.get(q.offset_topic, [])
            topics = [topic(i) for i in ids]
            for item in topics:
                item.pinned = self.topic_pages is not None and item.id == 1
                item.closed = item.id in self.closed_topics
            return NS(
                topics=topics,
                messages=[],
                users=[self.person],
                chats=[self.group],
                count=len({i for page in self.topic_pages.values() for i in page})
                if self.topic_pages
                else len(ids),
                order_by_create_date=False,
            )
        if isinstance(q, functions.messages.GetRepliesRequest):
            return NS(messages=self.rows, users=[self.person], chats=[self.group])
        if isinstance(q, functions.messages.ReadDiscussionRequest):
            self.read.append((q.msg_id, q.read_max_id))
            return True
        if isinstance(q, functions.messages.SendMessageRequest):
            self.sent.append(q.reply_to.reply_to_msg_id if q.reply_to else 1)
            return True
        raise AssertionError(type(q).__name__)


class StandaloneAppleWatchTests(IsolatedAsyncioTestCase):
    async def test_transport_uses_selected_topic_for_history_reads_and_send(self):
        with patch.object(sys, "path", [str(WATCH), *sys.path]):
            import tgwatch

            transport = ForumTransport()
            with patch.object(tgwatch, "_ensure_client", AsyncMock(return_value=transport)):
                self.assertEqual(
                    [r["id"] for r in (await tgwatch._handle({"op": "topics", "peer": PEER}))["topics"]],
                    [1, 7],
                )
                messages = await tgwatch._handle({"op": "messages", "peer": PEER, "topic_id": 7})
                self.assertEqual([x["id"] for x in messages], [76, 80])
                self.assertEqual(messages[0]["sender"], "Luz")
                self.assertEqual(transport.read, [(7, 80)])
                for root in (7, 1):
                    self.assertTrue(
                        (
                            await tgwatch._handle(
                                {"op": "send", "peer": PEER, "topic_id": root, "text": "Prueba"}
                            )
                        )["ok"]
                    )
                self.assertEqual(transport.sent, [7, 1])
                self.assertEqual(transport.read, [(7, 80)])
                with self.assertRaisesRegex(ValueError, "tema"):
                    await tgwatch._handle({"op": "send", "peer": PEER, "text": "Fuera"})
                self.assertEqual(transport.sent, [7, 1])
                self.assertFalse(
                    any(isinstance(q, functions.messages.ReadHistoryRequest) for q in transport.requests)
                )

    async def test_topic_pagination_survives_round_trips_and_expires_with_the_account(self):
        with patch.object(sys, "path", [str(WATCH), *sys.path]):
            import tgwatch

            first, second = ForumTransport(), ForumTransport()
            first.topic_pages = {0: [1, 7], 7: [1, 8]}
            with patch.object(tgwatch, "_ensure_client", AsyncMock(return_value=first)):
                start = await tgwatch._handle({"op": "topics", "peer": PEER})
                cursor = json.loads(json.dumps(start["next_cursor"]))
                self.assertEqual((cursor["seen"], cursor["pinned"]), (2, [1]))
                req = {"op": "topics", "peer": PEER, "cursor": cursor}
                more = await tgwatch._handle(req)
                self.assertEqual([item["id"] for item in more["topics"]], [8])
                self.assertIsNone(more["next_cursor"])
                self.assertEqual(len(first.raw_handlers), 1)
                first.topic_pages[0] = [1, 9]
                await first.raw_handlers[0](types.UpdateChannel(first.group.id))
                refreshed = await tgwatch._handle({"op": "topics", "peer": PEER})
                self.assertEqual([item["id"] for item in refreshed["topics"]], [1, 9])
            with patch.object(tgwatch, "_ensure_client", AsyncMock(return_value=second)):
                with self.assertRaises(ValueError):
                    await tgwatch._handle(req)

    async def test_closed_topic_and_text_ban_are_enforced_before_sending(self):
        with patch.object(sys, "path", [str(WATCH), *sys.path]):
            from tgwatch.forum_client import WatchForums

            transport = ForumTransport()
            transport.group.creator = False
            transport.closed_topics.add(7)
            forums = WatchForums(transport)
            with self.assertRaises(ValueError):
                await forums.send_text(PEER, 7, "Tema cerrado")
            transport.closed_topics.clear()
            transport.group.default_banned_rights = types.ChatBannedRights(NOW, send_plain=True)
            with self.assertRaises(ValueError):
                await forums.send_text(PEER, 7, "Texto restringido")
            self.assertEqual(transport.sent, [])


class AppleCompanionTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.c = Core.__new__(Core)
        self.c.accounts = NS(current="a", services={"a": NS(backend=NS(client=ForumTransport()))})
        self.c.chats = []
        self.c.locked = False
        self.c.stage = "ready"
        self.c.open_peer = 123
        self.c.message_json = lambda m: {"id": m.id, "text": "mensaje", "time": "12:00", "out": False}
        self.c.api_send = AsyncMock()

    async def test_phone_keeps_its_conversation_and_only_reads_selected_topic(self):
        operations = []

        async def forum(operation, *args, account=None, **kwargs):
            operations.append((operation, args, account))
            return [NS(id=80, service=False)] if operation == "forum_history" else True

        self.c.forum_call = forum
        self.assertEqual(
            (await self.c.watch_request({"op": "messages", "peer": PEER, "topic_id": 7, "account": "a"}))[0][
                "id"
            ],
            80,
        )
        self.assertEqual(self.c.open_peer, 123)
        self.assertEqual(
            [op[:2] for op in operations], [("forum_history", (PEER, 7)), ("forum_mark_read", (PEER, 7, 80))]
        )
        await self.c.watch_request(
            {"op": "send", "peer": PEER, "topic_id": 7, "text": "Prueba", "account": "a"}
        )
        self.assertEqual(operations[-1], ("forum_send", (PEER, 7, "Prueba"), "a"))
        self.c.api_send.assert_not_awaited()

    async def test_old_watch_and_stale_accounts_cannot_send_to_general(self):
        with self.assertRaises(ValueError):
            await self.c.watch_request({"op": "send", "peer": PEER, "text": "Fuera"})
        with self.assertRaises(ValueError):
            await self.c.watch_request(
                {"op": "send", "peer": PEER, "topic_id": 7, "text": "A otra cuenta", "account": "otra"}
            )
        self.c.api_send.assert_not_awaited()


class WearEventsTests(TestCase):
    def test_message_and_background_history_are_isolated_by_topic(self):
        app = NS(screen="chat", open_peer=PEER, topic={"id": 7}, messages=[], show_chat=Mock())
        for ident, root in [(12, 1), (14, 7), (16, 8)]:
            TgAsciiWatch.on_event(
                app, {"type": "message", "data": {"peer": PEER, "message": {"id": ident, "topic_id": root}}}
            )
        TgAsciiWatch.on_event(app, {"type": "history", "data": {"peer": PEER, "messages": [{"id": 99}]}})
        self.assertEqual([m["id"] for m in app.messages], [14])
        app.show_chat.assert_called_once_with()


class TelevisionTopicTests(IsolatedAsyncioTestCase):
    async def test_mixed_history_is_labelled_and_single_topic_is_filtered(self):
        client = ForumTransport()
        link = NS(connectionID=lambda: "qa", share_connection_=Mock(return_value=True))
        look = {
            "name": "TV",
            "bg": "#000000",
            "text": "#ffffff",
            "strong": "#ffffff",
            "font": "sf",
            "scale": 1,
            "brand_logo": {"variant": "title-short", "theme": "dark", "color": "blue"},
        }
        with patch.object(sys, "path", [str(WATCH), *sys.path]):
            from tgwatch.forum_client import WatchForums

        backend = WatchForums(client)
        core = NS(
            tv_link=link,
            stage="ready",
            account="a",
            locked=False,
            in_background=False,
            backend=backend,
            chats=[NS(id=PEER, name="Proyecto")],
            text=str,
            watch_appearance=lambda: look,
        )
        await share_chat(core, PEER, "a")
        packet = json.loads(link.share_connection_.call_args.args[0])
        self.assertEqual(
            packet["messages"], ["Diseño · Mensaje 76", "General · Mensaje 77", "Diseño · Mensaje 80"]
        )
        await share_chat(core, PEER, "a", 7)
        packet = json.loads(link.share_connection_.call_args.args[0])
        self.assertEqual((packet["title"], packet["topic_id"]), ("Proyecto · Diseño", 7))
        self.assertEqual(packet["messages"], ["Mensaje 76", "Mensaje 80"])
        self.assertEqual(client.iter_params["ids"], [80, 76])

        protected, expiring = row(85), row(86)
        protected.noforwards, expiring.ttl_period = True, 60
        client.rows = [row(90, 7), row(88), expiring, protected, row(77)]
        await share_chat(core, PEER, "a", 1)
        packet = json.loads(link.share_connection_.call_args.args[0])
        self.assertEqual((packet["title"], packet["topic_id"]), ("Proyecto · General", 1))
        self.assertEqual(packet["messages"], ["Mensaje 77", "Mensaje 88"])
        self.assertEqual(client.iter_params, {"ids": [88, 86, 85, 77]})
        self.assertEqual(
            [q.msg_id for q in client.requests if isinstance(q, functions.messages.GetRepliesRequest)], [7, 1]
        )

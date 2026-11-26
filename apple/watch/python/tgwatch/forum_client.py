"""The standalone watch uses the same forum permissions, pagination and read boundaries as the phone."""
from types import SimpleNamespace

from telethon import errors, events, functions, utils
from tg_ascii.community_management import CommunityManagement
from tg_ascii.forum_topics import ForumTopics, _allowed, _denied
from tg_ascii.peer_tools import PeerTools


class WatchForums(ForumTopics, PeerTools, CommunityManagement):
    def __init__(self, client):
        self.client = client
        self.names = {}

    @classmethod
    def for_client(cls, client):
        adapter = getattr(client, '_tgwatch_forums', None)
        if adapter is None:
            adapter = cls(client)
            client.add_event_handler(adapter.updated, events.Raw())
            client._tgwatch_forums = adapter
        return adapter

    async def updated(self, update):
        self.forum_update(update)

    def cache_name(self, peer, name):
        if name:
            self.names[peer] = name
            if len(self.names) > 1024:
                self.names.pop(next(iter(self.names)))

    async def resolve_missing_senders(self, rows):
        for peer in dict.fromkeys(row.sender_id for row in rows if row.sender_id):
            if peer not in self.names:
                try:
                    self.cache_name(peer, utils.get_display_name(await self.client.get_entity(peer)))
                except (ValueError, OSError, errors.RPCError):
                    pass

    @staticmethod
    def message(row):
        # The watch formats its own compact message once the shared core has
        # resolved this topic's outgoing read maximum and chronological order.
        return SimpleNamespace(id=row.id, outgoing=bool(row.out), raw=row)

    async def send_text(self, peer, topic, text):
        if not text.strip():
            raise ValueError('Empty message.')
        entity, reply = await self._forum_destination(peer, topic, None)
        if not _allowed(entity, 'send_plain'):
            raise _denied()
        await self.client(functions.messages.SendMessageRequest(entity, text, reply_to=reply))
        self._forum_changed(utils.get_peer_id(entity), topic)

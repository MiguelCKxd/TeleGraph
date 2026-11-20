"""Native Telegram text drafts with UTF-16 entities and account-scoped updates."""
import asyncio
from datetime import timezone

from telethon import functions as f, types as t, utils

from .message_tools import entity_spans, formatted_entities

DRAFT_TIMEOUT = 15


def decode_draft(draft):
    stamp = getattr(draft, 'date', None)
    if stamp is not None and stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    result = {'text': '', 'custom': [], 'formats': [], 'reply': None,
              'date': stamp.timestamp() if stamp is not None else 0, 'unsupported': False}
    if isinstance(draft, t.DraftMessageEmpty):
        return result
    if not isinstance(draft, t.DraftMessage):
        raise ValueError('Unsupported Telegram draft.')
    text = draft.message or ''
    formats, custom = entity_spans(text, draft.entities or [])
    reply = getattr(draft, 'reply_to', None)
    result.update(text=text, formats=formats, custom=custom,
                  reply=reply.reply_to_msg_id if isinstance(reply, t.InputReplyToMessage) else None)
    # Retain a marker so the text editor never silently discards a richer draft
    # created by another Telegram client (attachments, effects, quoted replies).
    result['unsupported'] = any(getattr(draft, key, None) is not None for key in
        ('media', 'effect', 'suggested_post', 'rich_message')) or (reply is not None and (
            not isinstance(reply, t.InputReplyToMessage) or any(getattr(reply, key, None) is not None for key in
                ('top_msg_id', 'reply_to_peer_id', 'quote_text', 'monoforum_peer_id', 'todo_item_id', 'poll_option'))))
    return result


class TelegramDrafts:
    async def fetch_drafts(self):
        versions = dict(getattr(self, '_draft_versions', {}))
        response = await asyncio.wait_for(self.client(f.messages.GetAllDraftsRequest()), DRAFT_TIMEOUT)
        if not hasattr(response, 'updates'):
            raise ValueError('Telegram did not return a complete draft snapshot.')
        result = {}
        snapshots = {}
        for update in getattr(response, 'updates', ()):
            if not isinstance(update, t.UpdateDraftMessage) or update.top_msg_id is not None or update.saved_peer_id is not None:
                continue  # Forum/saved-dialog drafts have a distinct scope, never overwrite the main chat.
            peer = utils.get_peer_id(update.peer)
            result[peer] = decode_draft(update.draft)
            snapshots[peer] = update.draft
        protected = getattr(self, '_protected_drafts', None)
        if protected is None:
            protected = self._protected_drafts = set()
        # Raw updates and successful saves may have changed this chat while the
        # complete snapshot was in flight. Its old flags must not replace them.
        peers = set(snapshots) | protected | set(getattr(self, '_draft_options', {}))
        for peer in peers:
            if getattr(self, '_draft_versions', {}).get(peer, 0) != versions.get(peer, 0):
                continue
            self._remember_draft_options(peer, snapshots.get(peer))
            if result.get(peer, {}).get('unsupported'):
                protected.add(peer)
            else:
                protected.discard(peer)
        return result

    async def save_draft(self, peer, text, format_spans=(), custom_spans=(), reply_to=None, *, replace_unsupported=False):
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            return True  # Never upload secret chat drafts to Telegram cloud
        if not isinstance(text, str):
            raise ValueError('Draft text must be text.')
        if reply_to is not None and (type(reply_to) is not int or not 0 < reply_to < 2**31):
            raise ValueError('Invalid draft reply.')
        entities = formatted_entities(text, format_spans, custom_spans)
        if peer in getattr(self, '_protected_drafts', ()) and not replace_unsupported:
            raise ValueError('This Telegram draft contains media or reply details. Open it in Telegram or explicitly replace it before saving a text draft.')
        locks = getattr(self, '_draft_locks', None)
        if locks is None:
            locks = self._draft_locks = {}
        state = locks.setdefault(peer, [asyncio.Lock(), 0])
        state[1] += 1
        try:
            async with asyncio.timeout(DRAFT_TIMEOUT):
                async with state[0]:
                    if peer in getattr(self, '_protected_drafts', ()) and not replace_unsupported:
                        raise ValueError('A richer Telegram draft arrived while this edit was waiting to save.')
                    version = getattr(self, '_draft_versions', {}).get(peer, 0)
                    options = getattr(self, '_draft_options', {}).get(peer, {}) if text else {}
                    request = f.messages.SaveDraftRequest(await self.client.get_input_entity(peer), text,
                        entities=entities, reply_to=t.InputReplyToMessage(reply_to) if reply_to is not None else None,
                        **options)
                    result = await self.client(request)
                    if result is False:
                        raise ValueError('Telegram did not save the draft.')
                    if getattr(self, '_draft_versions', {}).get(peer, 0) == version:
                        self._advance_draft_version(peer)
                        getattr(self, '_protected_drafts', set()).discard(peer)
                        if not text:
                            getattr(self, '_draft_options', {}).pop(peer, None)
                    return result
        finally:
            state[1] -= 1
            if not state[1]:
                locks.pop(peer, None)

    def draft_event(self, update):
        if hasattr(update, 'updates') and isinstance(update.updates, (list, tuple)):
            for item in update.updates:
                self.draft_event(item)
            return
        if hasattr(update, 'update'):
            self.draft_event(update.update)
            return
        if not isinstance(update, t.UpdateDraftMessage) or update.top_msg_id is not None or update.saved_peer_id is not None:
            return
        peer, draft = utils.get_peer_id(update.peer), decode_draft(update.draft)
        self._advance_draft_version(peer)
        self._remember_draft_options(peer, update.draft)
        protected = getattr(self, '_protected_drafts', None)
        if protected is None:
            protected = self._protected_drafts = set()
        if draft['unsupported']:
            protected.add(peer)
        else:
            protected.discard(peer)
        if self.on_change:
            self.on_change('draft', (peer, draft))

    def _advance_draft_version(self, peer):
        versions = getattr(self, '_draft_versions', None)
        if versions is None:
            versions = self._draft_versions = {}
        versions[peer] = versions.get(peer, 0) + 1

    def _remember_draft_options(self, peer, draft):
        options = getattr(self, '_draft_options', None)
        if options is None:
            options = self._draft_options = {}
        flags = {name: True for name in ('no_webpage', 'invert_media') if getattr(draft, name, False) is True}
        if flags:
            options[peer] = flags
        else:
            options.pop(peer, None)

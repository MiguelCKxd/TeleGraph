from . import APP_NAME
from .i18n import tr
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import os
import stat
import unicodedata
from .telegram_features import TelegramFeatures
from .demo_features import DemoFeatures
from .telegram_extras import TelegramExtras
from .message_tools import MessageTools
from .telegram_actions import TelegramActions
from .messaging_features import MessagingFeatures
from .bot_buttons import BotButtons
from .transfers import transfer_timeout, tracked_transfer, cancel_transfers
from .customization_sync import SyncedCustomization
from .telegram_drafts import TelegramDrafts
from .peer_tools import PeerTools
from .advanced_messaging import AdvancedMessagingMixin
from .community_management import CommunityManagement
from .forum_topics import ForumTopics


def display(text):
    """ASCII display only; never mutate text sent to Telegram. Strip controls."""
    text = unicodedata.normalize('NFKD', str(text))
    return ''.join(c if c == '\n' or 32 <= ord(c) < 127 else
                   '' if unicodedata.combining(c) else '?' for c in text)


def single_line(text):
    return display(text).replace('\n', ' ')


def attachment_path(value):
    path = Path(value).expanduser()
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(tr('Elige un archivo normal, no una carpeta.'))
    return path


@dataclass
class Chat:
    id: int
    name: str
    unread: int = 0
    pinned: bool = False
    kind: str = 'user'
    contact: bool = False
    archived: bool = False
    muted: bool = False
    emoji_status_id: int | None = None
    unread_mark: bool = False
    member: bool | None = None
    entity: object = field(default=None, repr=False, compare=False)
    forum: bool = False
    has_link: bool = False


@dataclass
class Message:
    id: int
    sender: str
    text: str
    time: str
    outgoing: bool = False
    media: object = None
    media_kind: str = ''
    filename: str = ''
    size: int = 0
    custom_emojis: tuple = ()
    raw_text: str | None = None
    entities: tuple = ()
    reply_to_id: int | None = None
    read: bool = False
    reactions: tuple = ()
    sender_id: int | None = None
    sender_color: int | None = None
    reply_icon_id: int | None = None
    reply_markup: object = None
    keyboard_applicable: bool = True
    date: datetime | None = None
    protected: bool = False
    via_bot_id: int | None = None
    service: bool = False
    forwarded: bool = False
    comments_count: int | None = None
    discussion_peer_id: int | None = None
    thread_id: int | None = None
    edited_at: datetime | None = None
    webpage: object = None  # a link preview (types.WebPage), not an attachment
    grouped_id: int | None = None
    topic_id: int | None = None


class DemoBackend(DemoFeatures):
    demo = True

    def __init__(self):
        self.init_features()
        self.messages = {
            1: [Message(1, APP_NAME, 'Demo local. Haz clic en un chat, escribe o adjunta un archivo.\nNo se envia nada a Telegram.', '12:00')],
            2: [Message(2, 'Alex', 'Ya tenemos ventana propia y chats clicables.', '12:01'),
                Message(3, tr('Tu'), 'Y un borrador distinto para cada chat.', '12:02', True)],
            3: [Message(4, 'Diseno', 'Verde sobre negro, con botones y desplazamiento.', '12:03')],
        }
        self.callback = None

    async def chats(self):
        kinds = getattr(self, 'demo_chat_kinds', {})
        return [Chat(key, name, pinned=key in self.demo_pins, kind=kinds.get(key, 'user'))
                for key in dict.fromkeys([*self.demo_pins, *self.demo_chat_names])
                for name in [self.demo_chat_names[key]]]

    async def history(self, chat_id):
        return list(self.messages[chat_id])

    async def send(self, chat_id, text):
        msg = Message(max(m.id for v in self.messages.values() for m in v) + 1,
                      tr('Tu'), text, datetime.now().strftime('%H:%M'), True)
        self.messages[chat_id].append(msg)
        self.messages[chat_id] = self.messages[chat_id][-200:]
        return msg

    async def close(self):
        pass

    async def send_batch(self,peer,paths,text='',spans=(),emojis=(),progress=None,reply_to=None,silent=False,schedule=None):
        return [await self.send_attachment(peer,path,progress,text if i==0 else '') for i,path in enumerate(paths)]

    async def send_attachment(self, chat_id, path, progress=None, caption=''):
        path = attachment_path(path)
        if progress:
            progress(path.stat().st_size, path.stat().st_size)
        return await self.send(chat_id, tr('[Archivo] ') + path.name + ('\n' + caption if caption else ''))


class TelegramBackend(ForumTopics, CommunityManagement, AdvancedMessagingMixin, PeerTools, BotButtons, TelegramFeatures, TelegramExtras, MessageTools, TelegramActions, MessagingFeatures, SyncedCustomization, TelegramDrafts):
    demo = False

    def __init__(self, client):
        from telethon import events
        from .account_profile import AccountProfile
        from .secret_chats import SecretChatManager
        self.client = client
        self.callback = None
        self.names = OrderedDict()
        self.read_max = {}
        self.on_change = None
        self.account_profile = AccountProfile(client, self._premium_changed)
        self.secret_chats = SecretChatManager(self)
        self._config_epoch = self._reaction_epoch = 0
        client.add_event_handler(self.account_event, events.Raw())
        client.add_event_handler(self.incoming, events.NewMessage())
        client.add_event_handler(self.edited_event, events.MessageEdited())
        client.add_event_handler(self.deleted_event, events.MessageDeleted())
        client.add_event_handler(self.read_event, events.MessageRead())
        client.add_event_handler(self.state_event, events.Raw())

    def _premium_changed(self, premium):
        self._config_epoch += 1
        self._reaction_epoch += 1
        if self.on_change:
            self.on_change('premium', premium)

    async def premium_enabled(self):
        await self.account_profile.ensure()
        return self.account_profile.premium

    async def refresh_account(self):
        await self.account_profile.refresh()
        return self.account_profile.snapshot()

    async def account_event(self, update):
        """Consume self entities already carried by updates without another RPC."""
        from telethon import types
        if hasattr(self, 'secret_chats') and self.secret_chats.handle_raw_update(update):
            return
        self.draft_event(update)
        identity = self.account_profile.user_id
        entities = getattr(update, '_entities', {})
        from .capability_cache import remember, consume_update
        consume_update(self, update)
        if isinstance(entities, dict):
            for entity in entities.values():
                remember(self, entity)
        own = entities.get(identity) if identity is not None and isinstance(entities, dict) else None
        updated = self.account_profile.remember(own) if own is not None else False
        if isinstance(update, types.UpdateUser) and update.user_id == identity and not updated:
            self.account_profile.invalidate()
            try:
                await self.account_profile.ensure()
            except (OSError, TimeoutError):
                pass  # Keep invalidated so the next operation can refresh it.
        elif isinstance(update, types.UpdateConfig):
            self._config_epoch += 1
            self._reaction_epoch += 1
        elif isinstance(update, types.UpdateRecentReactions):
            self._reaction_epoch += 1
        message = getattr(update, 'message', None)
        if isinstance(getattr(message, 'action', None), types.MessageActionSetChatTheme) and self.on_change:
            from telethon.utils import get_peer_id
            self.on_change('chat_theme', get_peer_id(message.peer_id))

    def cache_name(self, peer_id, name):
        if peer_id is None or not name:
            return
        self.names[peer_id] = name
        self.names.move_to_end(peer_id)
        getattr(self,'_sender_failures',{}).pop(peer_id,None)
        if len(self.names) > 4096:
            self.names.popitem(last=False)

    def visible_edit_date(self, msg):
        from telethon import utils
        peer = getattr(msg, 'peer_id', None)
        date = getattr(msg, 'edit_date', None)
        hidden = bool(getattr(msg, 'edit_hide', False))
        if peer is None:
            return None if hidden else date
        key = (utils.get_peer_id(peer), msg.id)
        known = self.__dict__.setdefault('_visible_edits', OrderedDict())
        if hidden or date is None:
            return known.get(key)
        previous = known.get(key)
        if previous is None or date > previous:
            known[key] = date
        known.move_to_end(key)
        if len(known) > 4096:
            known.popitem(last=False)
        return known[key]

    def message(self, msg):
        from telethon import types, utils
        self.remember_advanced_message(msg)
        from .messaging_features import reaction_id
        from .sender_identity import author_id,own_message,attached_author,label,display_label
        sender_id=author_id(msg)
        sender=attached_author(msg,sender_id)
        own=own_message(msg,sender_id)
        if own:name=tr('Tu')
        else:
            name=label(sender)
            if name:self.cache_name(sender_id,name)
            else:name=self.names.get(sender_id) or display_label(msg,sender_id)
        signature=getattr(msg,'post_author',None)
        if signature and not own:name+=' · '+signature
        name=' '.join(name.split())
        text = msg.raw_text or ''
        from telethon.types import MessageEntityCustomEmoji
        custom_emojis = []
        raw = None
        for entity in getattr(msg, 'entities', None) or []:
            if isinstance(entity, MessageEntityCustomEmoji):
                if raw is None:
                    raw = text.encode('utf-16-le')
                try:
                    alt = raw[entity.offset * 2:(entity.offset + entity.length) * 2].decode('utf-16-le')
                except UnicodeDecodeError: continue
                custom_emojis.append((entity.document_id, alt))
        file = getattr(msg, 'file', None)
        # Telethon exposes a link preview's photo as the message's file; the
        # preview belongs to the text, it is not an attachment.
        preview = getattr(getattr(msg, 'media', None), 'webpage', None)
        if preview is not None and type(getattr(msg, 'media', None)).__name__ == 'MessageMediaWebPage':
            file = None
        else:
            preview = None
        if file:
            filename = getattr(file, 'name', None) or tr('Archivo adjunto')
            size = getattr(file, 'size', None)
            detail = tr('[Archivo] ') + filename + (f' ({size:,} bytes)' if size is not None else '')
            text = detail + ('\n' + text if text else '')
        kind = ''
        if file:
            mime = getattr(file, 'mime_type', '') or ''
            kind = 'sticker' if getattr(msg, 'sticker', None) else 'image' if mime.startswith('image/') or getattr(msg, 'photo', None) else 'audio' if mime.startswith('audio/') or getattr(msg, 'voice', None) else 'video' if mime.startswith('video/') else 'file'
        media=getattr(msg,'media',None)
        from .advanced_messaging import advanced_media_summary
        advanced_kind,summary=advanced_media_summary(media or getattr(msg,'action',None))
        if advanced_kind:
            kind=advanced_kind;media=media or getattr(msg,'action',None)
            text=summary+('\n'+text if text else '')
        action = getattr(msg, 'action', None)
        if action is not None and not advanced_kind and not text:
            try:
                from .service_messages import service_text
                from telethon import utils as _utils
                actor = _utils.get_display_name(getattr(msg, 'sender', None)) if getattr(msg, 'sender', None) else name
                text = service_text(action, actor, getattr(msg, 'action_entities', None) or (), bool(msg.out))
            except Exception:
                text = ''
        rich=getattr(msg,'rich_message',None)
        if rich is not None:
            from .rich_articles import rich_article_text
            kind='article';media=rich
            text=rich_article_text(rich) or text or tr('Artículo')
        from .profile_customization import overlay_sender
        sender_style = overlay_sender(self, sender_id, (
            getattr(getattr(getattr(msg,'sender',None),'color',None),'color',None),
            getattr(getattr(getattr(msg,'sender',None),'color',None),'background_emoji_id',None), None))
        return Message(msg.id, name, text or tr('[Adjunto / mensaje de servicio]'),
                       msg.date.astimezone().strftime('%H:%M'), bool(msg.out),
                       media if file or advanced_kind or rich is not None else None, kind,
                       getattr(file, 'name', None) or '', getattr(file, 'size', 0) or 0, tuple(custom_emojis), text if advanced_kind or rich is not None else msg.raw_text or '', () if advanced_kind or rich is not None else tuple(getattr(msg, 'entities', None) or []),
                       getattr(getattr(msg, 'reply_to', None), 'reply_to_msg_id', None),
                       reactions=tuple((reaction_id(r.reaction),r.count,r.chosen_order is not None) for r in getattr(getattr(msg,'reactions',None),'results',[]) if reaction_id(r.reaction) is not None),
                       sender_id=sender_id,
                       sender_color=sender_style[0], reply_icon_id=sender_style[1],
                       reply_markup=getattr(msg, 'reply_markup', None),
                       keyboard_applicable=not getattr(getattr(msg,'reply_markup',None),'selective',False)
                           or bool(getattr(msg,'is_private',False) or getattr(msg,'mentioned',False)),
                       date=msg.date, edited_at=self.visible_edit_date(msg), protected=bool(getattr(msg,'noforwards',False)),
                       via_bot_id=getattr(msg,'via_bot_id',None), service=getattr(msg,'action',None) is not None,
                       forwarded=getattr(msg,'fwd_from',None) is not None,
                       comments_count=getattr(msg.replies, 'replies', 0) if getattr(getattr(msg, 'replies', None), 'comments', False) else None,
                       discussion_peer_id=utils.get_peer_id(types.PeerChannel(msg.replies.channel_id))
                           if getattr(getattr(msg, 'replies', None), 'comments', False) and getattr(msg.replies, 'channel_id', None) else None,
                       thread_id=getattr(getattr(msg, 'reply_to', None), 'reply_to_top_id', None)
                           or getattr(getattr(msg, 'reply_to', None), 'reply_to_msg_id', None),
                       webpage=preview, grouped_id=getattr(msg, 'grouped_id', None),
                       topic_id=self.forum_message_topic(msg))

    async def resolve_missing_senders(self,messages):
        from .sender_identity import resolve
        await resolve(self,messages)

    async def incoming(self, event):
        if self.callback:
            await self.resolve_missing_senders([event.message])
            self.callback(event.chat_id, self.message(event.message))

    async def chats(self):
        chats = self.secret_chats.chats() if hasattr(self, 'secret_chats') else []
        from .capability_cache import remember
        async for d in self.client.iter_dialogs(limit=None):
            remember(self, d.entity, notify=False)
            if not hasattr(self, 'read_max'): self.read_max = {}
            self.read_max[d.id] = getattr(d.dialog, 'read_outbox_max_id', 0)
            name = d.name or str(d.id)
            self.cache_name(d.id, name)
            kind = 'bot' if getattr(d.entity, 'bot', False) else 'group' if d.is_group else 'channel' if d.is_channel else 'user'
            muted_until = getattr(getattr(d.dialog, 'notify_settings', None), 'mute_until', None)
            muted = bool(muted_until and muted_until.timestamp() > datetime.now().timestamp())
            chats.append(Chat(d.id, name, d.unread_count, bool(d.pinned), kind,
                              bool(getattr(d.entity, 'contact', False)), bool(d.archived), muted, getattr(getattr(d.entity,'emoji_status',None),'document_id',None),bool(getattr(d.dialog,'unread_mark',False)),
                              member=not bool(getattr(d.entity,'left',False) or getattr(d.entity,'kicked',False)) if kind in ('group','channel') else None,
                              entity=d.entity, forum=bool(getattr(d.entity, 'forum', False)),
                              has_link=bool(getattr(d.entity, 'has_link', False))))
        return chats

    async def history(self, chat_id):
        from .secret_chats import is_secret_peer
        if is_secret_peer(chat_id):
            return self.secret_chats.history(chat_id)
        raw=await self.client.get_messages(chat_id, limit=80)
        await self.resolve_missing_senders(raw)
        messages = [self.message(m) for m in reversed(raw)]
        maximum = getattr(self, 'read_max', {}).get(chat_id, 0)
        for message in messages: message.read = message.outgoing and message.id <= maximum
        return messages

    async def send(self, chat_id, text):
        from .secret_chats import is_secret_peer
        if is_secret_peer(chat_id):
            return await self.secret_chats.send_text(chat_id, text)
        from .emoji_usage import note
        note(self, (), text)  # recently used emoji (picker)
        return self.message(await self.client.send_message(chat_id, text, parse_mode=None))

    @tracked_transfer
    async def send_attachment(self, chat_id, path, progress=None, caption=''):
        from .secret_chats import is_secret_peer
        if is_secret_peer(chat_id):
            async with transfer_timeout(progress) as report:
                return await self.secret_chats.send_file(chat_id, path, progress=report, caption=caption)
        path = attachment_path(path)
        with path.open('rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError(tr('Elige un archivo normal, no una carpeta.'))
            async with transfer_timeout(progress) as report:
                sent = await self.client.send_file(chat_id, stream, force_document=True,
                                                   parse_mode=None, progress_callback=report, caption=caption)
        return self.message(sent)

    async def start_secret_chat(self, user_peer):
        return await self.secret_chats.start_chat(user_peer)

    async def set_secret_ttl(self, peer, seconds):
        return await self.secret_chats.set_ttl(peer, seconds)

    async def secret_chat_info(self, peer):
        return self.secret_chats.chat_info(peer)

    async def rekey_secret_chat(self, peer):
        await self.secret_chats.request_rekey(peer)
        return self.secret_chats.chat_info(peer)

    async def notify_secret_screenshot(self, peer):
        await self.secret_chats.notify_screenshot(peer)

    async def discard_secret_chat(self, peer, delete_history=True):
        await self.secret_chats.discard(peer, delete_history=delete_history)

    async def close(self):
        import asyncio
        from .sticker_search import cancel_pending
        from .sender_identity import cancel_pending as cancel_senders
        try:
            secret = getattr(self, 'secret_chats', None)
            if secret is not None:
                try:
                    await asyncio.wait_for(secret.close(), 3)
                except Exception:
                    pass
            manager = getattr(self, 'call_manager', None)
            group = getattr(self, 'group_call_manager', None)
            if group is not None:
                try:
                    await asyncio.wait_for(group.close(), 7)
                except Exception:
                    pass
                finally:
                    self.group_call_manager = None
            if manager is not None:
                try:
                    await asyncio.wait_for(manager.close(), 5)
                finally:
                    self.call_manager = None
            await cancel_transfers(self)
            await asyncio.wait_for(self.presence(False),3)
        except Exception: pass  # Disconnection must still complete if status RPC fails.
        finally:
            try:
                cleanup = [cancel_pending(self), cancel_senders(self)]
                notification_cache = getattr(self, '_notification_cache', None)
                if notification_cache is not None:
                    cleanup.append(cancel_pending(notification_cache))
                catalogue = getattr(self, '_emoji_documents', None)
                if catalogue is not None:
                    cleanup.append(catalogue.cancel())
                await asyncio.gather(*cleanup)
            finally:await self.client.disconnect()

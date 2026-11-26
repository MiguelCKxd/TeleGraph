import asyncio
import tempfile
import unittest
from copy import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telethon import functions as f, types as t, utils
from tg_ascii.backend import TelegramBackend
from tg_ascii.forum_topics import message_topic
from tg_ascii.outbox import Pending, build_operation, install, with_random_ids

NOW = datetime(2026, 2, 2, tzinfo=timezone.utc)
GROUP = t.PeerChannel(100)
PEER = utils.get_peer_id(GROUP)


def channel(ident=100, **options):
    options = {'megagroup': True, 'forum': True, 'creator': True, **options}
    return t.Channel(ident, 'Community', t.ChatPhotoEmpty(), NOW, access_hash=91, **options)


def topic(ident, top=None, **values):
    return t.ForumTopic(ident, NOW, GROUP, 'General' if ident == 1 else f'Topic {ident}', 0x6FB9F0,
                        top or ident, 0, 4, 2, 0, 0, 0, t.PeerUser(9), t.PeerNotifySettings(), **values)


def message(mid, root=1, *, reply=None, peer=GROUP, **values):
    header = None
    if root != 1:
        header = t.MessageReplyHeader(forum_topic=True, reply_to_msg_id=reply or root,
                                      reply_to_top_id=root if reply and reply != root else None)
    elif reply:
        header = t.MessageReplyHeader(reply_to_msg_id=reply)
    return t.Message(mid, peer, date=NOW + timedelta(seconds=mid), message='Body', from_id=t.PeerUser(9),
                     reply_to=header, **values)


class Telegram:
    def __init__(self):
        self.entity = channel()
        self.group_full = SimpleNamespace(linked_chat_id=None)
        self.other = {}
        self.topics = {i: topic(i, i + 20) for i in (1, 10, 20)}
        self.posts = {25: message(25), 27: message(27, 10), 29: message(29, 20)}
        self.requests = []
        self.history = []
        self.deleted_batches = [0]
        self.override = {}
        self.serial = 50
        self.upload_opts = []

    def add_event_handler(self, *args):
        pass

    async def get_entity(self, peer):
        ident = utils.get_peer_id(peer)
        return self.entity if ident == utils.get_peer_id(self.entity) else self.other[ident]

    async def get_input_entity(self, peer):
        entity = await self.get_entity(peer)
        return utils.get_input_peer(entity)

    async def get_messages(self, peer, ids=None, **kwargs):
        if isinstance(ids, int):
            return self.posts.get(ids)
        return [self.posts.get(x) for x in ids]

    async def _file_to_media(self, stream, **options):
        self.upload_opts.append(options)
        data = stream.read()
        await options['progress_callback'](len(data), len(data))
        return None, t.InputMediaUploadedDocument(t.InputFile(1, 1, 'attachment', 'a'), 'application/pdf', []), None

    def _get_response_message(self, ids, updates, peer):
        return [u.message for u in updates.updates if isinstance(u, t.UpdateNewChannelMessage)]

    async def __call__(self, request):
        self.requests.append(request)
        callback = self.override.get(type(request))
        if callback:
            return await callback(request)
        if isinstance(request, f.channels.GetFullChannelRequest):
            return SimpleNamespace(chats=[self.entity], full_chat=self.group_full)
        if isinstance(request, f.messages.GetForumTopicsRequest):
            matches = [x for x in self.topics.values() if not request.q or request.q.lower() in x.title.lower()]
            start = next((i + 1 for i,x in enumerate(matches) if x.id == request.offset_topic), 0)
            return t.messages.ForumTopics(len(matches), matches[start:start+request.limit], list(self.posts.values()),
                                          [self.entity], [], 1)
        if isinstance(request, f.messages.GetForumTopicsByIDRequest):
            return SimpleNamespace(topics=[self.topics.get(i, t.ForumTopicDeleted(i)) for i in request.topics],
                                   chats=[], users=[])
        if isinstance(request, (f.messages.GetRepliesRequest, f.messages.SearchRequest, f.messages.GetScheduledHistoryRequest)):
            return SimpleNamespace(messages=self.history, chats=[], users=[])
        if isinstance(request, f.messages.ReadDiscussionRequest):
            return True
        if isinstance(request, f.messages.EditForumTopicRequest):
            row = self.topics[request.topic_id]
            for key in ('title', 'closed', 'hidden', 'icon_emoji_id'):
                v = getattr(request, key)
                if v is not None:
                    setattr(row, key, v)
        elif isinstance(request, f.messages.UpdatePinnedForumTopicRequest):
            self.topics[request.topic_id].pinned = request.pinned
        elif isinstance(request, f.messages.CreateForumTopicRequest):
            self.topics[90] = topic(90, my=True)
            self.topics[90].title = request.title
            return SimpleNamespace(updates=[t.UpdateMessageID(90, request.random_id)])
        elif isinstance(request, f.messages.DeleteTopicHistoryRequest):
            remaining = self.deleted_batches.pop(0)
            if not remaining:
                self.topics.pop(request.top_msg_id)
            return t.messages.AffectedHistory(0, 0, remaining)
        elif isinstance(request, f.channels.ToggleForumRequest):
            self.entity.forum = request.enabled
            return SimpleNamespace(chats=[self.entity])
        elif isinstance(request, f.messages.UploadMediaRequest):
            doc = t.Document(2,3,b'ref',NOW,'application/pdf',3,4,[])
            return t.MessageMediaDocument(document=doc)
        elif isinstance(request, (f.messages.SendMessageRequest, f.messages.SendMediaRequest, f.messages.SendMultiMediaRequest)):
            reply = request.reply_to
            root = 1 if not reply else reply.top_msg_id or reply.reply_to_msg_id
            ids = [x.random_id for x in request.multi_media] if hasattr(request,'multi_media') else [request.random_id]
            updates = []
            for random_id in ids:
                self.serial += 1
                post = message(self.serial, root, out=True)
                updates.extend([t.UpdateMessageID(post.id, random_id), t.UpdateNewChannelMessage(post,1,1)])
            return t.Updates(updates,[],[],NOW,1)
        return True


class ForumTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api = Telegram()
        self.be = TelegramBackend(self.api)
        self.be.resolve_missing_senders = AsyncMock()
        self.events = []
        self.be.on_change = lambda *event: self.events.append(event)

    async def test_pages_search_account_cache_and_topic_offsets(self):
        self.api.posts[30] = message(30, 10)
        page = await self.be.forum_topics(PEER, limit=2)
        self.assertEqual([r['id'] for r in page['topics']], [1,10])
        self.assertFalse(page['topics'][0]['can_delete'])
        self.assertTrue(page['topics'][0]['can_hide'])
        self.assertEqual(page['next_cursor']['offset_date'], int(self.api.posts[30].date.timestamp()))
        nxt = await self.be.forum_topics(PEER, cursor=page['next_cursor'], limit=2)
        self.assertEqual([r['id'] for r in nxt['topics']], [20])
        self.assertIsNone(nxt['next_cursor'])
        with self.assertRaises(ValueError):
            await self.be.forum_topics(PEER, query='other', cursor=page['next_cursor'])
        self.assertEqual(len((await self.be.forum_topics(PEER,query='20'))['topics']), 1)
        await self.be.forum_topics(PEER, limit=2)
        self.assertEqual(sum(isinstance(q,f.messages.GetForumTopicsRequest) for q in self.api.requests),3)
        other = TelegramBackend(Telegram())
        other.client.topics[10].title='Other account'
        self.assertEqual((await other.forum_topics(PEER,limit=2))['topics'][1]['title'],'Other account')
        self.be.forum_update(t.UpdatePinnedForumTopic(GROUP,10,True))
        await self.be.forum_topics(PEER,limit=2)
        self.assertEqual(sum(isinstance(q,f.messages.GetForumTopicsRequest) for q in self.api.requests),4)

    async def test_real_pagination_repeats_pinned_rows_and_excludes_general_from_count(self):
        self.api.topics[20].pinned=True
        async def load(q):
            ids={0:[20,10],10:[1,20],1:[]}[q.offset_topic]
            return t.messages.ForumTopics(2,[self.api.topics[i] for i in ids],[],[],[],1)
        self.api.override[f.messages.GetForumTopicsRequest]=load
        first=await self.be.forum_topics(PEER,limit=1)
        second=await self.be.forum_topics(PEER,limit=1,cursor=first['next_cursor'])
        end=await self.be.forum_topics(PEER,limit=1,cursor=second['next_cursor'])
        self.assertEqual([r['id'] for r in first['topics']+second['topics']],[20,10,1])
        self.assertEqual((end['topics'],end['next_cursor']),([],None))
        with self.assertRaises(ValueError):
            await TelegramBackend(Telegram()).forum_topics(PEER,limit=1,cursor=first['next_cursor'])

    async def test_general_history_search_scheduled_include_ordinary_replies_only(self):
        self.api.history = [message(33,20), message(31,reply=25), message(29,peer=t.PeerChannel(42)), message(25)]
        history = await self.be.forum_history(PEER,1)
        self.assertEqual([m.id for m in history],[25,31])
        self.assertTrue(all(m.topic_id==1 for m in history))
        self.assertEqual(next(q for q in self.api.requests if isinstance(q,f.messages.GetRepliesRequest)).msg_id, 1)
        matched = await self.be.forum_search(PEER,1,pinned=True)
        self.assertEqual([m.id for m in matched],[31,25])
        q=self.api.requests[-1]
        self.assertEqual(q.top_msg_id,1)
        self.assertIsInstance(q.filter,t.InputMessagesFilterPinned)
        self.assertEqual([m.id for m in await self.be.forum_scheduled(PEER,1)],[25,31])
        self.assertIsNone(message_topic(message(25,reply=9),False))

    async def test_around_required_peer_and_thread_and_older_cursor(self):
        self.api.history=[message(35,10),message(30,10),message(28,20),message(22,10)]
        page=await self.be.forum_history(PEER,10,around=27,limit=4)
        self.assertEqual([m.id for m in page],[22,27,30,35])
        self.assertEqual((page.next_offset,page.more),(22,True))
        self.assertEqual((self.api.requests[-1].msg_id,self.api.requests[-1].add_offset),(10,-2))
        self.assertFalse(await self.be.forum_history(PEER,10,around=29))
        self.assertFalse(await self.be.forum_history(PEER,10,around=404))
        self.api.posts[61]=message(61,reply=50)
        self.api.history=[message(62,reply=50),message(55,reply=40)]
        self.assertEqual([m.id for m in await self.be.discussion_around(PEER,50,61)],[61,62])
        self.assertFalse(await self.be.discussion_around(PEER,40,61))

    async def test_read_one_topic_never_acknowledges_the_whole_group(self):
        await self.be.forum_mark_read(PEER,1,55)
        await self.be.forum_mark_read(PEER,1,55)
        await self.be.forum_mark_read(PEER,10,27)
        requests=[(q.msg_id,q.read_max_id) for q in self.api.requests if isinstance(q,f.messages.ReadDiscussionRequest)]
        self.assertEqual(requests,[(1,21),(10,27)])
        self.assertIn(('forum_topics',(PEER,10)),self.events)

    async def test_reply_parent_and_general_and_wrong_topic(self):
        self.assertIsNone(await self.be.forum_reply(PEER,1))
        self.assertIsNone(await self.be.forum_reply(PEER,1,1))
        for tid,sub,expected in [(10,None,(10,None)),(10,27,(27,10)),(1,25,(25,None))]:
            result=await self.be.forum_reply(PEER,tid,sub)
            self.assertEqual((result.reply_to_msg_id,result.top_msg_id),expected)
            bytes(result)
        with self.assertRaises(ValueError): await self.be.forum_reply(PEER,10,29)
        with self.assertRaises(ValueError): await self.be.forum_reply(PEER,1,27)

    async def test_queue_retries_formatted_voice_album_and_general(self):
        install()
        item=Pending('one',PEER,'bold',format_spans=[(0,4,'bold',None)],reply_to=27,
                     topic_id=10,thread_root=10,silent=True,schedule=NOW.isoformat())
        for _ in range(2):
            await with_random_ids(item.random_ids,build_operation(self.be,item))
        sends=[q for q in self.api.requests if isinstance(q,f.messages.SendMessageRequest)]
        self.assertEqual(sends[0].random_id,sends[1].random_id)
        self.assertEqual((sends[0].reply_to.reply_to_msg_id,sends[0].reply_to.top_msg_id),(27,10))
        self.assertTrue(sends[0].silent and sends[0].schedule_date and sends[0].entities)
        with tempfile.TemporaryDirectory() as tmp:
            a,b=[Path(tmp)/name for name in ('one.ogg','two.pdf')]
            a.write_bytes(b'x'); b.write_bytes(b'yz')
            item=Pending('one',PEER,'caption',paths=[str(a)],topic_id=1,thread_root=1,voice=4,silent=True)
            sent=await build_operation(self.be,item)
            self.assertEqual(len(sent),1)
            req=self.api.requests[-1]
            self.assertIsNone(req.reply_to); self.assertEqual(req.message,'caption'); self.assertTrue(req.silent)
            self.assertTrue(self.api.upload_opts[-1]['attributes'][0].voice)
            album=Pending('one',PEER,'album',paths=[str(a),str(b)],topic_id=10,reply_to=27)
            results=await with_random_ids(album.random_ids,build_operation(self.be,album))
            self.assertEqual([r.topic_id for r in results],[10,10])
            req=self.api.requests[-1]
            self.assertEqual(req.reply_to.top_msg_id,10)
            self.assertEqual([x.message for x in req.multi_media],['album',''])
            self.assertEqual([x.random_id for x in req.multi_media],album.random_ids)

    async def test_create_edit_ack_pin_delete_and_general_guard(self):
        row=await self.be.forum_create(PEER,'Created',icon_color=0x6fb9f0)
        self.assertEqual((row['id'],row['title']),(90,'Created'))
        row=await self.be.forum_edit(PEER,90,title='Updated',closed=True)
        self.assertEqual((row['title'],row['closed']),('Updated',True))
        edit_requests=[q for q in self.api.requests if isinstance(q,f.messages.EditForumTopicRequest)]
        self.assertEqual([(q.title,q.closed) for q in edit_requests],[('Updated',None),(None,True)])
        self.assertTrue((await self.be.forum_pin(PEER,90,True))['pinned'])
        await self.be.forum_pin(PEER,90,True)
        self.assertEqual(sum(isinstance(q,f.messages.UpdatePinnedForumTopicRequest) for q in self.api.requests),1)
        await self.be.forum_edit(PEER,1,hidden=True)
        with self.assertRaises(ValueError): await self.be.forum_edit(PEER,90,hidden=True)
        with self.assertRaises(ValueError): await self.be.forum_delete(PEER,1)
        self.api.deleted_batches=[2,0]
        self.assertTrue(await self.be.forum_delete(PEER,90))
        self.assertEqual(sum(isinstance(q,f.messages.DeleteTopicHistoryRequest) for q in self.api.requests),2)
        with self.assertRaises(ValueError): await self.be.forum_topic(PEER,90)

    async def test_permissions_member_creator_closed_and_private_attachment(self):
        entity=self.api.entity
        entity.creator=False
        entity.default_banned_rights=t.ChatBannedRights(None,manage_topics=True,send_docs=True)
        with self.assertRaises(ValueError): await self.be.forum_create(PEER,'Denied')
        with self.assertRaises(ValueError): await self.be.forum_edit(PEER,10,title='Denied')
        with self.assertRaises(ValueError): await self.be.forum_pin(PEER,10,True)
        self.api.topics[10].closed=True
        with self.assertRaises(ValueError): await self.be.forum_send(PEER,10,'x')
        self.api.topics[10].my=True
        self.assertTrue((await self.be.forum_edit(PEER,10,closed=False))['can_edit'])
        self.api.history=[message(27,10,out=False)]
        with self.assertRaises(ValueError): await self.be.forum_delete(PEER,10)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'blocked.pdf';path.write_bytes(b'a')
            with self.assertRaises(ValueError): await self.be.forum_send(PEER,1,paths=[path])
        self.assertFalse(self.api.upload_opts)

    async def test_forums_can_link_to_discussions_and_toggle_only_as_owner(self):
        self.api.group_full.linked_chat_id=101
        self.api.other[utils.get_peer_id(t.PeerChannel(101))]=channel(101,megagroup=False,forum=False,broadcast=True)
        linked=await self.be.linked_discussion(PEER)
        self.assertEqual((linked['kind'],linked['peer']),('channel',-1000000000101))
        self.assertFalse((await self.be.forum_toggle(PEER,False)).forum)
        self.api.entity.creator=False
        with self.assertRaises(ValueError): await self.be.forum_toggle(PEER,True)

    async def test_updates_during_a_page_request_discard_the_stale_page(self):
        started,release=asyncio.Event(),asyncio.Event()
        attempts=0
        async def load(q):
            nonlocal attempts
            attempts+=1
            old=copy(self.api.topics[10])
            if attempts==1:
                started.set();await release.wait()
            return t.messages.ForumTopics(1,[old],[],[],[],1)
        self.api.override[f.messages.GetForumTopicsRequest]=load
        job=asyncio.create_task(self.be.forum_topics(PEER))
        await started.wait()
        self.api.topics[10].title='new'
        self.be.forum_update(t.UpdatePinnedForumTopic(GROUP,10,True));release.set()
        self.assertEqual((await job)['topics'][0]['title'],'new')
        self.assertEqual(attempts,2)

    def test_reactions_do_not_manufacture_edits_and_genuine_edit_survives(self):
        original=message(25)
        reacted=copy(original);reacted.edit_hide=True;reacted.edit_date=NOW+timedelta(minutes=2)
        self.assertIsNone(self.be.message(reacted).edited_at)
        edited=copy(original);edited.edit_date=NOW+timedelta(minutes=1)
        self.assertEqual(self.be.message(edited).edited_at,edited.edit_date)
        reacted.reactions=t.MessageReactions([t.ReactionCount(t.ReactionEmoji('👍'),2)])
        value=self.be.message(reacted)
        self.assertEqual(value.edited_at,edited.edit_date)
        self.assertEqual(value.reactions,(('👍',2,False),))
        other=copy(reacted);other.peer_id=t.PeerChannel(200)
        self.assertIsNone(self.be.message(other).edited_at)
        self.assertIsNone(TelegramBackend(Telegram()).message(reacted).edited_at)

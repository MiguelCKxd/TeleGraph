"""Bounded local patching of Telegram polls/checklists. No RPC or timers."""
from collections import OrderedDict
from copy import copy

from telethon import types as t
from telethon import utils


class AdvancedIndex:
    def __init__(self, capacity=256):
        self.capacity = capacity
        self.messages = OrderedDict()
        self.polls = {}
        self.todo_events = {}

    def discard(self, key):
        old = self.messages.pop(key, None)
        self.todo_events.pop(key, None)
        if old is not None and isinstance(old.media, t.MessageMediaPoll):
            keys = self.polls.get(old.media.poll.id)
            if keys is not None:
                keys.discard(key)
                if not keys: self.polls.pop(old.media.poll.id, None)

    def remember(self, message):
        peer = getattr(message, 'peer_id', None)
        if peer is None: return
        key = utils.get_peer_id(peer), message.id
        media = getattr(message, 'media', None)
        if not isinstance(media, (t.MessageMediaPoll, t.MessageMediaToDo)):
            self.discard(key)
            return
        watermark = self.todo_events.get(key)
        self.discard(key)
        self.messages[key] = message
        if watermark is not None: self.todo_events[key] = watermark
        if isinstance(media, t.MessageMediaPoll): self.polls.setdefault(media.poll.id, set()).add(key)
        while len(self.messages) > self.capacity: self.discard(next(iter(self.messages)))

    def patch(self, update, identity=None):
        if isinstance(update, (t.UpdateMessagePoll, t.UpdateMessagePollVote)):
            for key in tuple(self.polls.get(update.poll_id, ())):
                old = self.messages[key]
                media = copy(old.media)
                if isinstance(update, t.UpdateMessagePoll):
                    if update.poll is not None: media.poll = update.poll
                    media.results = merge_results(media.results, update.results)
                elif identity is not None and isinstance(update.peer, t.PeerUser) and update.peer.user_id == identity:
                    # Vote updates carry no aggregate counts. Only the current
                    # account's own selected options can be changed locally.
                    media.results = copy(media.results)
                    results = {item.option: copy(item) for item in media.results.results or ()}
                    for answer in media.poll.answers:
                        item = results.setdefault(answer.option, t.PollAnswerVoters(answer.option))
                        item.chosen = answer.option in update.options
                    media.results.results = list(results.values())
                else: continue
                if bytes(media) == bytes(old.media): continue
                message = copy(old); message.media = media
                self.messages[key] = message
                yield key[0], message
            return
        if isinstance(update, t.UpdateDeleteChannelMessages):
            for ident in update.messages: self.discard((-1_000_000_000_000 - update.channel_id, ident))
            return
        if isinstance(update, t.UpdateDeleteMessages):
            identifiers = set(update.messages)
            for key in tuple(self.messages):
                if key[1] in identifiers and utils.resolve_id(key[0])[1] is not t.PeerChannel: self.discard(key)
            return
        if not isinstance(update, (t.UpdateNewMessage, t.UpdateNewChannelMessage)): return
        event = update.message
        action = getattr(event, 'action', None)
        if not isinstance(action, (t.MessageActionTodoAppendTasks, t.MessageActionTodoCompletions)): return
        ident = getattr(getattr(event, 'reply_to', None), 'reply_to_msg_id', None)
        key = utils.get_peer_id(event.peer_id), ident
        old = self.messages.get(key)
        if old is None or not isinstance(old.media, t.MessageMediaToDo): return
        # Duplicate delivery/reconnect updates must not revert a more recent toggle.
        if event.id <= self.todo_events.get(key, -1): return
        media = copy(old.media)
        if isinstance(action, t.MessageActionTodoAppendTasks):
            media.todo = copy(media.todo)
            existing = {item.id for item in media.todo.list}
            media.todo.list = [*media.todo.list, *(item for item in action.list if item.id not in existing)]
        else:
            actor = getattr(event, 'from_id', None)
            if actor is None and getattr(event, 'out', False) and identity is not None: actor = t.PeerUser(identity)
            if action.completed and actor is None: return
            ids = {item.id for item in media.todo.list}
            completed = {item.id: item for item in media.completions or ()}
            for item in action.incompleted: completed.pop(item, None)
            for item in action.completed:
                if item in ids: completed[item] = t.TodoCompletion(item, actor, event.date)
            media.completions = list(completed.values())
        self.todo_events[key] = event.id
        if bytes(media) == bytes(old.media): return
        message = copy(old); message.media = media
        self.messages[key] = message
        yield key[0], message


def merge_results(previous, incoming):
    """A min result omits account-specific choices; never erase those choices."""
    result = copy(previous)
    for field in ('total_voters', 'recent_voters', 'solution', 'solution_entities', 'solution_media'):
        value = getattr(incoming, field, None)
        if value is not None: setattr(result, field, value)
    if not incoming.min:
        result.min = False
        result.has_unread_votes = incoming.has_unread_votes
        result.can_view_stats = incoming.can_view_stats
    if incoming.results is not None:
        previous_answers = {item.option: item for item in previous.results or ()}
        answers = []
        for value in incoming.results:
            item = copy(value)
            old = previous_answers.get(item.option)
            if incoming.min and old is not None:
                item.chosen = old.chosen
                if item.correct is None: item.correct = old.correct
            answers.append(item)
        result.results = answers
    return result

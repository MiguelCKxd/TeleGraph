"""Push-event correctness and strict bounds without any Telegram connection."""
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import Mock

from telethon import types as t

from tg_ascii.advanced_messaging import AdvancedMessagingMixin, poll_media, todo_media
from tg_ascii.advanced_updates import AdvancedIndex
from tg_ascii.telegram_extras import reconcile_history


def poll_message(ident=12, peer=None, poll_id=999):
    poll = poll_media('Question', ['First', 'Second']).poll
    poll.answers = [t.PollAnswer(answer.text, bytes([index])) for index, answer in enumerate(poll.answers)]
    poll.id = poll_id
    media = t.MessageMediaPoll(poll, t.PollResults(results=[
        t.PollAnswerVoters(poll.answers[0].option, chosen=True, voters=1, recent_voters=[]),
        t.PollAnswerVoters(poll.answers[1].option, chosen=False, voters=2, recent_voters=[])], total_voters=3))
    return t.Message(ident, peer or t.PeerUser(77), date=datetime.now(UTC), message='', media=media)


def checklist_message():
    return t.Message(12, t.PeerUser(77), date=datetime.now(UTC), message='',
        media=t.MessageMediaToDo(todo_media('List', [(1, 'First'), (2, 'Second')]).todo))


def todo_event(action, ident=20, peer=None, sender=None):
    return t.UpdateNewMessage(t.MessageService(ident, peer or t.PeerUser(77), datetime.now(UTC), action=action,
        from_id=sender or t.PeerUser(88), reply_to=t.MessageReplyHeader(reply_to_msg_id=12)), 1, 1)


class PushUpdates(unittest.TestCase):
    def test_unknown_poll_does_not_allocate_index_or_call_network(self):
        backend = AdvancedMessagingMixin(); backend.client = Mock(); backend.on_change = Mock()
        backend.process_advanced_update(t.UpdateMessagePoll(999, t.PollResults(total_voters=5)))
        self.assertFalse(hasattr(backend, '_advanced_index'))
        backend.client.assert_not_called(); backend.on_change.assert_not_called()

    def test_min_results_preserve_own_vote_without_mutating_snapshot(self):
        index = AdvancedIndex(); message = poll_message(); index.remember(message)
        options = [answer.option for answer in message.media.poll.answers]
        update = t.UpdateMessagePoll(999, t.PollResults(min=True, results=[
            t.PollAnswerVoters(options[0], voters=2, recent_voters=[]), t.PollAnswerVoters(options[1], voters=8, recent_voters=[])], total_voters=10))
        peer, changed = next(iter(index.patch(update)))
        self.assertEqual(peer, 77)
        self.assertTrue(changed.media.results.results[0].chosen)
        self.assertEqual(changed.media.results.total_voters, 10)
        self.assertEqual(message.media.results.total_voters, 3)
        self.assertEqual(list(index.patch(update)), [])

    def test_full_results_retract_own_vote_and_keep_optional_solution(self):
        index = AdvancedIndex(); message = poll_message(); message.media.results.solution = 'Answer'
        message.media.results.solution_entities = []
        index.remember(message)
        answer = message.media.poll.answers[0].option
        changed = next(iter(index.patch(t.UpdateMessagePoll(999, t.PollResults(results=[t.PollAnswerVoters(answer, voters=4, recent_voters=[])])))))[1]
        self.assertFalse(changed.media.results.results[0].chosen)
        self.assertEqual(changed.media.results.solution, 'Answer')

    def test_forwarded_poll_copies_update_together_but_accounts_are_isolated(self):
        first, second = AdvancedIndex(), AdvancedIndex()
        first.remember(poll_message()); first.remember(poll_message(14, t.PeerChannel(90)))
        second.remember(poll_message())
        update = t.UpdateMessagePoll(999, t.PollResults(total_voters=6), peer=t.PeerUser(77), msg_id=12)
        self.assertEqual(len(list(first.patch(update))), 2)
        self.assertEqual(second.messages[(77, 12)].media.results.total_voters, 3)

    def test_vote_event_never_invents_aggregate_counts(self):
        index = AdvancedIndex(); message = poll_message(); index.remember(message)
        answer = message.media.poll.answers[1].option
        self.assertEqual(list(index.patch(t.UpdateMessagePollVote(999, t.PeerUser(88), [answer], [1], 1), identity=77)), [])
        changed = next(iter(index.patch(t.UpdateMessagePollVote(999, t.PeerUser(77), [answer], [1], 1), identity=77)))[1]
        self.assertEqual(changed.media.results.total_voters, 3)
        self.assertEqual([value.voters for value in changed.media.results.results], [1, 2])
        self.assertEqual([bool(value.chosen) for value in changed.media.results.results], [False, True])

    def test_checklist_completions_duplicates_and_older_events(self):
        index = AdvancedIndex(); original = checklist_message(); index.remember(original)
        event = todo_event(t.MessageActionTodoCompletions([1, 999], []))
        changed = next(iter(index.patch(event)))[1]
        self.assertEqual([value.id for value in changed.media.completions], [1])
        self.assertEqual(changed.media.completions[0].completed_by, t.PeerUser(88))
        self.assertIsNone(original.media.completions)
        self.assertEqual(list(index.patch(event)), [])
        self.assertEqual(list(index.patch(todo_event(t.MessageActionTodoCompletions([], [1]), ident=19))), [])
        changed = next(iter(index.patch(todo_event(t.MessageActionTodoCompletions([], [1]), ident=21))))[1]
        self.assertEqual(changed.media.completions, [])

    def test_checklist_append_preserves_ids_and_has_no_cross_chat_effect(self):
        index = AdvancedIndex(); index.remember(checklist_message())
        event = todo_event(t.MessageActionTodoAppendTasks([t.TodoItem(3, t.TextWithEntities('Third', []))]))
        other = deepcopy(event); other.message.peer_id = t.PeerUser(99)
        self.assertEqual(list(index.patch(other)), [])
        changed = next(iter(index.patch(event)))[1]
        self.assertEqual([value.id for value in changed.media.todo.list], [1, 2, 3])
        event.message.id = 21
        self.assertEqual(list(index.patch(event)), [])

    def test_index_is_bounded_and_evicts_poll_references(self):
        index = AdvancedIndex(4)
        for ident in range(10): index.remember(poll_message(ident, poll_id=ident))
        self.assertEqual(len(index.messages), 4)
        self.assertEqual(set(index.polls), {6, 7, 8, 9})
        self.assertEqual(list(index.patch(t.UpdateMessagePoll(0, t.PollResults(total_voters=10)))), [])

    def test_deletion_respects_channel_message_id_namespace(self):
        index = AdvancedIndex(); index.remember(poll_message()); index.remember(poll_message(peer=t.PeerChannel(90)))
        list(index.patch(t.UpdateDeleteMessages([12], 1, 1)))
        self.assertEqual(set(index.messages), {(-1000000000090, 12)})
        list(index.patch(t.UpdateDeleteChannelMessages(90, [12], 1, 1)))
        self.assertFalse(index.messages); self.assertFalse(index.polls)

    def test_backend_emits_local_edit_only_and_history_reconciles_it(self):
        backend = AdvancedMessagingMixin(); backend.client = Mock(); backend.on_change = Mock()
        backend.message = lambda value: value
        original = poll_message(); backend.remember_advanced_message(original)
        backend.process_advanced_update(t.UpdateMessagePoll(999, t.PollResults(total_voters=8)))
        kind, payload = backend.on_change.call_args.args
        self.assertEqual(kind, 'advanced_media')
        changed = reconcile_history([original], [(kind, payload)], 77)[0]
        self.assertEqual(changed.media.results.total_voters, 8)
        backend.client.assert_not_called()


if __name__ == '__main__': unittest.main()

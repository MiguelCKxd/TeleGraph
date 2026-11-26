"""On-demand Telegram polls, checklists, places, contacts and Stars.

There are no startup requests, background refresh loops or payment retries here.
UI entry points gate these methods through ``advanced_features``. Telegram stays
authoritative for permissions; mutations re-read the addressed message first.
"""
import math
import secrets
import time
from copy import copy
from dataclasses import dataclass
from datetime import datetime

from telethon import functions as f
from telethon import types as t
from telethon import utils

from .i18n import tr
from .forum_topics import input_reply
from .sticker_search import cached


def plain(value):
    return value if isinstance(value, str) else getattr(value, 'text', '') or ''


def text_value(value, maximum, label):
    """Preserve valid Telegram entities supplied by an editor, including emoji."""
    result = value if isinstance(value, t.TextWithEntities) else t.TextWithEntities(str(value), [])
    if not result.text.strip() or len(result.text) > maximum:
        raise ValueError(tr('{field}: use between 1 and {maximum} characters.').format(field=label, maximum=maximum))
    return result


def config_values(config):
    value = getattr(config, 'config', config)
    return {item.key: getattr(item.value, 'value', None) for item in getattr(value, 'value', ())}


def limit(values, name, default):
    value = values.get(name, default)
    return int(value) if type(value) in (int, float) and math.isfinite(value) and 0 < value <= 1_000_000 else default


def poll_media(question, answers, *, config=None, anonymous=True, multiple=False, quiz=False,
               correct=(), solution='', close_period=None, close_date=None, open_answers=False,
               revoting=True, shuffle=False, hidden_results=False, subscribers_only=False,
               countries=(), attached_media=None, solution_media=None):
    values = config or {}
    answers = list(answers)
    maximum = limit(values, 'poll_answers_max', 12)
    if not 2 <= len(answers) <= maximum:
        raise ValueError(tr('Choose between 2 and {maximum} answers.').format(maximum=maximum))
    question = text_value(question, 300, tr('Question'))
    options = [t.InputPollAnswer(text_value(answer, 100, tr('Answer'))) for answer in answers]
    correct = list(dict.fromkeys(correct))
    if any(type(index) is not int or not 0 <= index < len(answers) for index in correct):
        raise ValueError(tr('Choose valid correct answers.'))
    if quiz and not correct or not quiz and correct:
        raise ValueError(tr('Quiz mode requires at least one correct answer.'))
    if quiz and open_answers:
        raise ValueError(tr('A quiz cannot allow participants to add answers.'))
    explanation = solution if isinstance(solution, t.TextWithEntities) else t.TextWithEntities(str(solution), [])
    if len(explanation.text) > 200 or explanation.text.count('\n') > 2:
        raise ValueError(tr('The quiz explanation allows 200 characters and two line breaks.'))
    if not quiz and (explanation.text or solution_media is not None):
        raise ValueError(tr('Explanations are available for quizzes.'))
    if close_date is not None and close_period is not None:
        raise ValueError(tr('Choose a closing date or a duration, not both.'))
    max_period = limit(values, 'poll_close_period_max', 2628000)
    if close_period is not None and (type(close_period) is not int or not 5 <= close_period <= max_period):
        raise ValueError(tr('Invalid poll duration.'))
    if close_date is not None:
        if not isinstance(close_date, datetime):
            raise ValueError(tr('Invalid closing date.'))
        seconds = close_date.timestamp() - time.time()
        if not 5 <= seconds <= max_period:
            raise ValueError(tr('Invalid closing date.'))
    countries = list(dict.fromkeys(str(country).upper().strip() for country in countries))
    if len(countries) > limit(values, 'poll_countries_max', 12) or any(
            len(country) != 2 or not country.isascii() or not country.isalpha() for country in countries):
        raise ValueError(tr('Use two-letter country codes separated by commas.'))
    poll = t.Poll(0, question, options, hash=0, public_voters=not anonymous,
                  multiple_choice=multiple, quiz=quiz, close_period=close_period, close_date=close_date,
                  open_answers=open_answers, revoting_disabled=not revoting, shuffle_answers=shuffle,
                  hide_results_until_close=hidden_results, subscribers_only=subscribers_only,
                  countries_iso2=countries or None)
    return t.InputMediaPoll(poll, correct_answers=correct if quiz else None,
                           solution=explanation.text if explanation.text else None,
                           solution_entities=explanation.entities if explanation.text else None,
                           attached_media=attached_media, solution_media=solution_media)


def todo_media(title, items, *, config=None, others_can_append=False, others_can_complete=False):
    values = config or {}
    items = list(items)
    if not 1 <= len(items) <= limit(values, 'todo_items_max', 30):
        raise ValueError(tr('The checklist has too few or too many tasks.'))
    ids, tasks = set(), []
    for ident, text in items:
        if type(ident) is not int or not 0 < ident < 2 ** 31 or ident in ids:
            raise ValueError(tr('Checklist task identifiers must be unique positive numbers.'))
        ids.add(ident)
        tasks.append(t.TodoItem(ident, text_value(text, limit(values, 'todo_item_length_max', 200), tr('Task'))))
    return t.InputMediaTodo(t.TodoList(
        text_value(title, limit(values, 'todo_title_length_max', 255), tr('Title')), tasks,
        others_can_append=others_can_append, others_can_complete=others_can_complete))


def coordinates(latitude, longitude, accuracy=None):
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (ValueError, TypeError):
        raise ValueError(tr('Enter a valid latitude and longitude.')) from None
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError(tr('Latitude must be between −90 and 90; longitude between −180 and 180.'))
    if accuracy is not None and (type(accuracy) is not int or not 0 <= accuracy <= 1500):
        raise ValueError(tr('Location accuracy must be between 0 and 1500 metres.'))
    return t.InputGeoPoint(latitude, longitude, accuracy_radius=accuracy)


def advanced_media_summary(media):
    """Readable fallback even with complex interaction disabled; never performs IO."""
    if isinstance(media, t.MessageActionConferenceCall):
        text = '📞 ' + tr('Conference call')
        if media.duration is not None:
            text += f' · {media.duration} s'
        return 'conference', text
    if isinstance(media, t.MessageMediaPoll):
        poll, results = media.poll, media.results
        counts = {entry.option: entry for entry in results.results or ()}
        lines = [('☑ ' if poll.quiz else '▤ ') + plain(poll.question)]
        for answer in poll.answers:
            result = counts.get(answer.option)
            count = getattr(result, 'voters', None)
            suffix = f' — {count}' if count is not None else ''
            lines.append(('✓ ' if getattr(result, 'chosen', False) else '○ ') + plain(answer.text) + suffix)
        if results.total_voters is not None:
            lines.append(tr('{count} votes').format(count=results.total_voters))
        if poll.closed: lines.append(tr('Closed poll'))
        if getattr(results, 'solution', None): lines.append(results.solution)
        return 'poll', '\n'.join(lines)
    if isinstance(media, t.MessageMediaToDo):
        completed = {item.id for item in media.completions or ()}
        return 'checklist', '\n'.join([plain(media.todo.title)] + [
            ('☑ ' if item.id in completed else '☐ ') + plain(item.title) for item in media.todo.list])
    if isinstance(media, (t.MessageMediaGeo, t.MessageMediaGeoLive, t.MessageMediaVenue)):
        geo = media.geo
        position = f'{geo.lat:.6f}, {geo.long:.6f}' if isinstance(geo, t.GeoPoint) else tr('Unavailable location')
        title = getattr(media, 'title', '')
        address = getattr(media, 'address', '')
        prefix = tr('Live location') if isinstance(media, t.MessageMediaGeoLive) else tr('Location')
        return 'location', '\n'.join(value for value in (prefix, title, address, position) if value)
    if isinstance(media, t.MessageMediaContact):
        return 'contact', '\n'.join((tr('Contact'), ' '.join(filter(None, (media.first_name, media.last_name))), media.phone_number))
    if isinstance(media, (t.MessageActionStarGift, t.MessageActionStarGiftUnique)):
        gift = media.gift
        title = getattr(gift, 'title', None) or tr('Telegram gift')
        number = getattr(gift, 'num', None)
        if number is not None: title += f' #{number}'
        return 'gift', title + ('\n' + plain(media.message) if getattr(media, 'message', None) else '')
    if isinstance(media, (t.MessageActionGiftStars, t.MessageActionGiftPremium, t.MessageActionGiftCode)):
        stars, months = getattr(media, 'stars', None), getattr(media, 'months', None)
        return 'gift', tr('{count} Telegram Stars').format(count=stars) if stars is not None else tr('Telegram Premium · {months} months').format(months=months)
    return '', ''


def todo_fingerprint(todo):
    """Completion events are independent of edits; IDs and structure are not."""
    return bytes(todo)


@dataclass(frozen=True)
class StarsQuote:
    token: str
    title: str
    amount: int
    recipient: str
    expires: float


class AdvancedMessagingMixin:
    def remember_advanced_message(self, message):
        from .advanced_updates import AdvancedIndex
        index = getattr(self, '_advanced_index', None)
        if index is None:
            if not isinstance(getattr(message, 'media', None), (t.MessageMediaPoll, t.MessageMediaToDo)): return
            self._advanced_index = index = AdvancedIndex()
        index.remember(message)

    def process_advanced_update(self, update):
        index = getattr(self, '_advanced_index', None)
        if index is None: return
        identity = getattr(getattr(self, 'account_profile', None), 'user_id', None)
        for peer, message in index.patch(update, identity):
            if getattr(self, 'on_change', None): self.on_change('advanced_media', (peer, self.message(message)))

    async def advanced_config(self):
        return config_values(await self.app_config())

    async def _structured_sent(self, request):
        updates = await self.client(request)
        messages = [update.message for update in getattr(updates, 'updates', ())
                    if isinstance(update, (t.UpdateNewMessage, t.UpdateNewChannelMessage, t.UpdateNewScheduledMessage))]
        mapping = next((update.id for update in getattr(updates, 'updates', ())
                        if isinstance(update, t.UpdateMessageID) and update.random_id == request.random_id), None)
        if mapping is not None:
            messages = [message for message in messages if message.id == mapping]
        peer_id = (getattr(getattr(self, 'account_profile', None), 'user_id', None)
                   if isinstance(request.peer, t.InputPeerSelf) else utils.get_peer_id(request.peer))
        messages = [message for message in messages if peer_id is not None and utils.get_peer_id(message.peer_id) == peer_id]
        if len(messages) == 1:
            await self.resolve_missing_senders(messages)
            return self.message(messages[0])
        # An acknowledged update with no message is not permission to re-send.
        return None

    async def _send_structured(self, peer, media, *, reply_to=None, silent=False, schedule=None):
        request = f.messages.SendMediaRequest(
            await self.client.get_input_entity(peer), media, '', silent=silent,
            reply_to=input_reply(reply_to),
            schedule_date=schedule)
        return await self._structured_sent(request)

    async def _poll_target(self, peer):
        target = await self.client.get_input_entity(peer)
        if isinstance(target, (t.InputPeerUser, t.InputPeerUserFromMessage)):
            user = await self.client.get_entity(target)
            # Bot request-poll keyboards explicitly operate in private chats.
            # Ordinary person-to-person polls are rejected by Telegram.
            if not (getattr(user, 'bot', False) or getattr(user, 'is_self', False)):
                raise ValueError(tr('Choose a group or channel.'))
        return target

    async def prepare_poll_attachments(self, peer, question, answers, files, *, progress=None, **options):
        from .poll_attachments import inspect_poll_files, upload_poll_files
        # Validate server limits and the destination before uploading anything.
        pending = {key: t.InputMediaEmpty() for key in files}
        target = await self._poll_target(peer)
        poll_media(question, answers, config=await self.advanced_config(), **(options | pending))
        inspected = await inspect_poll_files(files)
        return await upload_poll_files(self, target, inspected, progress)

    async def send_poll(self, peer, question, answers, *, reply_to=None, silent=False, schedule=None, **options):
        target = await self._poll_target(peer)
        media = poll_media(question, answers, config=await self.advanced_config(), **options)
        return await self._send_structured(target, media, reply_to=reply_to, silent=silent, schedule=schedule)

    async def _checked_media(self, peer, ident, cls):
        message = await self.checked_message(peer, ident)
        if not isinstance(message.media, cls):
            raise ValueError(tr('This message is no longer available in this form.'))  # noqa: TRY004 - the remote message changed
        return message

    async def _advanced_refreshed(self, peer, ident):
        message = await self.checked_message(peer, ident)
        await self.resolve_missing_senders([message])
        return self.message(message)

    async def poll_state(self, peer, ident):
        message = await self._checked_media(peer, ident, t.MessageMediaPoll)
        return message.media, bool(message.out or message.media.poll.creator)

    async def _can_vote(self, message):
        poll = message.media.poll
        if poll.closed:
            raise ValueError(tr('This poll is closed.'))
        if poll.countries_iso2:
            values = await self.advanced_config()
            if values.get('phone_country_iso2') not in poll.countries_iso2:
                raise ValueError(tr('Voting is restricted to the countries selected by the poll creator.'))
        if poll.subscribers_only:
            original = getattr(getattr(message, 'fwd_from', None), 'from_id', None) or message.peer_id
            channel = await self.client.get_entity(original)
            if not isinstance(channel, t.Channel) or channel.left:
                raise ValueError(tr('Only eligible channel subscribers can vote.'))
            result = await self.client(f.channels.GetParticipantRequest(channel, t.InputPeerSelf()))
            joined = getattr(result.participant, 'date', None)
            created = getattr(getattr(message, 'fwd_from', None), 'date', None) or message.date
            if joined is not None and (created - joined).total_seconds() < 86400:
                raise ValueError(tr('You must have joined 24 hours before this poll was posted.'))

    async def vote_poll(self, peer, ident, options):
        message = await self._checked_media(peer, ident, t.MessageMediaPoll)
        await self._can_vote(message)
        poll = message.media.poll
        selected = list(dict.fromkeys(options))
        allowed = {answer.option for answer in poll.answers}
        if any(option not in allowed for option in selected) or (not poll.multiple_choice and len(selected) > 1):
            raise ValueError(tr('Choose valid poll answers.'))
        chosen = any(result.chosen for result in message.media.results.results or ())
        if chosen and (poll.quiz or poll.revoting_disabled):
            raise ValueError(tr('This poll does not allow changing or retracting your vote.'))
        await self.client(f.messages.SendVoteRequest(await self.client.get_input_entity(peer), ident, selected))
        return await self._advanced_refreshed(peer, ident)

    async def poll_voters(self, peer, ident, option=None, offset=''):
        message = await self._checked_media(peer, ident, t.MessageMediaPoll)
        if not message.media.poll.public_voters:
            raise ValueError(tr('This poll is anonymous.'))
        if option is not None and option not in {item.option for item in message.media.poll.answers}:
            raise ValueError(tr('This answer no longer exists.'))
        result = await self.client(f.messages.GetPollVotesRequest(
            await self.client.get_input_entity(peer), ident, 50, option=option, offset=offset or None))
        names = {utils.get_peer_id(item): utils.get_display_name(item) for item in [*result.users, *result.chats]}
        rows = []
        labels = {answer.option: plain(answer.text) for answer in message.media.poll.answers}
        for vote in result.votes:
            ident = utils.get_peer_id(vote.peer)
            options = getattr(vote, 'options', None) or ([vote.option] if hasattr(vote, 'option') else [])
            rows.append((ident, names.get(ident, str(ident)), [labels.get(option, '') for option in options]))
        return rows, getattr(result, 'next_offset', None)

    async def close_poll(self, peer, ident):
        message = await self._checked_media(peer, ident, t.MessageMediaPoll)
        poll = copy(message.media.poll)
        if not (message.out or poll.creator):
            # Admin rights may permit closing polls; the server resolves that case.
            permissions = await self.client.get_permissions(peer, 'me')
            if not (getattr(permissions, 'is_admin', False) or getattr(permissions, 'is_creator', False)):
                raise ValueError(tr('You cannot close this poll.'))
        if not poll.closed:
            poll.closed = True
            await self.client(f.messages.EditMessageRequest(await self.client.get_input_entity(peer), ident,
                                                            media=t.InputMediaPoll(poll)))
        return await self._advanced_refreshed(peer, ident)

    async def append_poll_answer(self, peer, ident, text, media=None):
        message = await self._checked_media(peer, ident, t.MessageMediaPoll)
        if not message.media.poll.open_answers or message.media.poll.closed:
            raise ValueError(tr('This poll does not accept new answers.'))
        values = await self.advanced_config()
        if len(message.media.poll.answers) >= limit(values, 'poll_answers_max', 12):
            raise ValueError(tr('This poll has reached its answer limit.'))
        answer = t.InputPollAnswer(text_value(text, 100, tr('Answer')), media=media)
        await self.client(f.messages.AddPollAnswerRequest(await self.client.get_input_entity(peer), ident, answer))
        return await self._advanced_refreshed(peer, ident)

    async def delete_poll_answer(self, peer, ident, option):
        message = await self._checked_media(peer, ident, t.MessageMediaPoll)
        if not message.media.poll.open_answers or message.media.poll.closed:
            raise ValueError(tr('This poll does not accept changes to its answers.'))
        if option not in {answer.option for answer in message.media.poll.answers}:
            raise ValueError(tr('This answer no longer exists.'))
        # The server checks creator/answer-author identity and the deletion period.
        await self.client(f.messages.DeletePollAnswerRequest(await self.client.get_input_entity(peer), ident, option))
        return await self._advanced_refreshed(peer, ident)

    async def send_checklist(self, peer, title, items, *, reply_to=None, silent=False, schedule=None, **options):
        if not await self.premium_enabled():
            raise ValueError(tr('Creating checklists requires Telegram Premium.'))
        media = todo_media(title, items, config=await self.advanced_config(), **options)
        return await self._send_structured(peer, media, reply_to=reply_to, silent=silent, schedule=schedule)

    async def checklist_state(self, peer, ident):
        message = await self._checked_media(peer, ident, t.MessageMediaToDo)
        return message.media, bool(message.out)

    async def toggle_checklist(self, peer, ident, item_id, completed):
        message = await self._checked_media(peer, ident, t.MessageMediaToDo)
        if not (message.out or message.media.todo.others_can_complete):
            raise ValueError(tr('The checklist author does not allow others to complete tasks.'))
        if item_id not in {item.id for item in message.media.todo.list}:
            raise ValueError(tr('This task no longer exists.'))
        await self.client(f.messages.ToggleTodoCompletedRequest(
            await self.client.get_input_entity(peer), ident,
            [item_id] if completed else [], [] if completed else [item_id]))
        return await self._advanced_refreshed(peer, ident)

    async def append_checklist(self, peer, ident, texts):
        message = await self._checked_media(peer, ident, t.MessageMediaToDo)
        todo = message.media.todo
        if not (message.out or todo.others_can_append):
            raise ValueError(tr('The checklist author does not allow others to add tasks.'))
        values = await self.advanced_config()
        texts = list(texts)
        if not texts or len(todo.list) + len(texts) > limit(values, 'todo_items_max', 30):
            raise ValueError(tr('The checklist has too few or too many tasks.'))
        # Fresh IDs prevent accidentally completing a removed and re-added task.
        used = {item.id for item in todo.list}
        tasks = []
        for text in texts:
            ident_new = secrets.randbelow(2 ** 31 - 1) + 1
            while ident_new in used: ident_new = secrets.randbelow(2 ** 31 - 1) + 1
            used.add(ident_new)
            tasks.append(t.TodoItem(ident_new, text_value(text, limit(values, 'todo_item_length_max', 200), tr('Task'))))
        await self.client(f.messages.AppendTodoListRequest(await self.client.get_input_entity(peer), ident, tasks))
        return await self._advanced_refreshed(peer, ident)

    async def edit_checklist(self, peer, ident, title, items, snapshot, **options):
        message = await self._checked_media(peer, ident, t.MessageMediaToDo)
        if not message.out:
            raise ValueError(tr('Only the checklist author can edit its structure.'))
        if todo_fingerprint(message.media.todo) != snapshot:
            raise ValueError(tr('This checklist changed on another device. Reopen the editor.'))
        media = todo_media(title, items, config=await self.advanced_config(), **options)
        await self.client(f.messages.EditMessageRequest(await self.client.get_input_entity(peer), ident, media=media))
        return await self._advanced_refreshed(peer, ident)

    async def send_location(self, peer, latitude, longitude, *, accuracy=None, period=None,
                            title='', address='', reply_to=None):
        point = coordinates(latitude, longitude, accuracy)
        if period is not None:
            if type(period) is not int or not (60 <= period <= 86400 or period == 2 ** 31 - 1):
                raise ValueError(tr('Invalid live location duration.'))
            media = t.InputMediaGeoLive(point, period=period)
        elif title:
            media = t.InputMediaVenue(point, str(title).strip(), str(address).strip(), '', '', '')
        else:
            media = t.InputMediaGeoPoint(point)
        return await self._send_structured(peer, media, reply_to=reply_to)

    async def edit_location(self, peer, ident, latitude=None, longitude=None, *, stop=False):
        message = await self._checked_media(peer, ident, t.MessageMediaGeoLive)
        if not message.out: raise ValueError(tr('Only your own live location can be changed.'))
        if stop:
            media = t.InputMediaGeoLive(t.InputGeoPointEmpty(), stopped=True)
        else:
            media = t.InputMediaGeoLive(coordinates(latitude, longitude))
        await self.client(f.messages.EditMessageRequest(await self.client.get_input_entity(peer), ident, media=media))
        return await self._advanced_refreshed(peer, ident)

    async def send_contact_card(self, peer, first, last, phone, *, vcard='', reply_to=None):
        from .auth import normalize_phone
        if not str(first).strip(): raise ValueError(tr('El nombre es obligatorio.'))
        if len(first) > 255 or len(last) > 255 or len(vcard.encode('utf-8')) > 2048:
            raise ValueError(tr('This contact card is too long.'))
        card = t.InputMediaContact(normalize_phone(phone), first.strip(), last.strip(), vcard)
        return await self._send_structured(peer, card, reply_to=reply_to)

    async def gift_catalogue(self):
        return await cached(self, ('advanced-gifts',),
                            lambda: self.client(f.payments.GetStarGiftsRequest(hash=0)), ttl=60)

    async def profile_gifts(self, peer, offset='', *, include_hidden=False):
        return await self.client(f.payments.GetSavedStarGiftsRequest(
            await self.client.get_input_entity(peer), str(offset), 30, exclude_unsaved=not include_hidden))

    async def gift_visibility(self, stargift, visible):
        return await self.client(f.payments.SaveStarGiftRequest(stargift, unsave=not visible))

    async def stars_balance(self):
        return await self.client(f.payments.GetStarsStatusRequest(t.InputPeerSelf()))

    async def _prepare_stars_invoice(self, invoice, title, recipient):
        form = await self.client(f.payments.GetPaymentFormRequest(invoice))
        bill = getattr(form, 'invoice', None)
        if bill is None or bill.currency != 'XTR' or getattr(bill, 'recurring', False):
            raise ValueError(tr('This payment must be completed through Telegram’s official purchase page.'))
        amount = sum(item.amount for item in bill.prices)
        if type(amount) is not int or amount <= 0:
            raise ValueError(tr('Telegram returned an invalid payment amount.'))
        return self._remember_payment(title, amount, recipient, ('invoice', form.form_id, invoice))

    def _remember_payment(self, title, amount, recipient, operation):
        pending = getattr(self, '_advanced_payment_quotes', None)
        if pending is None: pending = self._advanced_payment_quotes = {}
        now = time.monotonic()
        for token in list(pending):
            if pending[token][0].expires <= now: pending.pop(token, None)
        while len(pending) >= 8: pending.pop(next(iter(pending)))
        quote = StarsQuote(secrets.token_urlsafe(24), title, amount, recipient, now + 120)
        pending[quote.token] = quote, operation
        return quote

    async def prepare_gift(self, peer, gift_id, *, message='', hide_name=False, include_upgrade=False):
        values = await self.advanced_config()
        if values.get('stargifts_blocked') is True:
            raise ValueError(tr('Telegram has disabled gift purchases for this account.'))
        catalogue = await self.gift_catalogue()
        gift = next((item for item in catalogue.gifts if item.id == gift_id), None)
        if gift is None or getattr(gift, 'sold_out', False) or getattr(gift, 'auction', False):
            raise ValueError(tr('This gift is unavailable for a direct purchase.'))
        if getattr(gift, 'limited_per_user', False) and (gift.per_user_remains or 0) <= 0:
            raise ValueError(tr('You have reached the purchase limit for this gift.'))
        if getattr(gift, 'require_premium', False) and not await self.premium_enabled():
            raise ValueError(tr('This gift requires Telegram Premium.'))
        if getattr(gift, 'locked_until_date', None):
            check = await self.client(f.payments.CheckCanSendGiftRequest(gift_id))
            if isinstance(check, t.payments.CheckCanSendGiftResultFail):
                raise ValueError(plain(check.reason))
        text = None
        if plain(message): text = text_value(message, limit(values, 'stargifts_message_length_max', 255), tr('Message'))
        entity = await self.client.get_entity(peer)
        invoice = t.InputInvoiceStarGift(await self.client.get_input_entity(entity), gift_id,
                                        hide_name=hide_name, include_upgrade=include_upgrade, message=text)
        return await self._prepare_stars_invoice(invoice, getattr(gift, 'title', None) or tr('Telegram gift'), utils.get_display_name(entity))

    async def prepare_premium_gift(self, peer, months, message=''):
        if months not in (3, 6, 12): raise ValueError(tr('Choose 3, 6 or 12 months.'))
        entity = await self.client.get_entity(peer)
        text = text_value(message, 255, tr('Message')) if plain(message) else None
        invoice = t.InputInvoicePremiumGiftStars(utils.get_input_user(entity), months, message=text)
        return await self._prepare_stars_invoice(invoice, tr('Telegram Premium · {months} months').format(months=months), utils.get_display_name(entity))

    async def paid_reaction_options(self, peer, ident):
        await self.checked_message(peer, ident)
        entity = await self.client.get_entity(peer)
        if not isinstance(entity, t.Channel) or not entity.broadcast:
            raise ValueError(tr('Star reactions are available on channel posts.'))
        response = await self.client(f.channels.GetFullChannelRequest(entity))
        if not getattr(response.full_chat, 'paid_reactions_available', False):
            raise ValueError(tr('This channel has disabled Star reactions.'))
        values = await self.advanced_config()
        return entity, limit(values, 'stars_paid_reaction_amount_max', 2500)

    async def prepare_paid_reaction(self, peer, ident, count, *, anonymous=False):
        entity, maximum = await self.paid_reaction_options(peer, ident)
        if type(count) is not int or not 1 <= count <= maximum:
            raise ValueError(tr('Choose between 1 and {maximum} Stars.').format(maximum=maximum))
        privacy = t.PaidReactionPrivacyAnonymous() if anonymous else t.PaidReactionPrivacyPeer(t.InputPeerSelf())
        operation = ('reaction', await self.client.get_input_entity(entity), ident, count, privacy)
        return self._remember_payment(tr('Star reaction'), count, utils.get_display_name(entity), operation)

    async def commit_stars_payment(self, token, *, confirmed_amount):
        """A quote can be consumed once; errors never trigger a second charge."""
        pending = getattr(self, '_advanced_payment_quotes', {})
        record = pending.get(token)
        if record is None or record[0].expires <= time.monotonic():
            pending.pop(token, None)
            raise ValueError(tr('This payment confirmation expired. Review the price again.'))
        quote, operation = record
        if type(confirmed_amount) is not int or confirmed_amount != quote.amount:
            raise ValueError(tr('Confirm the exact amount shown by Telegram.'))
        pending.pop(token)
        if operation[0] == 'invoice':
            return await self.client(f.payments.SendStarsFormRequest(operation[1], operation[2]))
        _, peer, ident, count, privacy = operation
        # Unlike other Telegram random IDs, paid reactions include Unix seconds.
        random_id = (int(time.time()) << 32) | secrets.randbits(32)
        if random_id >= 2 ** 63: random_id -= 2 ** 64
        return await self.client(f.messages.SendPaidReactionRequest(peer, ident, count, random_id=random_id, private=privacy))

    def discard_stars_quote(self, token):
        getattr(self, '_advanced_payment_quotes', {}).pop(token, None)

    async def convert_received_gift(self, stargift):
        return await self.client(f.payments.ConvertStarGiftRequest(stargift))

    async def saved_gift_reference(self, record, peer='me'):
        """Personal gift message IDs and channel saved IDs are different namespaces."""
        input_peer = await self.client.get_input_entity(peer)
        if isinstance(input_peer, t.InputPeerChannel):
            if record.saved_id is None: raise ValueError(tr('This gift has no channel reference.'))
            return t.InputSavedStarGiftChat(input_peer, record.saved_id)
        if record.msg_id is None: raise ValueError(tr('This gift has no message reference.'))
        return t.InputSavedStarGiftUser(record.msg_id)

    async def prepare_gift_upgrade(self, record, peer='me', *, keep_original=True):
        reference = await self.saved_gift_reference(record, peer)
        invoice = t.InputInvoiceStarGiftUpgrade(reference, keep_original_details=keep_original)
        return await self._prepare_stars_invoice(invoice, tr('Upgrade gift'), tr('My gifts'))

    async def prepare_gift_transfer(self, record, target, peer='me'):
        reference = await self.saved_gift_reference(record, peer)
        entity = await self.client.get_entity(target)
        invoice = t.InputInvoiceStarGiftTransfer(reference, await self.client.get_input_entity(entity))
        return await self._prepare_stars_invoice(invoice, tr('Transfer gift'), utils.get_display_name(entity))

    async def transfer_free_gift(self, record, target, peer='me'):
        if record.transfer_stars not in (None, 0): raise ValueError(tr('Review this gift’s transfer price first.'))
        return await self.client(f.payments.TransferStarGiftRequest(
            await self.saved_gift_reference(record, peer), await self.client.get_input_entity(target)))

    async def upgrade_prepaid_gift(self, record, peer='me', *, keep_original=True):
        if record.upgrade_stars not in (None, 0) or not record.can_upgrade:
            raise ValueError(tr('Review this gift’s upgrade price first.'))
        return await self.client(f.payments.UpgradeStarGiftRequest(
            await self.saved_gift_reference(record, peer), keep_original_details=keep_original))

    async def resale_gifts(self, gift_id, offset='', *, by_price=True):
        return await self.client(f.payments.GetResaleStarGiftsRequest(gift_id, offset, 30,
                                                                    sort_by_price=by_price, stars_only=True))

    async def prepare_resale_gift(self, slug, peer):
        if not isinstance(slug, str) or not slug or len(slug) > 160:
            raise ValueError(tr('Invalid collectible gift link.'))
        entity = await self.client.get_entity(peer)
        invoice = t.InputInvoiceStarGiftResale(slug, await self.client.get_input_entity(entity))
        return await self._prepare_stars_invoice(invoice, tr('Collectible gift') + ' · ' + slug, utils.get_display_name(entity))

    async def send_article(self, peer, source, *, format='markdown', rtl=False, noautolink=False, reply_to=None):
        from .rich_articles import article_input
        rich = article_input(source, format=format, rtl=rtl, noautolink=noautolink)
        request = f.messages.SendMessageRequest(await self.client.get_input_entity(peer), '', rich_message=rich,
                                                reply_to=input_reply(reply_to))
        return await self._structured_sent(request)

    async def article_state(self, peer, ident):
        message = await self.checked_message(peer, ident)
        rich = getattr(message, 'rich_message', None)
        if rich is None: raise ValueError(tr('This message is not an article.'))
        if rich.part: rich = await self._complete_article(peer, ident)
        return rich, bool(message.out)

    async def _complete_article(self, peer, ident):
        result = await self.client(f.messages.GetRichMessageRequest(await self.client.get_input_entity(peer), ident))
        message = next((item for item in getattr(result, 'messages', ()) if item.id == ident), None)
        rich = getattr(message, 'rich_message', None)
        if rich is None or rich.part:
            raise ValueError(tr('Telegram did not return the complete article. Try refreshing it.'))
        return rich

    async def edit_article(self, peer, ident, rich, snapshot):
        from .rich_articles import editable_article
        message = await self.checked_message(peer, ident)
        original = getattr(message, 'rich_message', None)
        if original is None or not message.out: raise ValueError(tr('Only your own articles can be edited.'))
        if original.part: original = await self._complete_article(peer, ident)
        if bytes(original) != snapshot:
            raise ValueError(tr('This article changed on another device. Reopen the editor.'))
        if isinstance(rich, t.RichMessage): rich = editable_article(rich)
        if not isinstance(rich, (t.InputRichMessage, t.InputRichMessageHTML, t.InputRichMessageMarkdown)):
            raise TypeError(tr('Invalid article content.'))
        await self.client(f.messages.EditMessageRequest(await self.client.get_input_entity(peer), ident, rich_message=rich))
        return await self._advanced_refreshed(peer, ident)

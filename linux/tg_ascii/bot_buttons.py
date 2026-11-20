"""Bot keyboards: retain Telegram rows and validate buttons again before use."""
from telethon import types, functions, utils
from .i18n import tr
from .links import browser_url


KINDS = {'KeyboardButton': 'text', 'KeyboardButtonCallback': 'callback',
         'KeyboardButtonUrl': 'url', 'KeyboardButtonWebView': 'webview',
         'KeyboardButtonSimpleWebView': 'simplewebview', 'KeyboardButtonCopy': 'copy',
         'ButtonTypeDefault': 'text', 'InlineButtonTypeCallback': 'callback',
         'InlineButtonTypeUrl': 'url', 'InlineButtonTypeWebView': 'webview',
         'ButtonTypeSimpleWebView': 'simplewebview', 'InlineButtonTypeCopy': 'copy',
         'KeyboardButtonGame': 'game', 'InlineButtonTypeGame': 'game',
         'KeyboardButtonUserProfile': 'profile', 'InlineButtonTypeUserProfile': 'profile',
         'KeyboardButtonRequestPhone': 'phone', 'ButtonTypeRequestPhone': 'phone',
         'KeyboardButtonRequestGeoLocation': 'locations', 'ButtonTypeRequestGeoLocation': 'locations',
         'KeyboardButtonRequestPoll': 'polls', 'ButtonTypeRequestPoll': 'polls'}


def button_action(button):
    # Telegram 1.45's layer separates the caption from its button action.
    action = getattr(button, 'type', button)
    return KINDS.get(type(action).__name__), action


def button_supported(button):
    kind, action = button_action(button)
    return kind is not None and not getattr(action, 'requires_password', False)


def button_available(button, capabilities, *, phone_available=True):
    """Presentation-only filtering; keep the original Telegram row/column IDs."""
    if not button_supported(button) or not capabilities.readable:
        return False
    kind, action = button_action(button)
    if kind in ('url', 'webview', 'simplewebview'):
        try:
            browser_url(action.url)
        except (AttributeError, TypeError, ValueError):
            return False
    if kind == 'text':
        return capabilities.allows('send')
    if kind in ('phone', 'locations', 'polls'):
        if capabilities.kind != 'bot':
            return False  # Telegram requests contact/location/poll in private bot chats.
        permission = {'phone': 'contact', 'locations': 'location', 'polls': 'poll'}[kind]
        return capabilities.allows(permission) and (kind != 'phone' or phone_available)
    # Inline callbacks, links, copies and games can also occur in read-only
    # channels/groups: they do not require permission to post a message.
    return True


def keyboard_message(messages, previous=None):
    """An older history page must not resurrect a keyboard removed by the bot."""
    result = previous
    for message in messages:
        markup = getattr(message, 'reply_markup', None)
        if isinstance(markup, (types.ReplyKeyboardMarkup, types.ReplyKeyboardHide, types.ReplyKeyboardForceReply)):
            if getattr(message, 'keyboard_applicable', True) and (result is None or message.id >= result.id):
                result = message
    return result


class BotButtons:
    async def activate_bot_button(self, peer, message_id, row, column, expected, *, phone_consent=None):
        message = await self.client.get_messages(peer, ids=message_id)
        if not message or utils.get_peer_id(message.peer_id) != peer:
            raise ValueError(tr('This bot button is no longer available.'))
        try:
            if row < 0 or column < 0: raise IndexError
            button = message.reply_markup.rows[row].buttons[column]
            if bytes(button) != expected: raise IndexError
        except (AttributeError, IndexError):
            raise ValueError(tr('This bot button is no longer available.')) from None
        if not button_supported(button):
            raise ValueError(tr('This button requires a feature not yet supported in Tg-As.'))
        kind, action = button_action(button)
        if kind == 'text':
            sent = await self.client.send_message(peer, button.text, parse_mode=None, reply_to=message_id)
            return {'message': self.message(sent)}
        if kind in ('callback', 'game'):
            answer = await self.client(functions.messages.GetBotCallbackAnswerRequest(
                peer, message_id, data=action.data if kind == 'callback' else None, game=kind == 'game'))
            return {'notice': answer.message, 'alert': answer.alert, 'url': answer.url}
        if kind == 'url':
            return {'url': browser_url(action.url)}
        if kind == 'copy': return {'copy': action.copy_text}
        if kind == 'profile': return {'profile': action.user_id}
        if kind in ('locations', 'polls'):
            return {'compose': kind, 'reply_to': message_id, 'quiz': getattr(action, 'quiz', None)}
        if kind == 'phone':
            sender = await message.get_sender()
            if not getattr(sender, 'bot', False) or not isinstance(message.peer_id, types.PeerUser):
                raise ValueError(tr('Choose a bot first.'))
            me = await self.client.get_me()
            phone = getattr(me, 'phone', None)
            if not phone:
                raise ValueError(tr('Your phone number is not available.'))
            card = {'phone': str(phone), 'first': getattr(me, 'first_name', '') or tr('Cuenta'),
                    'last': getattr(me, 'last_name', '') or '',
                    'recipient': utils.get_display_name(sender) or '@' + (getattr(sender, 'username', '') or str(peer))}
            if phone_consent != card['phone']:
                # Preparation never sends. Consent covers the exact displayed
                # number, and this second call revalidates the original button.
                return {'request_phone': card}
            sent = await self.send_contact_card(peer, card['first'], card['last'], card['phone'], reply_to=message_id)
            return {'message': sent}
        sender = await message.get_sender()
        if not getattr(sender, 'bot', False):
            raise ValueError(tr('Choose a bot first.'))
        bot = utils.get_input_user(await self.client.get_input_entity(sender))
        url = browser_url(action.url)
        if kind == 'simplewebview':
            answer = await self.client(functions.messages.RequestSimpleWebViewRequest(bot, 'web', url=url))
        else:
            answer = await self.client(functions.messages.RequestWebViewRequest(peer, bot, 'web', url=url))
        return {'url': browser_url(answer.url)}

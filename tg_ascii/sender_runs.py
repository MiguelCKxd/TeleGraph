"""Group consecutive messages of one author, as Telegram does in groups.

Within a run the author's name appears only on the first message and the
author's picture only beside the last one. Shared by desktop and mobile.
"""

# Telegram Desktop attaches a message to the previous one within 15 minutes.
ATTACH_SECONDS = 900


def _attachable(previous, current, header):
    if previous is None or header:
        return False
    if previous.outgoing != current.outgoing or previous.sender_id != current.sender_id:
        return False
    if getattr(previous, 'service', False) or getattr(current, 'service', False):
        return False
    if previous.sender_id is None:
        return False
    first, second = getattr(previous, 'date', None), getattr(current, 'date', None)
    if first is not None and second is not None:
        return abs((second - first).total_seconds()) <= ATTACH_SECONDS
    return True


def positions(messages, headers=None):
    """[(first_in_run, last_in_run)] aligned with ``messages``.

    ``headers`` are the day separators drawn before each message; a separator
    always breaks a run.
    """
    messages = list(messages)
    headers = list(headers) if headers is not None else [None] * len(messages)
    joined = [_attachable(messages[i - 1] if i else None, message, headers[i])
              for i, message in enumerate(messages)]
    result = []
    for index in range(len(messages)):
        first = not joined[index]
        last = index + 1 >= len(messages) or not joined[index + 1]
        result.append((first, last))
    return result


def shows_authors(kind):
    """Pictures beside incoming messages: groups only, never channels or chats."""
    return kind == 'group'

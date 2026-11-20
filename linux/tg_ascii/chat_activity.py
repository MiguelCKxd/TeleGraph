"""Chat list activity marks (1.4, Complex features › off by default).

``Name ● [3]`` when a private chat's user is online, ``Name ··· [3]`` while
someone types there. The mark sits between the name and the unread counter,
which is always kept. Data comes from updates Telegram already sends
(UpdateUserStatus / typing updates) and from the dialog entities; no polling.
"""
from datetime import datetime, timezone
import time

TYPING_SECONDS = 6
ONLINE_MARK = ' ●'
TYPING_MARK = ' ···'


def enabled(app):
    from .advanced_features import feature_enabled
    return feature_enabled(app, 'chat_list_activity')


def remember_typing(app, peer, status):
    typing = getattr(app, '_list_typing', None)
    if typing is None:
        typing = app._list_typing = {}
    if status:
        typing[(app.ui_account, peer)] = time.monotonic() + TYPING_SECONDS
    else:
        typing.pop((app.ui_account, peer), None)
    while len(typing) > 256:
        typing.pop(next(iter(typing)))


def is_online(app, chat):
    if chat.kind != 'user':
        return False
    from telethon import types
    presence = getattr(getattr(app.service, 'backend', None), '_presence', {}) or {}
    status = presence.get(chat.id, getattr(chat.entity, 'status', None))
    if not isinstance(status, types.UserStatusOnline):
        return False
    expires = status.expires
    return expires is None or expires > datetime.now(timezone.utc)


def mark(app, chat):
    if not enabled(app):
        return ''
    deadline = getattr(app, '_list_typing', {}).get((app.ui_account, chat.id))
    if deadline and deadline > time.monotonic():
        return TYPING_MARK
    return ONLINE_MARK if is_online(app, chat) else ''


def schedule_refresh(app, delay_ms=0):
    """Coalesce many status updates into one chat-list repaint."""
    if not enabled(app) or getattr(app, '_activity_refresh', None) is not None:
        return
    def run():
        app._activity_refresh = None
        if not getattr(app, 'closed', False) and getattr(app, 'stage', None) == 'ready':
            app.render_chats()
    app._activity_refresh = app.root.after(max(50, delay_ms), run)

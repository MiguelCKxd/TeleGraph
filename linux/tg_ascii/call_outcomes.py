"""Telegram call outcomes without guessing whether a busy user rejected it."""
from telethon import types as t

def discard_outcome(reason):
    if isinstance(reason,t.PhoneCallDiscardReasonBusy):return 'declined_or_busy'
    if isinstance(reason,t.PhoneCallDiscardReasonMissed):return 'not_answered'
    if isinstance(reason,t.PhoneCallDiscardReasonDisconnect):return 'disconnected'
    if isinstance(reason,t.PhoneCallDiscardReasonMigrateConferenceCall):return 'conference'
    return 'ended'

LABELS={'declined_or_busy':'Call declined or busy','not_answered':'Not answered',
        'disconnected':'Call disconnected','conference':'Moved to conference',
        'declined':'Call declined','cancelled':'Call cancelled','ended':'Call ended'}

"""Shared, bounded FLOOD_WAIT handling for idempotent Telegram reads.

TG-ASCII creates its clients with ``flood_sleep_threshold=0`` and
``request_retries=1``. Telethon then remembers a FLOOD_WAIT for each request
type and makes *every* later request of that type fail immediately, without
touching the network, until the wait expires. For file chunks (thumbnails,
avatars, emoji, stickers), history pages and emoji metadata this meant that
one rate-limited request turned dozens of queued previews into instant
failures, each one then cached as "failed" by the interface.

Only read-only, side-effect-free operations are routed through this module.
Waiting and repeating them cannot duplicate anything on Telegram. Sending,
editing, saving drafts and every other write keep their original behaviour.

The gate is per backend (one account) and per category, so one account being
rate limited never delays another account.
"""
import asyncio
import random
import time

from telethon import errors

# Waits up to this long are absorbed transparently; longer ones surface to the
# caller exactly as before (they are real, user-visible limits).
MAX_AUTOMATIC_WAIT = 30
# Small margin so Telethon's own per-request flood memory has expired.
MARGIN = 0.6
FLOOD_ERRORS = tuple(error for error in (getattr(errors, 'FloodWaitError', None),
                                          getattr(errors, 'FloodPremiumWaitError', None))
                     if error is not None)


def wait_seconds(exc):
    try:
        return max(1, int(getattr(exc, 'seconds', 0) or 0))
    except (TypeError, ValueError):
        return 1


class FloodGate:
    """Earliest monotonic time at which a category may contact Telegram again."""

    __slots__ = ('resume_at',)

    def __init__(self):
        self.resume_at = 0.0

    def remaining(self):
        return max(0.0, self.resume_at - time.monotonic())

    def hold(self, seconds):
        self.resume_at = max(self.resume_at, time.monotonic() + seconds + MARGIN)

    async def passage(self, limit=MAX_AUTOMATIC_WAIT):
        deadline = time.monotonic() + limit
        while True:
            resume_at = self.resume_at
            delay = self.remaining()
            if delay <= 0:
                return
            if delay > max(0, deadline - time.monotonic()):
                raise errors.FloodWaitError(request=None, capture=int(delay + 0.999))
            # Jitter avoids every queued preview waking in the same millisecond.
            await asyncio.sleep(delay + random.uniform(0, 0.25))
            if self.resume_at <= resume_at:
                return
            # Another read extended this category's wait while we slept.
            # Respect it without silently extending the caller's total budget.


def gate(owner, category):
    gates = getattr(owner, '_flood_gates', None)
    if gates is None:
        gates = {}
        try:
            owner._flood_gates = gates
        except AttributeError:
            return FloodGate()
    found = gates.get(category)
    if found is None:
        found = gates[category] = FloodGate()
    return found


async def read_with_flood_wait(owner, category, operation, *, limit=MAX_AUTOMATIC_WAIT, attempts=2):
    """Run ``operation()`` (a coroutine factory), waiting out short FLOOD_WAITs.

    ``operation`` must be idempotent. At most ``attempts`` extra executions are
    made; a wait longer than ``limit`` is raised unchanged.
    """
    shared = gate(owner, category)
    for attempt in range(attempts + 1):
        await shared.passage(limit)
        try:
            return await operation()
        except FLOOD_ERRORS as exc:
            seconds = wait_seconds(exc)
            shared.hold(seconds)
            if attempt >= attempts or seconds > limit:
                raise

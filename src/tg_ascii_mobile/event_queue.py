"""Bound the strings waiting for one WebView to consume its event stream."""
import asyncio
import sys

MAX_EVENTS = 500
MAX_EVENT_BYTES = 4 * 1024 * 1024


class EventQueue(asyncio.Queue):
    """Budget queued Python strings; socket buffers and the active write are separate.

    None is the reconnect marker. Core clears an overflowing queue before adding
    that marker, so a slow view requests a fresh state instead of stale updates.
    """

    def __init__(self, byte_limit=MAX_EVENT_BYTES, maxsize=MAX_EVENTS):
        super().__init__(maxsize=maxsize)
        self.byte_limit = byte_limit
        self.pending_bytes = 0

    @staticmethod
    def item_size(item):
        return 0 if item is None else sys.getsizeof(item)

    def would_overflow(self, item):
        return self.full() or self.pending_bytes + self.item_size(item) > self.byte_limit

    def _put(self, item):
        size = self.item_size(item)
        if self.pending_bytes + size > self.byte_limit:
            raise asyncio.QueueFull
        super()._put(item)
        self.pending_bytes += size

    def _get(self):
        item = super()._get()
        self.pending_bytes -= self.item_size(item)
        return item

    def clear(self):
        while not self.empty():
            self.get_nowait()

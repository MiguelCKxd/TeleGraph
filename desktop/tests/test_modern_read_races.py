"""Deferred callbacks belong to one visit/page/header request, not only a peer."""
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock

from tg_ascii.desktop_modern import DesktopModern


class DeferredWorker:
    def __init__(self):
        self.jobs = []

    def submit(self, operation, done, failed):
        operation.close()
        future = Future()
        self.jobs.append((future, done, failed))
        return future


class ModernReadRaceTests(unittest.TestCase):
    def history(self):
        return NS(busy=False, demo=False, messages=[NS(id=100)], ui_account='a', active=42,
                  service=NS(backend=NS(older_messages=AsyncMock())), worker=DeferredWorker(),
                  _history_request_token=object(), render_messages=Mock(), jump_loaded=Mock())

    def test_previous_visit_cannot_reinsert_older_messages(self):
        app = self.history()
        DesktopModern.load_older(app)
        app._history_request_token = object()
        app.worker.jobs[0][1]([NS(id=99)])
        self.assertEqual([message.id for message in app.messages], [100])
        app.render_messages.assert_not_called()

    def test_new_visit_replaces_pending_page_and_old_failure_cannot_backoff_it(self):
        app = self.history()
        DesktopModern.load_older(app)
        previous = app.worker.jobs[0]
        app._history_request_token = object()
        DesktopModern.load_older(app)
        self.assertEqual(len(app.worker.jobs), 2)
        self.assertTrue(previous[0].cancelled())
        previous[2](OSError('offline'))
        self.assertTrue(app._older_pending)
        self.assertEqual(getattr(app, '_older_retry_at', 0), 0)
        app.worker.jobs[1][1]([NS(id=90)])
        self.assertEqual([message.id for message in app.messages], [90, 100])
        self.assertFalse(app._older_pending)

    def test_same_visit_deduplicates_page_and_honors_failure_backoff(self):
        app = self.history()
        DesktopModern.load_older(app)
        DesktopModern.load_older(app)
        self.assertEqual(len(app.worker.jobs), 1)
        app.worker.jobs[0][2](OSError('offline'))
        DesktopModern.load_older(app)
        self.assertEqual(len(app.worker.jobs), 1)

    def test_old_header_cannot_replace_newer_status_for_same_chat(self):
        app = NS(update_chat_capabilities=Mock(), demo=False, active=42, ui_account='a',
                 service=NS(backend=NS(chat_header=AsyncMock(), avatar=AsyncMock())),
                 bot_row=Mock(), bot_buttons={key: Mock() for key in ('Bot commands', 'Open Mini App')},
                 header_avatar=Mock(), header_status_emoji=Mock(), activity=Mock(), worker=DeferredWorker(),
                 preview_dir=Path('/cache'), request_photo=Mock())
        DesktopModern.refresh_header(app)
        old = app.worker.jobs[0][1]
        DesktopModern.refresh_header(app)
        newest = app.worker.jobs[2][1]
        info = dict(commands=[], mini=False, emoji=None)
        newest(dict(info, status='new'))
        old(dict(info, status='old'))
        self.assertEqual(app.header_base_status, 'new')
        app.activity.set.assert_called_with('new')


if __name__ == '__main__':
    unittest.main()

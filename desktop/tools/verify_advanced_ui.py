"""Native opt-in dialog smoke test with synthetic Telegram objects and no network."""
import argparse
import json
import sys
import time
import tkinter as tk
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import MethodType
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from telethon import types as t

from tg_ascii.advanced_editor import EntityField
from tg_ascii.advanced_features import FEATURES
from tg_ascii.advanced_messaging import poll_media, todo_media
from tg_ascii.article_view import ArticleView
from tg_ascii.backend import Message
from tg_ascii.desktop import AsyncWorker
from tg_ascii.desktop_advanced import DesktopAdvancedMixin
from tg_ascii.desktop_features import DesktopFeatures
from tg_ascii.preferences import DEFAULTS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {'success': False, 'synthetic_only': True, 'network_requests': 0, 'payments': 0}
    started = time.monotonic()
    root = tk.Tk(); root.geometry('900x720'); root.title('TG-ASCII synthetic advanced UI test')
    worker = AsyncWorker(); errors = []
    previous_unraisable = sys.unraisablehook
    sys.unraisablehook = lambda value: errors.append('Unraisable: ' + repr(value.exc_value))
    root.report_callback_exception = lambda kind, error, trace: errors.append(str(error))
    app = DesktopAdvancedMixin()
    app.root, app.worker, app.popups, app.busy, app.demo = root, worker, [], False, False
    app.ui_account, app.active, app.closed, app.closing = 'synthetic', 77, False, False
    app.preferences = NS(values={**DEFAULTS, 'advanced_features': dict.fromkeys(FEATURES, True)})
    app.font_family = 'Arial'
    app.status = tk.StringVar(master=root)
    app.chats, app.messages = [], []
    app.render_messages, app.open_link, app.media_dialog, app.show_contact_profile = Mock(), Mock(), Mock(), Mock()
    app.show_error = lambda error: errors.append(str(error))
    app.telegram_picker = Mock()
    app.dialog = MethodType(DesktopFeatures.dialog, app)
    app.field = MethodType(DesktopFeatures.field, app)
    media = t.MessageMediaPoll(poll_media('Synthetic poll 😀', ['First', 'Second'], multiple=True, open_answers=True).poll,
                              t.PollResults(total_voters=0, results=[]))
    todo = t.MessageMediaToDo(todo_media('Synthetic checklist', [(1, 'One'), (2, 'Two')], others_can_append=True, others_can_complete=True).todo)
    rich = t.RichMessage([t.PageBlockTitle(t.TextPlain('Synthetic article')),
        t.PageBlockParagraph(t.TextBold(t.TextPlain('Formatted body'))),
        t.PageBlockDetails([t.PageBlockParagraph(t.TextPlain('Collapsed detail'))], t.TextPlain('Expand'))], [], [])
    backend = NS(poll_state=AsyncMock(return_value=(media, True)), checklist_state=AsyncMock(return_value=(todo, True)),
                 article_state=AsyncMock(return_value=(rich, True)), gift_catalogue=AsyncMock(return_value=NS(gifts=[])),
                 resale_gifts=AsyncMock(return_value=NS(gifts=[], next_offset=None)),
                 contacts=AsyncMock(return_value=[]), poll_voters=AsyncMock(return_value=([], None)))
    backend.account_profile = NS(premium=True, user_id=77)
    backend._capability_entities = {77: t.User(77, is_self=True)}
    app.service = NS(backend=backend)
    def call(operation, done, status, failed=None, **kwargs):
        app.busy = True
        def loaded(value): app.busy = False; done(value)
        def error(exc): app.busy = False; (failed or app.show_error)(exc)
        return worker.submit(operation, loaded, error)
    app.call = call
    def pump(seconds=.10):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            root.update()
            while not worker.events.empty():
                callback, value = worker.events.get_nowait(); callback(value)
            if errors: raise AssertionError(errors)
            time.sleep(.003)
    checks = []
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    try:
        for method in ('new_poll_dialog', 'new_checklist_dialog', 'location_dialog', 'share_contact_dialog', 'article_composer', 'gifts_dialog'):
            if method == 'gifts_dialog':
                backend.gift_catalogue.return_value = NS(gifts=[
                    t.StarGift(1, t.DocumentEmpty(1), 100, 80),
                    t.StarGift(2, t.DocumentEmpty(2), 100, 80, sold_out=True)])
            getattr(app, method)(); pump()
            assert app.popups[-1].winfo_exists(), method
            checks.append(method)
            if method == 'gifts_dialog':
                controls = list(descendants(app.popups[-1]))
                listing = next(widget for widget in controls if isinstance(widget, tk.Listbox))
                purchase = next(widget for widget in controls if isinstance(widget, tk.ttk.Button) and widget.cget('text') == 'Review gift purchase')
                assert not purchase.winfo_manager()
                listing.selection_set(0); listing.event_generate('<<ListboxSelect>>'); pump(.03)
                assert purchase.winfo_manager() == 'pack'
                listing.selection_clear(0, 'end'); listing.selection_set(1); listing.event_generate('<<ListboxSelect>>'); pump(.03)
                assert not purchase.winfo_manager()
                checks.append('sold_out_gift_has_no_purchase_button')
                backend.gift_catalogue.return_value.gifts[0].require_premium = True
                backend.account_profile.premium = False
                listing.selection_clear(0, 'end'); listing.selection_set(0); listing.event_generate('<<ListboxSelect>>'); pump(.03)
                assert not purchase.winfo_manager()
                checks.append('premium_gift_hidden_after_account_capability_change')
                backend.account_profile.premium = True
            app.popups[-1].destroy(); pump(.03)
        app.resale_gifts_dialog(1); pump(.1)
        assert backend.resale_gifts.await_count == 1
        checks.append('collectible_gifts_paginated'); app.popups[-1].destroy()
        gift = t.StarGift(1, t.DocumentEmpty(1), 100, 80)
        record = t.SavedStarGift(datetime.now(UTC), gift, msg_id=12, can_upgrade=True, upgrade_stars=50, convert_stars=80)
        app.open_saved_gift(record, 77, own=True); pump(.1)
        checks.append('profile_gift_actions'); app.popups[-1].destroy()
        for kind, raw in [('poll', media), ('checklist', todo), ('location', t.MessageMediaGeo(t.GeoPoint(1, 2, 0))),
                          ('contact', t.MessageMediaContact('34123456789', 'Synthetic', 'Contact', '', 77)), ('article', rich)]:
            item = Message(12, 'Synthetic', kind, '12:00', True, raw, kind)
            app.open_advanced_message(item); pump(.15)
            assert app.popups[-1].winfo_exists(), kind
            checks.append('read_' + kind)
            if kind in ('poll', 'checklist'):
                inspector = next(value for value in app._advanced_inspectors if value.window is app.popups[-1])
                updated = deepcopy(raw)
                if kind == 'poll':
                    first = next(widget for widget in inspector.body.winfo_children() if isinstance(widget, tk.ttk.Checkbutton))
                    first.invoke()
                    selected = inspector._poll_selection()
                    updated.results.total_voters = 23
                else:
                    updated.completions = [t.TodoCompletion(1, t.PeerUser(88), datetime.now(UTC))]
                change = Message(12, 'Synthetic', kind, '12:00', True, updated, kind)
                for _ in range(100): app.advanced_media_changed('synthetic', 77, change)
                pump(.12)
                if kind == 'poll':
                    assert inspector._poll_selection() == selected
                    assert backend.poll_state.await_count == 1
                    updated.poll.closed = True
                    app.advanced_media_changed('synthetic', 77, change); pump(.08)
                    assert not any(isinstance(widget, tk.ttk.Button) and widget.cget('text') in ('Vote', 'Close poll', 'Retract vote')
                                   for widget in inspector.body.winfo_children())
                    assert not any(isinstance(widget, tk.ttk.Checkbutton) for widget in inspector.body.winfo_children())
                    checks.append('closed_poll_has_readonly_results')
                else:
                    assert backend.checklist_state.await_count == 1
                checks.append(kind + '_push_updates_without_rpc')
            app.popups[-1].destroy(); pump(.03)
        app.article_editor(Message(12, 'Synthetic', 'Article', '12:00', True, rich, 'article'), rich); pump()
        checks.append('article_edit_preserving_blocks'); app.popups[-1].destroy()
        field = EntityField(root, app, t.TextWithEntities('😀 bold', [t.MessageEntityBold(0, 2)]))
        field.pack(); pump(.03)
        assert field.value().entities[0].length == 2
        assert field.value().text == '😀 bold'
        checks.append('utf16_entity_editor')
        field.editor.tag_add('sel', '1.0', 'end-1c')
        field.apply(t.MessageEntityBlockquote, collapsed=True)
        assert any(isinstance(entity, t.MessageEntityBlockquote) and entity.collapsed for entity in field.value().entities)
        checks.append('entity_editor_expandable_quote'); field.destroy()
        view = ArticleView(root, app, rich); view.pack(); pump(.03)
        assert len(view.folds) == 1 and not next(iter(view.folds.values()))
        checks.append('article_collapsed_details'); view.destroy()
        backend.account_profile.user_id = 3
        backend._capability_entities[77] = t.User(77)
        before = len(app.popups)
        app.new_poll_dialog(); pump(.03)
        assert len(app.popups) == before
        checks.append('human_private_chat_does_not_open_poll_composer')
        result.update(success=True, checks=checks, callback_errors=errors, wall_seconds=time.monotonic() - started,
                      created_at=datetime.now(UTC).isoformat())
    except Exception as exc:
        result.update(error=repr(exc), checks=checks, callback_errors=errors)
        raise
    finally:
        for window in app.popups:
            if window.winfo_exists(): window.destroy()
        worker.stop()
        worker.thread.join(timeout=5)
        result['worker_stopped'] = not worker.thread.is_alive()
        if errors or not result['worker_stopped']: result['success'] = False
        root.destroy()
        sys.unraisablehook = previous_unraisable
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
    if not result['success']: raise SystemExit(1)


if __name__ == '__main__': main()

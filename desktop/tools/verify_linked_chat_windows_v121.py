"""Native 1.2.1 chat-only windows; synthetic demo accounts, no network/hardware.

python tools/verify_linked_chat_windows_v121.py --output result.json --screenshots captures
This validates the chat-only contract, not the retired full-app child layout.
"""
import argparse
import asyncio
import json
import re
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import traceback
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii import __edition__
from tg_ascii import app_lock
from tg_ascii.accounts import Accounts
from tg_ascii.backend import Chat, Message
from tg_ascii.contact_profile import ContactProfile
from tg_ascii.desktop import Desktop
from tg_ascii.interface_store import default_layout, validate_layout
from tg_ascii.interface_windows import sync_window_accounts
from tg_ascii.i18n import tr


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        # Popup roots are not part of their parent's visible app interface.
        if not isinstance(child, tk.Toplevel):
            yield from descendants(child)


def labels(widget):
    result = []
    for child in descendants(widget):
        try:
            result.append(str(child.cget('text')))
        except tk.TclError:
            pass
    return result


def capture_menu(operation):
    with patch('tg_ascii.app_dialogs.popup_menu') as popup:
        operation()
    assert popup.called, 'The expected tools menu did not open'
    return popup.call_args.args[1]


def command(entries, label):
    found = [entry[1] for entry in entries if entry and entry[0] == label]
    assert len(found) == 1, (label, [entry[0] for entry in entries if entry])
    return found[0]


def pump(root, condition, errors, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if errors:
            raise AssertionError(errors)
        if condition():
            return
        time.sleep(.005)
    raise TimeoutError('Synthetic chat-window check did not finish')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    results = {'success': False, 'edition': __edition__, 'platform': sys.platform,
               'synthetic_only': True, 'accounts_accessed': False, 'hardware_used': False,
               'checks': [], 'callback_errors': []}
    errors, steps = results['callback_errors'], results['checks']
    timer_sources = {}
    original_after = tk.Misc.after
    def tracked_after(widget, delay, callback=None, *values):
        ident = original_after(widget, delay, callback, *values)
        if callback is not None and ident:
            script = widget.tk.call('after', 'info', ident)[0]
            name = widget.tk.splitlist(script)[0]
            timer_sources[str(name)] = {'delay': delay, 'callback': getattr(callback, '__qualname__', repr(callback)),
                                        'widget': str(widget), 'stack': traceback.format_stack(limit=7)}
        return ident
    timer_patch = patch.object(tk.Misc, 'after', tracked_after)
    timer_patch.start()
    root = None
    app = None
    views = []
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='tg-chat-windows-v121-') as directory:
        try:
            root = tk.Tk()
            service = Accounts(demo=True, root=directory)
            app = Desktop(root, demo=True, service=service)
            def failure(error):
                errors.append(type(error).__name__ + ': ' + str(error))
            def hook(view):
                view.show_error = failure
                view.root.report_callback_exception = lambda kind, error, trace: failure(error)
                return view
            hook(app)
            def tcl_error(message):
                errors.append('Tcl: ' + str(message))
                match = re.search(r'invalid command name "([^"]+)"', str(message))
                if match and match[1] in timer_sources:
                    results.setdefault('invalid_timer_sources', []).append(timer_sources[match[1]])
            root.tk.createcommand('bgerror', tcl_error)
            pump(root, lambda: bool(app.chats) and not app.busy, errors)
            assert service.demo
            account_a = app.ui_account
            backend_a = service.backend
            backend_a.presence = AsyncMock(return_value=None)
            backend_a.mark_read = AsyncMock(return_value=None)
            app.open_resolved(app.chats[0])
            pump(root, lambda: bool(app.messages) and not app.busy, errors)
            peer = app.active
            target = next(chat for chat in app.chats if chat.id == peer)
            with patch('tg_ascii.desktop_calls.call_allowed', return_value=True), patch.object(app, 'start_call') as start_call:
                app.update_chat_capabilities()
                root.update()
                for button, video in ((app.call_button, False), (app.video_call_button, True)):
                    assert button.master is app.header_details and button.winfo_ismapped()
                    assert button.winfo_x() < app.pinned_button.winfo_x()
                    button.invoke()
                    start_call.assert_called_with(video=video)
                entries = capture_menu(app.chat_tools_menu)
                command(entries, tr('Call'))()
                start_call.assert_called_with(video=False)
                command(entries, tr('Video call'))()
                start_call.assert_called_with(video=True)
            app.update_chat_capabilities()
            root.update()
            assert not app.call_button.winfo_ismapped() and not app.video_call_button.winfo_ismapped()
            steps.append('call_controls_visible_left_of_tools_when_allowed_and_hidden_when_unavailable')
            app.editor.insert('1.0', 'Principal retained synthetic draft')
            principal = (app.ui_account, app.active, app.editor.get('1.0', 'end-1c'))

            # The only public entry points are chat-list tools and chat-header tools.
            more = next(widget for widget in descendants(app.recovery_bar)
                        if isinstance(widget, ttk.Button) and widget.cget('text') == '⋯')
            recovery = capture_menu(more.invoke)
            forbidden = {tr('Open chat in new window'), 'New linked app window', 'New chat window',
                         'New linked chat window', 'Nueva ventana vinculada de la app',
                         'Nueva ventana de chat', 'Nueva ventana de chat vinculada', 'Nueva ventana de app vinculada'}
            assert not any(item and item[0] in forbidden for item in recovery)
            app.notebook.select(app.settings_page)
            pump(root, lambda: len(app.settings_page.winfo_children()) > 0, errors)
            assert not forbidden.intersection(labels(app.settings_page))
            app.notebook.select(app.chat_page)
            app.demo = False
            try:
                app.universal_search()
            finally:
                app.demo = True
            search = app.popups[-1]
            assert tr('Open chat in new window') not in labels(search)
            search.destroy()
            app.open_contacts()
            pump(root, lambda: not app.busy and bool(app.popups) and app.popups[-1].winfo_exists(), errors)
            contacts = app.popups[-1]
            assert tr('Open chat in new window') not in labels(contacts)
            contacts.destroy()
            profile = ContactProfile(app, peer)
            pump(root, lambda: profile.profile is not None and hasattr(profile, 'action_widgets'), errors)
            assert 'new_window' not in profile.action_widgets
            profile.window.destroy()
            steps.append('window_entry_absent_from_global_settings_search_contacts_profile')

            # Capture the menu without posting a native context menu. Only its
            # open-window callback executes; the backend remains a demo object.
            app.demo = False
            try:
                listing = capture_menu(lambda: app.chat_actions(peer))
            finally:
                app.demo = True
            command(listing, tr('Open chat in new window'))()
            first = hook(app._app_windows[-1]); views.append(first)
            header = capture_menu(app.chat_tools_menu)
            command(header, tr('Open chat in new window'))()
            second = hook(app._app_windows[-1]); views.append(second)
            assert first is not second
            pump(root, lambda: all(view.messages and not view.busy for view in views), errors)
            assert principal == (app.ui_account, app.active, app.editor.get('1.0', 'end-1c'))
            assert all(view.active == peer and view.ui_account == account_a for view in views)
            assert len({view.draft_manager.store.path for view in (app, *views)}) == 3
            assert first.worker.loop is second.worker.loop is app.worker.loop
            assert first.service.backend is second.service.backend is backend_a
            assert first.preferences is second.preferences is app.preferences
            assert first.interface_store is second.interface_store is app.interface_store
            steps.append('list_and_header_open_duplicate_chat_preserving_principal_and_shared_services')

            def no_global_panels(view):
                assert view._chat_only
                assert (view._pinned_account, view._pinned_peer) == (view.ui_account, view.active)
                for name in ('account_bar', 'account_picker', 'notebook', 'chat_sidebar', 'chat_list',
                             'story_page', 'settings_page', 'recovery_bar', 'global_results'):
                    widget = getattr(view, name, None)
                    assert widget is None or not widget.winfo_exists(), name
                for name in ('chat_page', 'chat_conversation', 'history', 'editor', 'attach_button',
                             'send_button', 'pinned_button', 'sticker_button', 'custom_emoji_button'):
                    widget = getattr(view, name)
                    assert widget.winfo_exists(), name
                assert '☺' in labels(view.composer_controls)
                tools = capture_menu(view.chat_tools_menu)
                assert tr('Open chat in new window') not in [entry[0] for entry in tools if entry]
                command(tools, tr('Close'))
                assert tr('Search in chat') in [entry[0] for entry in tools if entry]
                assert tr('Shared media') in [entry[0] for entry in tools if entry]
            for view in views:
                no_global_panels(view)
            first.root.geometry('400x420')
            pump(root, lambda: abs(first.root.winfo_width() - 400) < 3, errors)
            for name in ('editor', 'send_button', 'attach_button', 'pinned_button'):
                assert getattr(first, name).winfo_ismapped(), name
            displayed_history = first.bubble_view if getattr(first, '_canvas_chat_view', False) else first.history
            assert displayed_history.winfo_ismapped()
            no_global_panels(first)
            first.root.geometry('680x720')
            pump(root, lambda: abs(first.root.winfo_width() - 680) < 3, errors)
            steps.append('children_contain_full_chat_controls_without_global_app_panels_and_resize_400x420')

            first.editor.delete('1.0', 'end'); first.editor.insert('1.0', 'Synthetic child-only send')
            second.editor.insert('1.0', 'Second independent unsent draft')
            second_draft = second.editor.get('1.0', 'end-1c')
            first.send()
            pump(root, lambda: not first.busy and any(message.text == 'Synthetic child-only send' for message in second.messages), errors)
            assert second.editor.get('1.0', 'end-1c') == second_draft
            assert app.editor.get('1.0', 'end-1c') == principal[2]
            assert sum(message.text == 'Synthetic child-only send' for message in second.messages) == 1
            first.editor.insert('1.0', 'First independent draft')
            steps.append('send_fanout_once_preserves_other_composers')

            incoming = Message(800008, 'Synthetic remote sender', 'Incoming synthetic update', '12:00')
            app.account_event((account_a, peer, incoming))
            pump(root, lambda: all(any(message.id == incoming.id for message in view.messages) for view in views), errors)
            first.root.lift(); first.editor.focus_force(); root.update()
            assert first.chat_visible() and not second.chat_visible()
            assert not app.chat_visible(), 'Principal must not mark messages read while a child has focus'
            read = AsyncMock(return_value=None)
            with patch.object(backend_a, 'mark_read', read, create=True):
                first.demo = second.demo = False
                try:
                    first.acknowledge_visible()
                    second.acknowledge_visible()
                finally:
                    first.demo = second.demo = True
                pump(root, lambda: read.await_count and not first._read_pending, errors)
                read.assert_awaited_once_with(peer, incoming.id)
            steps.append('incoming_without_sidebar_and_read_ack_only_for_focused_child')

            # A legacy layout can neither recover a retired window button nor
            # shift a panel alias onto a different surviving action.
            document = validate_layout({**default_layout(), 'enabled': True, 'name': 'Synthetic old layout',
                'items': [
                    {'id': 'old-window', 'kind': 'button', 'text': 'Retired window', 'action': 'new-window', 'rect': [.02, .02, .2, .08]},
                    {'id': 'old-menu', 'kind': 'menu', 'text': 'Legacy menu', 'entries': [
                        {'text': 'Retired window', 'action': 'new-window'}, {'text': 'Refresh only', 'action': 'refresh'}], 'rect': [.25, .02, .2, .08]},
                    {'id': 'old-panel', 'kind': 'panel', 'text': 'Legacy panel', 'entries': [
                        {'text': 'Retired window', 'action': 'new-window'}, {'text': 'Refresh only', 'action': 'refresh'}], 'rect': [.5, .02, .2, .13]}]})
            drafts = [(view.active, view.editor.get('1.0', 'end-1c')) for view in (app, *views)]
            app.interface_store.commit(document)
            app.preferences.save({'theme': 'light', 'button_border_width': 2})
            pump(root, lambda: not getattr(app, '_shared_design_after', None) and all(not view.busy for view in (app, *views)), errors)
            for view, saved in zip((app, *views), drafts):
                assert (view.active, view.editor.get('1.0', 'end-1c')) == saved
                assert view.preferences.values['theme'] == 'light'
            for view in views:
                no_global_panels(view)
            runtime = app.layout_runtime
            assert 'custom/old-window' not in runtime.widgets
            assert 'custom/old-panel/0' not in runtime.widgets
            assert 'custom/old-panel/1' in runtime.widgets
            old_menu = capture_menu(runtime.widgets['custom/old-menu'].invoke)
            assert [item[0] for item in old_menu] == ['Refresh only']
            with patch.object(app, 'refresh') as refresh:
                runtime.invoke('widget:custom/old-panel/0')
                refresh.assert_not_called()
                runtime.invoke('widget:custom/old-panel/1')
                refresh.assert_called_once_with(reconnect=True)
            app.interface_store.commit(default_layout())
            pump(root, lambda: not getattr(app, '_shared_design_after', None), errors)
            for view in views:
                no_global_panels(view)
            steps.append('shared_design_and_legacy_layout_restore_preserve_chat_only_and_drafts')

            first.editor.focus_force()
            root.update()
            first.editor.event_generate('<Escape>')
            first.history.event_generate('<Escape>')
            first.root.event_generate('<F5>')
            first.latest_messages()
            pump(root, lambda: not first.busy and not getattr(first, '_refresh_pending', False), errors)
            with patch('tg_ascii.native_emoji.open_palette') as palette:
                first.emoji_picker()
                palette.assert_called_once()
            root.update()
            assert not errors
            steps.append('escape_refresh_history_and_emoji_do_not_require_sidebar')

            # The lock owner is the principal, including every chat child.
            app_lock.LockStore(directory).save(app_lock.make_record('7'))
            app.demo = False
            try:
                assert app_lock.lock_app(first)
                panel = app._app_lock_panel
                pump(root, lambda: panel.window.winfo_ismapped(), errors)
                assert all(view.root.state() == 'withdrawn' for view in (app, *views))
                before = len(app._app_windows)
                app.open_chat_in_new_window(peer, target, account_a)
                assert len(app._app_windows) == before
                panel.password.set('7'); panel.submit.invoke()
                pump(root, lambda: not app_lock.is_locked(app), errors)
            finally:
                app.demo = True
            for view, saved in zip((app, *views), drafts):
                assert view.editor.get('1.0', 'end-1c') == saved[1]
            steps.append('shared_lock_hides_chat_children_and_restores_independent_drafts')

            account_b = 'b' * 32
            service.entries[account_b] = {'label': 'Synthetic account B'}
            service.labels[account_b] = 'Synthetic account B'
            connected = threading.Event()
            async def connect_demo():
                await service.service(account_b).connect()
            app.worker.submit(connect_demo(), lambda _: connected.set(), failure)
            pump(root, connected.is_set, errors)
            service.services[account_b].backend.presence = AsyncMock(return_value=None)
            service.services[account_b].backend.mark_read = AsyncMock(return_value=None)
            from tg_ascii.ui_work import FrameJob
            retired_callback = Mock()
            retired_job = FrameJob(app.chat_list, retired_callback, delay=250)
            retired_job.request()
            app.switch_account(account_b)
            pump(root, lambda: app.ui_account == account_b and not app.busy and bool(app.chats), errors)
            until = time.monotonic() + .3
            pump(root, lambda: time.monotonic() >= until, errors)
            retired_callback.assert_not_called()
            steps.append('account_rebuild_cancels_callbacks_of_destroyed_sidebar_widgets')
            assert all(view.ui_account == account_a and view.service.backend is backend_a for view in views)
            first.switch_account(account_b)
            with patch('tg_ascii.interface_windows.navigate_from_chat_window') as navigate:
                redirected = Chat(999997, 'Synthetic navigation target')
                first.open_resolved(redirected)
                navigate.assert_called_once_with(first, chat=redirected)
            assert (first.ui_account, first.active) == (account_a, peer)
            app.open_resolved(app.chats[0])
            pump(root, lambda: not app.busy and bool(app.messages), errors)
            third = hook(app.open_chat_in_new_window()); views.append(third)
            pump(root, lambda: third.messages and not third.busy, errors)
            assert third.ui_account == account_b
            no_global_panels(third)
            steps.append('principal_account_switch_keeps_children_pinned_and_new_child_uses_new_account')

            # Closing one chat while its transient widgets and cancelled reads
            # exist must not kill the shared worker or a sibling.
            cancelled, entered = threading.Event(), threading.Event()
            delivered = []
            async def pending_read():
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            first.worker.submit(pending_read(), delivered.append, delivered.append)
            pump(root, entered.is_set, errors)
            transient, body = first.dialog('Synthetic open dialog')
            ttk.Label(body, text='Synthetic pending dialog').pack()
            transient.after_idle(lambda: None)
            command(capture_menu(first.chat_tools_menu), tr('Close'))()
            pump(root, lambda: first.closed and cancelled.is_set(), errors)
            assert not transient.winfo_exists()
            assert not delivered
            assert not second.closed and not third.closed and not app.worker._stopping
            assert third.service.backend is service.services[account_b].backend
            steps.append('child_close_cancels_owned_reads_and_dialogs_without_stopping_other_views')

            # Simulate a registry logout; never call Telegram log_out().
            service.entries.pop(account_a)
            service.labels.pop(account_a, None)
            service.services.pop(account_a)
            sync_window_accounts(app)
            pump(root, lambda: second.closed, errors)
            assert not third.closed and not app.closed
            assert app.ui_account == third.ui_account == account_b
            assert not app.worker._stopping
            assert account_a not in second.draft_manager.store.records
            steps.append('logout_registry_closes_only_children_of_removed_account')

            if args.screenshots:
                from PIL import ImageGrab
                args.screenshots.mkdir(parents=True, exist_ok=True)
                for name, view in (('main', app), ('chat-only', third)):
                    view.root.deiconify(); view.root.lift(); root.update()
                    end = time.monotonic() + .15
                    pump(root, lambda: time.monotonic() >= end, errors)
                    x, y = view.root.winfo_rootx(), view.root.winfo_rooty()
                    image = ImageGrab.grab(bbox=(x, y, x + view.root.winfo_width(), y + view.root.winfo_height()))
                    try:
                        image.save(args.screenshots / (name + '.png'))
                    finally:
                        image.close()
                results['screenshots'] = ['main.png', 'chat-only.png']
            command(capture_menu(third.chat_tools_menu), tr('Close'))()
            pump(root, lambda: third.closed, errors)
            assert not app.closed and not app.worker._stopping
            steps.append('last_child_close_keeps_principal_usable')

            cycle_states = []
            for index in range(5):
                child = hook(app.open_chat_in_new_window())
                views.append(child)
                pump(root, lambda: bool(child.messages) and not child.busy, errors)
                child.editor.insert('1.0', 'Synthetic cycle draft ' + str(index))
                command(capture_menu(child.chat_tools_menu), tr('Close'))()
                pump(root, lambda: child.closed, errors)
                assert child not in app._app_windows
                assert not child.worker.pending
                assert not app.worker._stopping
                cycle_states.append({'closed': child.closed, 'pending': len(child.worker.pending)})
            dangling = []
            for ident in root.tk.call('after', 'info'):
                script = root.tk.call('after', 'info', ident)[0]
                tokens = root.tk.splitlist(script)
                if tokens and not root.tk.call('info', 'commands', tokens[0]):
                    dangling.append(str(tokens[0]))
            assert not dangling, ('Destroyed Tk callbacks remain scheduled', dangling)
            assert not app._app_windows
            results['repeated_open_close_cycles'] = cycle_states
            steps.append('five_open_close_cycles_leave_no_registered_children_pending_work_or_deleted_tk_commands')
            results['success'] = True
        except Exception as error:
            results['error'] = repr(error)
            results['traceback'] = traceback.format_exc()
        finally:
            if app is not None:
                app.demo = True
                app.busy = False
                for view in views:
                    view.busy = False
                if not app.closed:
                    app.close()
                    deadline = time.monotonic() + 15
                    while not app.closed and time.monotonic() < deadline:
                        root.update(); time.sleep(.005)
                if not app.closed:
                    app.worker.stop()
                    root.destroy()
                app.worker.thread.join(3)
                results['worker_stopped'] = not app.worker.thread.is_alive()
                results['all_children_closed'] = all(view.closed for view in views)
            elif root is not None:
                root.destroy()
    timer_patch.stop()
    results['seconds'] = round(time.monotonic() - started, 3)
    results['success'] = bool(results['success'] and results.get('worker_stopped')
                              and results.get('all_children_closed') and not errors)
    payload = json.dumps(results, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + '\n', encoding='utf-8')
    print(payload)
    return 0 if results['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

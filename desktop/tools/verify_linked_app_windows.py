"""Native multiwindow regression using synthetic demo data, no credentials."""
import argparse
import json
from pathlib import Path
import sys
import tkinter as tk
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii.desktop import Desktop
from tg_ascii.backend import Chat, Message
from tg_ascii.interface_windows import open_linked_app_window


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = tk.Tk()
    app = Desktop(root, demo=True)
    results = {'success': False, 'synthetic_only': True, 'platform': sys.platform, 'callback_errors': []}
    steps = []
    state = {}
    def fail(error):
        if results.get('error'):
            return
        results['error'] = repr(error)
        results['traceback'] = traceback.format_exc()
        app.busy = False
        for view in getattr(app, '_app_windows', ()):
            view.busy = False
        app.close()
    def callback_error(kind, error, trace):
        results['callback_errors'].append(repr(error))
        fail(error)
    root.report_callback_exception = callback_error
    app.show_error = fail
    def wait_for(predicate, action, deadline=300):
        def poll():
            if results.get('error'):
                return
            try:
                if predicate():
                    action()
                elif countdown[0] <= 0:
                    raise TimeoutError('Native multiwindow step did not finish')
                else:
                    countdown[0] -= 1
                    root.after(30, poll)
            except Exception as error:
                fail(error)
        countdown = [deadline]
        poll()
    def start():
        state['main_account'] = app.ui_account
        state['main_backend'] = app.service.backend
        app.open_resolved(app.chats[0])
        wait_for(lambda: not app.busy and app.active is not None, create_windows)
    def create_windows():
        app.editor.insert('1.0', 'main draft before opening windows')
        state['main_chat'] = app.active
        state['main_text'] = app.editor.get('1.0', 'end-1c')
        state['first_target'] = app.chats[1]
        # A public/search preview does not occur in the server dialog list.
        external = Chat(990001, 'Synthetic public preview')
        app.service.backend.messages[external.id] = [Message(990002, 'Synthetic', 'Preview history', '12:00')]
        state['second_target'] = external
        first = open_linked_app_window(app, initial_chat=state['first_target'])
        second = open_linked_app_window(app, initial_chat=external)
        state.update(first=first, second=second)
        first.show_error = second.show_error = fail
        wait_for(lambda: all(v.messages and not v.busy and not getattr(v, '_refresh_pending', False)
                             for v in (first, second)), independent)
    def independent():
        first, second = state['first'], state['second']
        assert (app.ui_account, app.active, app.editor.get('1.0', 'end-1c')) == (
            state['main_account'], state['main_chat'], state['main_text'])
        assert first.active == state['first_target'].id
        assert second.active == state['second_target'].id
        assert second.messages[0].text == 'Preview history'
        assert any(chat.id == state['second_target'].id for chat in second.chats)
        assert all(chat.id != state['second_target'].id for chat in app.chats)
        steps.append('targeted_chat_open_preserves_main_and_unjoined_preview_after_initial_refresh')
        assert first.service is not second.service
        assert first.service.services is app.service.services
        assert first.service.backend is second.service.backend is state['main_backend']
        assert first.preferences is second.preferences is app.preferences
        assert first.interface_store is app.interface_store
        assert first.worker.loop is second.worker.loop is app.worker.loop
        assert first.wheel_router is second.wheel_router is app.wheel_router
        assert len({v.draft_manager.store.path for v in (app, first, second)}) == 3
        for index, view in enumerate((app, first, second)):
            view.active = view.chats[index % len(view.chats)].id
            view.editor.delete('1.0', 'end')
            view.editor.insert('1.0', 'draft-' + str(index))
        assert len({v.active for v in (app, first, second)}) == 3
        first.busy = True
        assert not app.busy and not second.busy
        first.busy = False
        state['drafts'] = [(v.active, v.editor.get('1.0', 'end-1c')) for v in (app, first, second)]
        steps.append('independent_chats_composers_busy_shared_sessions_design_worker')
        # Create another synthetic account directly, without a real session.
        key = 'b' * 32
        app.service.entries[key] = {'label': 'Second demo'}
        app.service.labels[key] = 'Second demo'
        async def connect_demo():
            await app.service.service(key).connect()
        app.worker.submit(connect_demo(), lambda _: choose_account(key), fail)
    def choose_account(key):
        first = state['first']
        first.switch_account(key)
        wait_for(lambda: first.ui_account == key and not first.busy, accounts_ready)
    def accounts_ready():
        first, second = state['first'], state['second']
        assert first.ui_account != app.ui_account == second.ui_account
        assert app.service.current == state['main_account']
        assert second.service.backend is state['main_backend']
        assert first.service.backend is not second.service.backend
        steps.append('independent_account_selection')
        # Switch back; account-local view state must retain its draft.
        first.switch_account(state['main_account'])
        wait_for(lambda: first.ui_account == state['main_account'] and not first.busy, customize)
    def customize():
        app.preferences.save({'theme': 'light', 'button_border_width': 2})
        wait_for(lambda: not getattr(app, '_shared_design_after', None) and all(not v.busy for v in (app, state['first'], state['second'])), customized)
    def customized():
        views = (app, state['first'], state['second'])
        for view, (peer, text) in zip(views, state['drafts']):
            assert view.active == peer, (view.active, peer)
            assert view.editor.get('1.0', 'end-1c') == text
            assert view.preferences.values['theme'] == 'light'
        steps.append('shared_design_retains_independent_selection_and_drafts')
        state['first'].close()
        wait_for(lambda: state['first'].closed, closed_one)
    def closed_one():
        assert not app.closed and not state['second'].closed
        assert not app.worker._stopping
        assert app.service.backend is state['main_backend']
        steps.append('secondary_close_preserves_other_views_and_connection')
        results.update(success=True, checks=steps, linked_full_windows=2, account_count=2)
        app.close()
    wait_for(lambda: app.chats and not app.busy, start)
    root.after(20000, lambda: fail(TimeoutError('Watchdog')) if not results['success'] else None)
    root.mainloop()
    app.worker.thread.join(timeout=3)
    results['worker_stopped'] = not app.worker.thread.is_alive()
    results['all_windows_closed'] = all(v.closed for v in (state.get('first'), state.get('second')) if v)
    results['success'] = results['success'] and results['worker_stopped'] and results['all_windows_closed'] and not results['callback_errors']
    payload = json.dumps(results, indent=2)
    if args.output:
        args.output.write_text(payload, encoding='utf-8')
    print(payload)
    return 0 if results['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Native Tk call-window QA with demo accounts and synthetic call managers.

No Telegram credentials, account files, network, microphone or camera are used.
The actual Desktop event worker, CallWindow, FlowFrame and local lock UI run.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import traceback
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii.accounts import Accounts
from tg_ascii.desktop import Desktop
from tg_ascii import app_lock
from tg_ascii.calls import CallError
from tg_ascii.i18n import set_language

FINGERPRINT = '👩‍💻 🌈 ❤️ 🦊'


class SyntheticManager:
    def __init__(self, app, account):
        self.app, self.account = app, account
        self.actions = []
        self.closed = False
        self.frame = None
        self.local_frame = None
        self._snapshot = {}

    @property
    def snapshot(self):
        return dict(self._snapshot)

    def state(self, state, token, *, publish=True, **values):
        self._snapshot = dict(state=state, token=token, peer=900002,
            incoming=state == 'incoming', muted=False, video=False,
            remote_video=False, emojis=FINGERPRINT if state == 'active' else '', error='')
        self._snapshot.update(values)
        if publish:
            self.emit()

    def emit(self):
        self.app.worker.events.put((lambda snapshot: self.app.call_event(self.account, snapshot), self.snapshot))

    async def command(self, method, *, peer=None, token=None, **values):
        if token != self._snapshot['token'] or (peer is not None and peer != self._snapshot['peer']):
            raise CallError('This call is no longer active')
        self.actions.append(dict(method=method, peer=peer, token=token,
            values=values, worker_thread=threading.get_ident()))
        await asyncio.sleep(0.025)
        if method == 'accept':
            self._snapshot.update(state='active', incoming=False, video=values['video'], emojis=FINGERPRINT)
        elif method in ('hangup', 'decline'):
            self._snapshot.update(state='ended', remote_video=False)
        elif method == 'mute':
            self._snapshot['muted'] = values['value']
        elif method == 'set_camera':
            self._snapshot['video'] = values['value']
        self.emit()

    async def accept(self, peer=None, video=False, *, token=None):
        await self.command('accept', peer=peer, token=token, video=video)

    async def decline(self, peer=None, *, token=None):
        await self.command('decline', peer=peer, token=token)

    async def hangup(self, peer=None, *, token=None):
        await self.command('hangup', peer=peer, token=token)

    async def mute(self, value, *, token=None):
        await self.command('mute', token=token, value=value)

    async def set_camera(self, value, *, token=None):
        await self.command('set_camera', token=token, value=value)

    def take_frame(self):
        frame, self.frame = self.frame, None
        return frame

    def take_local_frame(self):
        frame, self.local_frame = self.local_frame, None
        return frame

    async def close(self):
        self.closed = True
        self.frame = None


def pump(root, condition, errors, timeout=10):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if errors:
            raise AssertionError(errors)
        if condition():
            return
        root.update()
        time.sleep(0.005)
    raise TimeoutError('Native call UI check timed out')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = dict(success=False, synthetic_only=True, platform=sys.platform,
                  callback_errors=[], checks=[], layouts=[])
    errors, checks = result['callback_errors'], result['checks']
    main_thread = threading.get_ident()
    root = app = None
    managers, windows = [], []
    previous_root = os.environ.get('TG_ASCII_DATA_DIR')
    with tempfile.TemporaryDirectory(prefix='tg-call-ui-') as directory:
        os.environ['TG_ASCII_DATA_DIR'] = directory
        try:
            set_language('en')
            root = tk.Tk()
            service = Accounts(demo=True, root=Path(directory))
            app = Desktop(root, demo=True, service=service)
            root.report_callback_exception = lambda kind, error, trace: errors.append(repr(error))
            root.tk.createcommand('bgerror', lambda value: errors.append('Tcl: ' + str(value)))
            app.show_error = lambda error: errors.append(repr(error))
            result['tk_version'] = root.tk.call('info', 'patchlevel')
            pump(root, lambda: app.chats and not app.busy, errors)
            first, second = app.ui_account, 'b' * 32
            service.entries[second] = {'label': 'Synthetic B'}
            service.labels[first], service.labels[second] = 'Synthetic A', 'Synthetic B'
            future = app.worker.submit(service.service(second).connect(), lambda _: None, app.show_error)
            pump(root, future.done, errors)
            future.result()
            for account in (first, second):
                manager = SyntheticManager(app, account)
                managers.append(manager)
                service.services[account].backend.call_manager = manager
                service.services[account].backend.names = {900002: 'Synthetic contact'}
            a, b = managers

            def window_for(account):
                pump(root, lambda: account in getattr(app, '_call_windows', {}), errors)
                window = app._call_windows[account]
                if window not in windows:
                    windows.append(window)
                window.window.geometry('360x360')
                try:
                    pump(root, lambda: window.window.winfo_width() == 360 and window.window.winfo_ismapped(), errors)
                except TimeoutError:
                    result['window_diagnostics'] = dict(geometry=window.window.geometry(),
                        minimum=window.window.minsize(), mapped=window.window.winfo_ismapped(),
                        state=window.window.state(), scaling=root.tk.call('tk', 'scaling'))
                    raise
                return window

            def layout(window, expected, label):
                if 'devices' in window.buttons and 'mute' in expected:
                    expected = (*expected, 'devices')
                if 'effects' in window.buttons and window.snapshot.get('video'):
                    expected = (*expected, 'effects')
                root.update_idletasks()
                actual = {key for key, button in window.buttons.items() if button.winfo_ismapped()}
                assert actual == set(expected), (label, actual, expected)
                rectangles = []
                for key in sorted(actual):
                    button = window.buttons[key]
                    x, y, width, height = button.winfo_x(), button.winfo_y(), button.winfo_width(), button.winfo_height()
                    assert x >= 0 and y >= 0 and x + width <= window.controls.winfo_width()
                    assert y + height <= window.controls.winfo_height()
                    root_x = button.winfo_rootx() - window.window.winfo_rootx()
                    root_y = button.winfo_rooty() - window.window.winfo_rooty()
                    assert root_x >= 0 and root_y >= 0 and root_x + width <= window.window.winfo_width(), (label, key, 'outside window width')
                    assert root_y + height <= window.window.winfo_height(), (label, key, 'outside window height')
                    for other in rectangles:
                        ox, oy, ow, oh = other['bounds']
                        assert x + width <= ox or ox + ow <= x or y + height <= oy or oy + oh <= y
                    rectangles.append(dict(button=key, bounds=[x, y, width, height]))
                result['layouts'].append(dict(state=label, window_width=window.window.winfo_width(),
                    control_width=window.controls.winfo_width(), controls=rectangles))

            a.state('incoming', 'call-a-1', requested_video=True)
            view = window_for(first)
            layout(view, ('accept', 'accept_video', 'hangup'), 'incoming_360px')
            view.buttons['accept'].invoke()
            assert view.pending and all(str(button['state']) == 'disabled' for button in view.buttons.values())
            pump(root, lambda: view.snapshot.get('state') == 'active' and not view.pending, errors)
            layout(view, ('mute', 'camera', 'screen', 'hangup'), 'active_360px')
            assert str(view.fingerprint['text']) == FINGERPRINT
            assert a.actions[-1]['method'] == 'accept' and a.actions[-1]['values']['video'] is False
            checks.append('incoming_answer_controls_pending_state_and_emoji_fingerprint')

            view.buttons['mute'].invoke()
            pump(root, lambda: view.snapshot.get('muted') and not view.pending, errors)
            assert str(view.buttons['mute']['text']) == 'Unmute microphone'
            view.buttons['camera'].invoke()
            app.switch_account(second)
            pump(root, lambda: app.ui_account == second and not app.busy and not view.pending and
                 view.snapshot.get('video'), errors)
            assert a.actions[-1]['method'] == 'set_camera' and not b.actions
            assert str(view.heading['text']).startswith('Synthetic A')
            checks.append('mute_and_camera_remain_bound_to_captured_account_after_real_demo_switch')

            a.state('incoming', 'call-a-2', publish=False)
            count = len(a.actions)
            view.buttons['mute'].invoke()  # The stale UI still carries call-a-1.
            pump(root, lambda: not view.pending, errors)
            assert len(a.actions) == count and 'no longer active' in str(view.status['text'])
            a.emit()
            pump(root, lambda: view.snapshot.get('token') == 'call-a-2', errors)
            app.call_event(first, dict(state='ended', token='call-a-1'))
            assert view.snapshot['token'] == 'call-a-2'
            layout(view, ('accept', 'accept_video', 'hangup'), 'incoming_after_switch_360px')
            view.buttons['hangup'].invoke()
            pump(root, lambda: view.snapshot.get('state') == 'ended' and not view.pending, errors)
            assert a.actions[-1]['method'] == 'decline'
            layout(view, (), 'ended_hidden_controls')
            pump(root, lambda: view.timer is None, errors)
            view.dismiss()
            assert not view.alive() and first not in app._call_windows
            checks.append('stale_token_and_event_ignored_decline_and_final_destroy')

            b.state('connecting', 'call-b-1')
            active = window_for(second)
            layout(active, ('mute', 'camera', 'screen', 'hangup'), 'connecting_360px')
            assert all(str(active.buttons[key]['state']) == 'disabled' for key in ('mute', 'camera'))
            assert str(active.buttons['hangup']['state']) == 'normal'
            b.state('active', 'call-b-1', remote_video=True)
            pump(root, lambda: active.snapshot.get('remote_video'), errors)
            b.frame = dict(width=16, height=16, rotation=0, data=b'\x80' * 384, format='i420', token='call-b-1')
            pump(root, lambda: active.photo is not None, errors)
            active.window.geometry('900x700')
            pump(root, lambda: active.window.winfo_width() == 900, errors)
            b.frame = dict(width=1280, height=720, rotation=0,
                data=b'\x80' * (1280 * 720 * 3 // 2), format='i420', token='call-b-1')
            pump(root, lambda: active.photo is not None and active.photo.width() > 500, errors)
            active.window.geometry('360x280')
            pump(root, lambda: active.window.winfo_width() == 360 and active.window.winfo_height() == 280, errors)
            layout(active, ('mute', 'camera', 'screen', 'hangup'), 'received_hd_video_minimum_window')
            active.window.geometry('600x440')
            pump(root, lambda: active.window.winfo_width() == 600, errors)
            layout(active, ('mute', 'camera', 'screen', 'hangup'), 'received_hd_video_default_window')
            checks.append('hd_video_cannot_push_controls_out_of_window_after_resize')
            b.state('active', 'call-b-1', video=True, remote_video=True)
            pump(root, lambda: active.snapshot.get('video'), errors)
            b.local_frame = dict(width=640, height=480, rotation=0,
                data=b'\x80' * (640 * 480 * 3 // 2), format='i420', token='call-b-1')
            pump(root, lambda: active.local_photo is not None, errors)
            assert abs(active.local_photo.width() / active.local_photo.height() - 4 / 3) < .03
            assert active.local_picture.winfo_ismapped()
            assert active.local_picture.winfo_y() + active.local_picture.winfo_height() <= active.viewport.winfo_height()
            layout(active, ('mute', 'camera', 'screen', 'hangup'), 'local_camera_picture_in_picture')
            checks.append('local_preview_preserves_aspect_and_stays_inside_video_viewport')
            b.state('active', 'call-b-1', remote_video=False)
            pump(root, lambda: active.photo is None and active.local_photo is None, errors)
            checks.append('connecting_permissions_native_video_decode_and_camera_off_clears_image')

            from tg_ascii.desktop_calls import CallWindow
            group = SyntheticManager(app, first)
            group.group_call, group.can_manage = True, True
            group.state('active', 'group-layout', publish=False, video=True, remote_video=True)
            group_view = CallWindow(app, first, group)
            windows.append(group_view)
            group_view.update(group.snapshot)
            for width, height in ((360, 280), (600, 440)):
                group_view.window.geometry(f'{width}x{height}')
                pump(root, lambda: group_view.window.winfo_width() == width, errors)
                layout(group_view, ('mute', 'camera', 'screen', 'hangup', 'members', 'invite', 'group_settings', 'end_all'), f'group_video_{width}px')
            group_view.window.destroy()
            checks.append('group_video_controls_and_moderation_remain_inside_minimum_window')

            password = 'Synthetic-call-lock-1.2'
            store = app_lock.LockStore(directory)
            store.save(app_lock.make_record(password))
            for entry in service.services.values():
                entry.backend.presence = AsyncMock(return_value=None)
            app.notification_center = Mock()
            app.demo = False  # The guard is real; Accounts/backends remain demo.
            assert app_lock.lock_app(app)
            panel = app._app_lock_panel
            pump(root, lambda: active.window.state() == 'withdrawn', errors)
            count = len(b.actions)
            active.buttons['camera'].invoke()
            assert len(b.actions) == count and not active.pending
            a.state('incoming', 'call-a-3')
            pump(root, lambda: first in app._call_windows, errors)
            late = app._call_windows[first]
            windows.append(late)
            pump(root, lambda: late.window.state() == 'withdrawn', errors)
            assert not late.window.winfo_viewable()
            late.buttons['accept'].invoke()
            assert not late.pending
            checks.append('lock_hides_existing_and_late_call_windows_and_blocks_actions')
            panel.password.set(password)
            panel.submit.invoke()
            pump(root, lambda: not app_lock.is_locked(app), errors)
            pump(root, lambda: active.window.winfo_ismapped() and late.window.winfo_ismapped(), errors)
            app.demo = True
            assert str(active.fingerprint['text']) == FINGERPRINT
            checks.append('unlock_restores_call_windows_and_fingerprint')

            late.buttons['accept_video'].invoke()
            pump(root, lambda: not late.pending and late.snapshot.get('state') == 'active', errors)
            assert a.actions[-1]['method'] == 'accept' and a.actions[-1]['values']['video'] is True
            late.dismiss()
            active.dismiss()
            pump(root, lambda: not late.alive() and not active.alive(), errors)
            assert not app._call_windows
            assert all(action['worker_thread'] != main_thread for manager in managers for action in manager.actions)
            checks.append('answer_with_video_dismiss_hangs_up_and_worker_actions_are_off_tk_thread')
            result['success'] = True
        except Exception as error:
            result['error'] = repr(error)
            result['traceback'] = traceback.format_exc()
        finally:
            if app is not None:
                app.demo = True
                async def close_managers():
                    await asyncio.gather(*(manager.close() for manager in managers))
                finished = app.worker.submit(close_managers(), lambda _: None, lambda error: errors.append(repr(error)))
                try:
                    pump(root, finished.done, errors)
                    app.busy = False
                    app.close()
                    pump(root, lambda: app.closed, errors)
                except Exception as error:
                    errors.append('Cleanup: ' + repr(error))
                    app.worker.stop()
                    try:
                        root.destroy()
                    except tk.TclError:
                        pass
                app.worker.thread.join(timeout=3)
                result['worker_stopped'] = not app.worker.thread.is_alive()
                result['all_call_timers_stopped'] = all(window.timer is None for window in windows)
                result['fake_managers_closed'] = all(manager.closed for manager in managers)
                result['success'] &= bool(app.closed and result['worker_stopped'] and
                    result['all_call_timers_stopped'] and result['fake_managers_closed'] and not errors)
            elif root is not None:
                root.destroy()
            if previous_root is None:
                os.environ.pop('TG_ASCII_DATA_DIR', None)
            else:
                os.environ['TG_ASCII_DATA_DIR'] = previous_root
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding='utf-8')
    print(payload)
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

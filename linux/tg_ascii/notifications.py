"""Native notification-center delivery (macOS, Windows; Linux through notify-send). No floating desktop windows."""
from collections import OrderedDict
import hashlib
import sys
import threading
import time
import uuid
from . import APP_NAME
from .i18n import tr
from xml.sax.saxutils import escape

APP_ID = 'org.tgas.desktop'


def notification_key(account, peer):
    # Keep account identifiers out of OS metadata and respect Windows' tag length.
    return hashlib.sha256(f'{account}:{peer}'.encode()).hexdigest()[:16]


def notification_xml(title, body, reply=False, *, silent=True):
    clean = lambda value: ''.join(c for c in str(value) if c >= ' ' or c in '\n\t')
    actions = ('<actions><input id="reply" type="text" placeHolder=' + '"' + escape(tr('Reply'), {'"':'&quot;'}) + '"/>'
               '<action content="' + escape(tr('Reply'), {'"':'&quot;'}) + '" arguments="reply" activationType="background" hint-inputId="reply"/></actions>') if reply else ''
    return ('<toast launch="open"><visual><binding template="ToastGeneric"><text>' + escape(clean(title)) +
            '</text><text>' + escape(clean(body)) +
            '</text></binding></visual><audio silent="' + ('true' if silent else 'false') + '"/>' + actions + '</toast>')


class WindowsCenter:
    def __init__(self):
        import winreg
        import ctypes
        identify = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        identify.argtypes = [ctypes.c_wchar_p]
        identify.restype = ctypes.c_long
        if identify(APP_ID) < 0: raise OSError('Cannot register the notification app identity.')
        from winrt.windows.ui.notifications import ToastNotificationManager
        # Per-user identity for this portable app, without administrator access.
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, 'Software\\Classes\\AppUserModelId\\' + APP_ID) as key:
            winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(key, 'ShowInSettings', 0, winreg.REG_DWORD, 1)
        self.notifier = ToastNotificationManager.create_toast_notifier_with_id(APP_ID)
        self.retained = OrderedDict()
        self.privacy_locked = False

    def set_locked(self, locked):
        self.privacy_locked = bool(locked)
        if not locked:
            return
        # Explicit app identity restricts removal to this client's notifications.
        from winrt.windows.ui.notifications import ToastNotificationManager
        try:
            ToastNotificationManager.history.clear_with_id(APP_ID)
        finally:
            for toast in tuple(self.retained.values()):
                try:
                    self.notifier.hide(toast)
                except Exception:
                    pass
            self.retained.clear()

    def show(self, title, body, key, report, reply=None, activate=None, *, sound=False):
        if getattr(self, 'privacy_locked', False):
            title, body, reply = APP_NAME, tr('New message'), None
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import ToastNotification
        document = XmlDocument()
        document.load_xml(notification_xml(title, body, bool(reply), silent=not sound))
        toast = ToastNotification(document)
        toast.tag, toast.group = key, 'messages'
        toast.suppress_popup = False
        toast.add_failed(lambda _, event: report('Windows: ' + str(event.error_code)))
        if reply or activate:
            def activated(_, event):
                try:
                    from winrt.windows.ui.notifications import ToastActivatedEventArgs
                    from winrt.system import unbox_string
                    args = event.as_(ToastActivatedEventArgs)
                    if args.arguments == 'reply' and reply and not getattr(self, 'privacy_locked', False):
                        value = args.user_input['reply']
                        reply(value if isinstance(value, str) else unbox_string(value))
                    elif args.arguments in ('', 'open') and activate:
                        activate()
                except Exception as exc: report(str(exc))
            toast.add_activated(activated)
        self.retained[key] = toast
        while len(self.retained) > 500: self.retained.popitem(last=False)
        from winrt.windows.ui.notifications import NotificationSetting
        try:
            setting = self.notifier.setting
        except OSError as error:
            # A fresh portable AUMID has no notification settings record until
            # its first toast. ERROR_NOT_FOUND is not a denial: let Windows
            # enforce its policy when showing the toast instead of permanently
            # preventing that first delivery. Other failures remain visible.
            code = getattr(error, 'winerror', 0) or 0
            if code & 0xffffffff != 0x80070490:
                raise
            setting = None
        if setting is not None and setting != NotificationSetting.ENABLED:
            report('Notifications are disabled in Windows settings.'); return
        self.notifier.show(toast)


_mac_delegate_class = None


class MacCenter:
    def __init__(self):
        import Foundation
        # Calling UNUserNotificationCenter from an unbundled Python process can
        # terminate the process. Only a real, identified .app may use this API.
        if Foundation.NSBundle.mainBundle().bundleIdentifier() != APP_ID:
            raise RuntimeError('Native notifications require the compiled TG-ASCII.app.')
        import UserNotifications as un
        import objc
        global _mac_delegate_class
        if _mac_delegate_class is None:
            class TgAsNotificationDelegate(Foundation.NSObject, protocols=[objc.protocolNamed('UNUserNotificationCenterDelegate')]):
                def userNotificationCenter_willPresentNotification_withCompletionHandler_(self, center, notification, completion):
                    completion(un.UNNotificationPresentationOptionList | un.UNNotificationPresentationOptionBanner)
                def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(self, center, response, completion):
                    try:
                        token = response.notification().request().content().userInfo().get('reply_token')
                        if response.actionIdentifier() == 'reply':
                            self.target.handle_reply(token, str(response.userText()))
                        elif response.actionIdentifier() == un.UNNotificationDefaultActionIdentifier:
                            self.target.handle_open(token)
                    finally: completion()
            _mac_delegate_class = TgAsNotificationDelegate
        self.api = un
        self.delegate = _mac_delegate_class.alloc().init()
        self.delegate.target = self
        self.center = un.UNUserNotificationCenter.currentNotificationCenter()
        self.center.setDelegate_(self.delegate)
        self.pending = OrderedDict()
        self.requesting = False
        self.lock = threading.RLock()
        self.actions = OrderedDict()
        self.privacy_locked = False
        self.privacy_generation = 0

    def set_locked(self, locked):
        with self.lock:
            self.privacy_locked = bool(locked)
            self.privacy_generation = getattr(self, 'privacy_generation', 0) + 1
            if not locked:
                return
            for key, (_, _, report, token, _, sound) in tuple(self.pending.items()):
                self.pending[key] = (APP_NAME, tr('New message'), report, token, False, sound)
            for action in self.actions.values():
                action['reply'] = None
            self.center.removeAllPendingNotificationRequests()
            self.center.removeAllDeliveredNotifications()

    def handle_reply(self, token, text):
        with self.lock: action = self.actions.pop(token, {})
        callback=action.get('reply') if not getattr(self, 'privacy_locked', False) else None
        if callback: callback(text)

    def handle_open(self, token):
        with self.lock: action = self.actions.pop(token, {})
        callback=action.get('open')
        if callback: callback()

    def show(self, title, body, key, report, reply=None, activate=None, *, sound=False):
        # Serialize permission/settings callbacks through one request; coalesce
        # messages from the same chat while the permission sheet is on screen.
        token = uuid.uuid4().hex
        if reply:
            action = self.api.UNTextInputNotificationAction.actionWithIdentifier_title_options_textInputButtonTitle_textInputPlaceholder_(
                'reply', tr('Reply'), self.api.UNNotificationActionOptionAuthenticationRequired, tr('Enviar >'), tr('Reply'))
            category = self.api.UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_('messages', [action], [], 0)
            self.center.setNotificationCategories_({category})
        with self.lock:
            if getattr(self, 'privacy_locked', False):
                title, body, reply = APP_NAME, tr('New message'), None
            if reply or activate: self.actions[token] = {'reply':reply,'open':activate}
            while len(self.actions) > 500: self.actions.popitem(last=False)
            self.pending[key] = (title, body, report, token if reply or activate else None, bool(reply), sound)
            while len(self.pending) > 50: self.pending.popitem(last=False)
            if self.requesting: return
            self.requesting = True
        def authorized(granted, error):
            with self.lock:
                pending = list(self.pending.items())
                self.pending.clear()
                self.requesting = False
            for ident, (heading, text, callback, reply_token, can_reply, play_sound) in pending:
                if not granted or error:
                    callback('Notification permission is disabled in macOS.'); continue
                with self.lock:
                    # The permission callback may arrive after the interface locks.
                    # Check again immediately before submitting to the OS.
                    if getattr(self, 'privacy_locked', False):
                        heading, text, can_reply = APP_NAME, tr('New message'), False
                    generation = getattr(self, 'privacy_generation', 0)
                    content = self.api.UNMutableNotificationContent.alloc().init()
                    content.setTitle_(heading)
                    content.setBody_(text)
                    if play_sound:
                        content.setSound_(self.api.UNNotificationSound.defaultSound())
                    content.setThreadIdentifier_(ident)
                    if reply_token:
                        if can_reply: content.setCategoryIdentifier_('messages')
                        content.setUserInfo_({'reply_token': reply_token})
                    request = self.api.UNNotificationRequest.requestWithIdentifier_content_trigger_(ident, content, None)
                    def completed(err, fn=callback, ident=ident, generation=generation):
                        with self.lock:
                            if generation != getattr(self, 'privacy_generation', 0):
                                # Covers an add already handed to the OS when lock
                                # removed the earlier delivered/pending requests.
                                self.center.removePendingNotificationRequestsWithIdentifiers_([ident])
                                self.center.removeDeliveredNotificationsWithIdentifiers_([ident])
                        if err:
                            fn(str(err))
                    self.center.addNotificationRequest_withCompletionHandler_(request, completed)
        options = self.api.UNAuthorizationOptionAlert
        if sound:
            options |= self.api.UNAuthorizationOptionSound
        self.center.requestAuthorizationWithOptions_completionHandler_(options, authorized)



class LinuxCenter:
    """freedesktop.org notifications (GNOME, KDE, …) through libnotify's
    notify-send (1.5.5). Clicking a notification opens its chat; locking the
    app closes every notification it has shown. No D-Bus library is bundled:
    notify-send and gdbus are part of every desktop install."""
    MAX_WAITING = 8

    def __init__(self):
        import shutil
        self.tool = shutil.which('notify-send')
        if self.tool is None:
            raise RuntimeError('notify-send (libnotify) is not installed.')
        self.gdbus = shutil.which('gdbus')
        from .logos import asset_path
        self.icon = str(asset_path('title-short', 'dark'))
        self.lock = threading.Lock()
        self.ids = OrderedDict()      # key -> notification id
        self.waiting = OrderedDict()  # key -> process waiting for a click
        self.privacy_locked = False

    def set_locked(self, locked):
        self.privacy_locked = bool(locked)
        if not locked:
            return
        with self.lock:
            ids, self.ids = list(self.ids.values()), OrderedDict()
            waiting, self.waiting = list(self.waiting.values()), OrderedDict()
        for process in waiting:
            try:
                process.terminate()
            except OSError:
                pass
        for ident in ids:
            self._close(ident)

    def _close(self, ident):
        if not self.gdbus or not ident:
            return
        import subprocess
        try:
            subprocess.run([self.gdbus, 'call', '--session', '--dest', 'org.freedesktop.Notifications',
                            '--object-path', '/org/freedesktop/Notifications',
                            '--method', 'org.freedesktop.Notifications.CloseNotification', str(ident)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass

    def show(self, title, body, key, report, reply=None, activate=None, *, sound=False):
        import subprocess
        clean = lambda value: ''.join(c for c in str(value) if c >= ' ' or c in '\n\t')
        command = [self.tool, f'--app-name={APP_NAME}', f'--icon={self.icon}', '--print-id']
        with self.lock:
            previous = self.ids.get(key)
            old = self.waiting.pop(key, None)
        if previous:
            command.append(f'--replace-id={previous}')  # One notification per chat, updated.
        if sound:
            command.append('--hint=string:sound-name:message-new-instant')
        if activate is not None:
            command.append('--action=default=' + tr('Open'))
        command += ['--', clean(title)[:200], clean(body)[:1000]]
        if old is not None:
            try:
                old.terminate()
            except OSError:
                pass
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        with self.lock:
            if activate is not None:
                self.waiting[key] = process
                while len(self.waiting) > self.MAX_WAITING:
                    _, oldest = self.waiting.popitem(last=False)
                    try:
                        oldest.terminate()  # The notification stays; only its click is forgotten.
                    except OSError:
                        pass

        def watch():
            ident = process.stdout.readline().strip()
            if ident.isdigit():
                with self.lock:
                    self.ids[key] = ident
                    self.ids.move_to_end(key)
                    while len(self.ids) > 64:
                        self.ids.popitem(last=False)
            action = process.stdout.readline().strip() if activate is not None else ''
            code = process.wait()
            with self.lock:
                if self.waiting.get(key) is process:
                    self.waiting.pop(key, None)
            if action == 'default' and activate is not None and not self.privacy_locked:
                activate()
            elif code not in (0, -15) and not ident:
                report('Linux: ' + (process.stderr.read().strip()[:200] or f'notify-send {code}'))
        threading.Thread(target=watch, name='tg-linux-notification', daemon=True).start()


class NotificationCenter:
    def __init__(self, report):
        self.report = report
        self.adapter = None
        self.unavailable = False
        self.retry_at = 0.0
        self.locked = False

    def set_locked(self, locked):
        self.locked = bool(locked)
        try:
            # A lock also clears this app's notifications from an earlier run.
            # Adapter construction itself does not request notification consent.
            if self.adapter is None and locked:
                self._create_adapter()
            if self.adapter is not None:
                self.adapter.set_locked(self.locked)
        except Exception as exc:
            self.report(str(exc))

    def _create_adapter(self):
        if sys.platform == 'darwin': self.adapter = MacCenter()
        elif sys.platform == 'win32': self.adapter = WindowsCenter()
        elif sys.platform.startswith('linux'): self.adapter = LinuxCenter()
        else: raise RuntimeError('Native notifications are supported on macOS, Windows and Linux.')

    def show(self, title, body, key, reply=None, activate=None, *, sound=False, on_failed=None):
        if self.unavailable and time.monotonic() < self.retry_at:
            if on_failed:
                on_failed()
            return False
        self.unavailable = False
        def failed(error):
            if on_failed:
                on_failed()
            self.report(error)
        try:
            if self.adapter is None:
                self._create_adapter()
                self.adapter.set_locked(self.locked)
            if self.locked:
                title, body, reply = APP_NAME, tr('New message'), None
            self.adapter.show(title, body, key, failed, reply, activate, sound=sound)
            return True
        except Exception as exc:
            # No modal error and no desktop-popup fallback. The app remains usable.
            self.unavailable = True
            self.retry_at = time.monotonic() + 30
            self.adapter = None
            failed(str(exc))
            return False


def clear_locked_notification_history(report=None):
    """Clear this app's old OS notices before creating Accounts at startup.

    Adapter initialization and history removal do not ask for notification
    consent or open Telegram. Retain the returned center until the startup
    panel closes, so macOS keeps its native delegate alive.
    """
    center = NotificationCenter(report or (lambda error: None))
    center.set_locked(True)
    return center


def app_foreground(root):
    try:
        return root.state() == 'normal' and root.focus_displayof() is not None
    except Exception:
        return False


def foreground_view(app):
    """Return the full app view containing focus, including its own dialogs."""
    owner = getattr(app, '_linked_owner', None) or app
    try:
        widget = owner.root.focus_displayof()
    except Exception:
        widget = None
    if widget is not None:
        views = (owner, *tuple(getattr(owner, '_app_windows', ())))
        roots = {id(view.root): view for view in views if not getattr(view, 'closed', False)}
        current = widget
        while current is not None:
            view = roots.get(id(current))
            if view is not None and app_foreground(view.root):
                return view
            current = getattr(current, 'master', None)
        # Lightweight adapters and native widgets may not expose their parent.
        if app_foreground(owner.root):
            return owner
    return None


class InlineNotice:
    """One passive notice inside the main window, never a top-level window."""
    def __init__(self, root):
        self.root, self.frame, self.timer, self.watch = root, None, None, None
        self.replying=False;self.pending=None

    def close(self):
        self.replying=False;self.pending=None
        for timer in (self.timer, self.watch):
            if timer:
                try: self.root.after_cancel(timer)
                except Exception: pass
        self.timer = self.watch = None
        if self.frame is not None:
            self.frame.destroy()
            self.frame = None

    def finish(self):
        pending=self.pending
        self.close()
        if pending:
            self.root.after_idle(lambda:self.show(*pending) if app_foreground(self.root) else None)

    def show(self, title, body, activate=None, reply=None):
        import tkinter as tk
        from tkinter import ttk
        from .themes import _palette
        if self.frame is not None and self.replying:
            self.pending=(title,body,activate,reply)
            return  # An incoming notice must not erase a reply being composed.
        self.close()
        self.frame = tk.Frame(self.root, bg=_palette['panel'], highlightbackground=_palette['line'], highlightthickness=1)
        heading = tk.Frame(self.frame, bg=_palette['panel'])
        heading.pack(fill='x')
        ttk.Button(heading, text='×', width=2, command=self.finish).pack(side='right', padx=3, pady=3)
        self.title = tk.Label(heading, text=title, anchor='w', justify='left', bg=_palette['panel'], fg=_palette['strong'])
        self.title.pack(side='left', fill='x', expand=True, padx=8)
        self.body = tk.Label(self.frame, text=body, anchor='w', justify='left', bg=_palette['panel'], fg=_palette['text'])
        self.body.pack(fill='x', padx=8, pady=(0,8))
        if reply:
            reply_row=ttk.Frame(self.frame)
            entry=ttk.Entry(reply_row)
            entry.pack(side='left',fill='x',expand=True)
            submitted=[False]
            def submit(_=None):
                if submitted[0]:return 'break'
                text=entry.get()
                if not text.strip():return 'break'
                submitted[0]=True
                reply(text)
                self.finish()
                return 'break'
            ttk.Button(reply_row,text=tr('Enviar >'),command=submit).pack(side='right',padx=(4,0))
            def start_reply():
                self.replying=True
                if self.timer:
                    self.root.after_cancel(self.timer);self.timer=None
                reply_row.pack(fill='x',padx=8,pady=(0,8))
                entry.focus_set()
            ttk.Button(heading,text=tr('Reply'),command=start_reply).pack(side='right',padx=3,pady=3)
            entry.bind('<Return>',submit)
            entry.bind('<Escape>',lambda e:(self.finish(),'break')[1])
        if activate:
            used=[False]
            def open_message(_=None):
                if used[0]:return 'break'
                used[0]=True;self.close();self.root.after_idle(activate)
                return 'break'
            for widget in (self.frame,heading,self.title,self.body):
                widget.configure(cursor='hand2')
                widget.bind('<Button-1>',open_message)
            self.frame.configure(takefocus=True)
            self.frame.bind('<Return>',open_message)
            self.frame.bind('<space>',open_message)
        self.frame.place(x=10, y=10, width=min(320, max(160, self.root.winfo_width()-20)))
        self.frame.lift()
        self.timer = self.root.after(6000, self.close)
        self.monitor()

    def monitor(self):
        self.watch = None
        if not app_foreground(self.root) and not self.replying: self.close(); return
        width = min(320, max(160, self.root.winfo_width()-20))
        self.frame.place_configure(width=width)
        self.title.configure(wraplength=width-55)
        self.body.configure(wraplength=width-20)
        self.watch = self.root.after(200, self.monitor)

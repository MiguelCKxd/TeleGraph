"""Optional system dialogs. No action is executed by this presentation layer."""
import asyncio
import re


CANCELLED = {'handled': True, 'cancelled': True}
UNHANDLED = {'handled': False}


def validated(value):
    """Bound untrusted bridge data and keep the native adapters deliberately small."""
    if not isinstance(value, dict):
        raise ValueError('dialog')
    kind = value.get('kind')
    if kind not in ('menu', 'confirm', 'prompt'):
        raise ValueError('dialog kind')
    request_id = value.get('id')
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{32}', request_id):
        raise ValueError('dialog id')

    def text(key, limit, default=''):
        result = value.get(key, default)
        if not isinstance(result, str) or len(result.encode('utf-16-le')) // 2 > limit:
            raise ValueError('dialog field')
        return result

    actions = value.get('actions')
    if not isinstance(actions, list) or not 1 <= len(actions) <= (32 if kind == 'menu' else 1):
        raise ValueError('dialog actions')
    clean = []
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get('label'), str) or not 1 <= len(action['label']) <= 256:
            raise ValueError('dialog action')
        clean.append({'label': action['label'], 'destructive': action.get('destructive') is True})
    result = {'id': request_id, 'kind': kind, 'title': text('title', 4096),
              'message': text('message', 4096), 'cancel': text('cancel', 256),
              'actions': clean, 'reduce_motion': value.get('reduce_motion') is True}
    if not result['cancel']:
        raise ValueError('dialog cancel')
    if kind == 'prompt':
        input_type = value.get('input_type', 'text')
        if input_type not in ('text', 'password', 'email', 'tel', 'url'):
            raise ValueError('dialog input')
        maximum = value.get('maxlength', 4096)
        if type(maximum) is not int or not 1 <= maximum <= 4096:
            raise ValueError('dialog length')
        result.update(input_type=input_type, maxlength=maximum,
                      value=text('value', maximum), placeholder=text('placeholder', 256))
    return result


class DialogService:
    """One native modal at a time, with account and backend identity checks."""
    def __init__(self, core, present, timeout=300):
        self.core, self.present, self.timeout = core, present, timeout
        self.pending = None

    def permitted(self, account, backend):
        return (account == self.core.account and backend is self.core.backend and
                self.core.stage == 'ready' and not self.core.locked and
                self.core.appearance().get('native_dialogs') is True)

    async def request(self, request, account):
        backend = self.core.backend
        if not self.permitted(account, backend):
            return dict(UNHANDLED)
        data = validated(request)
        if self.pending:
            # Repeated HTTP requests must not present or execute a second modal.
            return dict(CANCELLED)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        pending = {'id': data['id'], 'account': account, 'future': future, 'cancel': None}
        self.pending = pending

        def finish(result):
            if future.done():
                return
            if not self.permitted(account, backend):
                result = dict(CANCELLED)
            elif not isinstance(result, dict) or result.get('handled') is not True:
                result = dict(UNHANDLED)
            elif result.get('cancelled') is True:
                result = dict(CANCELLED)
            else:
                index = result.get('index')
                if type(index) is not int or not 0 <= index < len(data['actions']):
                    result = dict(CANCELLED)
                else:
                    answer = {'handled': True, 'cancelled': False, 'index': index}
                    if data['kind'] == 'prompt':
                        content = result.get('text')
                        if not isinstance(content, str) or len(content.encode('utf-16-le')) // 2 > data['maxlength']:
                            result = dict(CANCELLED)
                        else:
                            answer['text'] = content
                            result = answer
                    else:
                        result = answer
            future.set_result(result)

        def received(result):
            try:
                loop.call_soon_threadsafe(finish, result)
            except RuntimeError:
                pass  # App shutdown already closed the owning worker loop.

        try:
            pending['cancel'] = self.present(data, received)
            return await asyncio.wait_for(future, self.timeout)
        except asyncio.TimeoutError:
            return dict(CANCELLED)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never log request/response values: prompts may contain private text.
            return dict(UNHANDLED)
        finally:
            if self.pending is pending:
                self.pending = None
            self.dismiss(pending)

    @staticmethod
    def dismiss(pending):
        if pending['cancel']:
            try:
                pending['cancel']()
            except Exception:
                pass  # A closed native UI must not interrupt account shutdown.

    def cancel(self, request_id=None, account=None):
        pending = self.pending
        if not pending or (request_id is not None and request_id != pending['id']) or (account is not None and account != pending['account']):
            return False
        if not pending['future'].done():
            pending['future'].set_result(dict(CANCELLED))
        self.dismiss(pending)
        return True


async def request(core, request, account):
    service = getattr(core, 'native_dialogs', None)
    return await service.request(request, account) if service else dict(UNHANDLED)


def cancel(core, request_id=None, account=None):
    service = getattr(core, 'native_dialogs', None)
    return service.cancel(request_id, account) if service else False


def install_ios(app):
    from rubicon.objc import Block, ObjCClass, ObjCInstance, ns_from_py, py_from_ns, objc_id
    factory = ObjCClass('TGNativeDialogs')

    def present(data, done):
        handle = {'session': None, 'block': None, 'cancelled': False}

        def completed(result):
            try:
                done(py_from_ns(ObjCInstance(result)))
            finally:
                handle['session'] = handle['block'] = None

        def run():
            if handle['cancelled']:
                return
            try:
                handle['block'] = Block(completed, None, objc_id)
                handle['session'] = factory.presentFromWebView_request_completion_(
                    app.webview._impl.native, ns_from_py(data), handle['block'])
                if not handle['session']:
                    handle['block'] = None
                    done(dict(UNHANDLED))
            except Exception:
                handle['session'] = handle['block'] = None
                done(dict(UNHANDLED))

        def dismiss():
            handle['cancelled'] = True

            def run_cancel():
                if handle['session']:
                    handle['session'].cancel()
                handle['session'] = handle['block'] = None
            app.on_main_thread(run_cancel)
        app.on_main_thread(run)
        return dismiss
    app.core.native_dialogs = DialogService(app.core, present)


def _contrast_ratio(foreground, background):
    """sRGB text contrast, including the foreground's Android ARGB opacity."""
    opacity = (foreground >> 24 & 255) / 255

    def luminance(channels):
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                  for value in channels]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))

    back = [(background >> shift & 255) / 255 for shift in (16, 8, 0)]
    front = [(foreground >> shift & 255) / 255 * opacity + channel * (1 - opacity)
             for shift, channel in zip((16, 8, 0), back)]
    light, dark = sorted((luminance(front), luminance(back)), reverse=True)
    return (light + .05) / (dark + .05)


def _android_button_contrast(dialog):
    """Keep native accent colors unless they disappear on the dialog's own theme.

    BeeWare's Activity can supply a dark accent to an otherwise dark Android
    dialog. Resolve the *dialog* context, not the web page or Activity background,
    and retain the native foreground ColorStateList (including disabled states).
    OEM drawables without an opaque theme surface remain under system control.
    """
    from java import jarray, jclass
    attrs = jclass('android.R$attr')
    values = dialog.getContext().obtainStyledAttributes(jarray('I')([
        attrs.colorBackgroundFloating, attrs.textColorPrimary]))
    try:
        background = int(values.getColor(0, 0))
        colors = values.getColorStateList(1)
    finally:
        values.recycle()
    if background >> 24 & 255 != 255 or colors is None:
        return
    for which in (-1, -2, -3):  # DialogInterface positive, negative and neutral.
        button = dialog.getButton(which)
        if button is None or not button.isEnabled():
            continue
        original = int(button.getCurrentTextColor())
        themed = int(colors.getColorForState(button.getDrawableState(), colors.getDefaultColor()))
        if _contrast_ratio(original, background) < 4.5 <= _contrast_ratio(themed, background):
            button.setTextColor(colors)


def install_android(app, activity):
    from java import dynamic_proxy, jarray, jclass
    Builder = jclass('android.app.AlertDialog$Builder')
    OnClick = jclass('android.content.DialogInterface$OnClickListener')
    OnDismiss = jclass('android.content.DialogInterface$OnDismissListener')
    Lifecycle = jclass('android.app.Application$ActivityLifecycleCallbacks')
    application = activity.getApplication()

    def present(data, done):
        handle = {'dialog': None, 'cancelled': False, 'finished': False, 'listeners': []}

        def finish(result):
            if handle['finished']:
                return
            handle['finished'] = True
            lifecycle = handle.pop('lifecycle', None)
            if lifecycle:
                application.unregisterActivityLifecycleCallbacks(lifecycle)
            done(result)
            handle['listeners'].clear()

        class Click(dynamic_proxy(OnClick)):
            def __init__(self, callback):
                super().__init__(); self.callback = callback

            def onClick(self, dialog, which):
                self.callback(which)

        class Dismiss(dynamic_proxy(OnDismiss)):
            def onDismiss(self, dialog):
                # Selection callbacks run before Android dismisses the dialog.
                finish(handle.pop('result', dict(CANCELLED)))
                handle['dialog'] = None

        class ActivityState(dynamic_proxy(Lifecycle)):
            def onActivityPaused(self, current):
                if current == activity and handle['dialog']:
                    handle['dialog'].dismiss()

            def onActivityDestroyed(self, current):
                self.onActivityPaused(current)

            def onActivityCreated(self, current, bundle): pass
            def onActivityStarted(self, current): pass
            def onActivityResumed(self, current): pass
            def onActivityStopped(self, current): pass
            def onActivitySaveInstanceState(self, current, bundle): pass

        def run():
            if handle['cancelled']:
                return
            try:
                if activity.isFinishing() or activity.isDestroyed():
                    finish(dict(UNHANDLED)); return
                builder = Builder(activity).setTitle(data['title'])
                field = None
                if data['kind'] == 'prompt':
                    field = jclass('android.widget.EditText')(activity)
                    types = {'text': 1, 'password': 129, 'email': 33, 'tel': 3, 'url': 17}
                    field.setInputType(types[data['input_type']])
                    field.setSingleLine(True)
                    field.setFilters(jarray(jclass('android.text.InputFilter'))([
                        jclass('android.text.InputFilter$LengthFilter')(data['maxlength'])]))
                    field.setText(data['value']); field.setHint(data['placeholder'])
                    builder.setView(field)
                if data['kind'] != 'menu' and data['message']:
                    builder.setMessage(data['message'])

                def selected(index):
                    result = {'handled': True, 'cancelled': False, 'index': index}
                    if field is not None:
                        result['text'] = str(field.getText())
                    handle['result'] = result
                listener = Click(lambda index: selected(index if data['kind'] == 'menu' else 0))
                negative = Click(lambda _: None)
                dismissal = Dismiss()
                handle['listeners'].extend([listener, negative, dismissal])
                if data['kind'] == 'menu':
                    builder.setItems(jarray(jclass('java.lang.CharSequence'))([action['label'] for action in data['actions']]), listener)
                else:
                    builder.setPositiveButton(data['actions'][0]['label'], listener)
                builder.setNegativeButton(data['cancel'], negative)
                dialog = builder.create()
                dialog.setOnDismissListener(dismissal)
                handle['dialog'] = dialog
                lifecycle = ActivityState(); handle['lifecycle'] = lifecycle
                application.registerActivityLifecycleCallbacks(lifecycle)
                if data['reduce_motion']:
                    dialog.getWindow().setWindowAnimations(0)
                dialog.show()
                try:
                    _android_button_contrast(dialog)
                except Exception:
                    # Theme resources vary by OEM; styling must not cancel a dialog.
                    pass
            except Exception:
                if handle['dialog']:
                    handle['dialog'].dismiss()
                finish(dict(UNHANDLED))

        def dismiss():
            handle['cancelled'] = True
            app.loop.call_soon_threadsafe(lambda: handle['dialog'].dismiss() if handle['dialog'] else None)
        app.loop.call_soon_threadsafe(run)
        return dismiss
    app.core.native_dialogs = DialogService(app.core, present)

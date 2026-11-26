"""Exercise native bridge lifecycle with controlled OS callbacks (no user data)."""
import asyncio
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tg_ascii_mobile import native_dialogs


DATA = {'id': 'a' * 32, 'kind': 'prompt', 'title': 'Nombre', 'cancel': 'Cancelar',
        'actions': [{'label': 'Guardar'}], 'value': 'Original', 'maxlength': 40}


class NativeAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.core = SimpleNamespace(account='a', backend=object(), stage='ready', locked=False,
                                    appearance=lambda: {'native_dialogs': True})
        self.app = SimpleNamespace(core=self.core, loop=self.loop,
                                   on_main_thread=lambda run: self.loop.call_soon(run),
                                   webview=SimpleNamespace(_impl=SimpleNamespace(native=object())))

    async def start(self):
        task = asyncio.create_task(self.core.native_dialogs.request(DATA, 'a'))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return task

    async def test_ios_completion_bridges_dictionary_and_dismisses_on_cancel(self):
        class Session:
            def cancel(self):
                self.done({'handled': True, 'cancelled': True})

        session = Session()

        class Factory:
            @staticmethod
            def presentFromWebView_request_completion_(web, data, callback):
                session.done = callback
                return session
        module = SimpleNamespace(Block=lambda function, *_: function, ObjCClass=lambda _: Factory,
                                 ObjCInstance=lambda value: value, ns_from_py=lambda value: value,
                                 py_from_ns=lambda value: value, objc_id=object)
        with patch.dict(sys.modules, {'rubicon.objc': module}):
            native_dialogs.install_ios(self.app)
            task = await self.start()
            session.done({'handled': True, 'cancelled': False, 'index': 0, 'text': 'Nuevo'})
            self.assertEqual((await task)['text'], 'Nuevo')
            task = await self.start()
            self.core.native_dialogs.cancel()
            self.assertEqual(await task, native_dialogs.CANCELLED)
            await asyncio.sleep(0)

    async def test_ios_cancel_before_main_queue_runs_never_presents(self):
        queued = []
        self.app.on_main_thread = queued.append
        module = SimpleNamespace(Block=lambda function, *_: function, ObjCClass=lambda _: None,
                                 ObjCInstance=lambda value: value, ns_from_py=lambda value: value,
                                 py_from_ns=lambda value: value, objc_id=object)
        with patch.dict(sys.modules, {'rubicon.objc': module}):
            native_dialogs.install_ios(self.app)
            task = await self.start()
            self.core.native_dialogs.cancel()
            self.assertEqual(await task, native_dialogs.CANCELLED)
            for callback in queued:
                callback()
            self.assertIsNone(self.core.native_dialogs.pending)

    async def test_android_result_waits_for_dismiss_and_activity_pause_cancels(self):
        listeners, dialogs, builders = [], [], []
        application = SimpleNamespace(registerActivityLifecycleCallbacks=listeners.append,
                                      unregisterActivityLifecycleCallbacks=listeners.remove)
        activity = SimpleNamespace(getApplication=lambda: application, isFinishing=lambda: False,
                                   isDestroyed=lambda: False)

        class Field:
            def __init__(self, activity): self.text = ''
            def setInputType(self, value): pass
            def setSingleLine(self, value): pass
            def setFilters(self, value): pass
            def setHint(self, value): pass
            def setText(self, value): self.text = value
            def getText(self): return self.text

        class Dialog:
            def setOnDismissListener(self, listener): self.listener = listener
            def show(self): pass
            def dismiss(self): self.listener.onDismiss(self)
            def getWindow(self): return SimpleNamespace(setWindowAnimations=lambda value: None)

        class Builder:
            def __init__(self, activity): builders.append(self)
            def setTitle(self, title): return self
            def setMessage(self, value): pass
            def setView(self, field): self.field = field
            def setPositiveButton(self, title, listener): self.positive = listener
            def setNegativeButton(self, title, listener): self.negative = listener
            def setItems(self, items, listener): self.items = listener
            def create(self):
                dialog = Dialog(); dialogs.append(dialog); return dialog

        classes = {'android.app.AlertDialog$Builder': Builder, 'android.widget.EditText': Field,
                   'android.text.InputFilter$LengthFilter': lambda limit: limit}
        module = SimpleNamespace(dynamic_proxy=lambda _: object, jarray=lambda _: list,
                                 jclass=lambda name: classes.get(name, object))
        with patch.dict(sys.modules, {'java': module}):
            native_dialogs.install_android(self.app, activity)
            task = await self.start()
            builders[0].field.text = 'Editado'
            builders[0].positive.onClick(dialogs[0], -1)
            self.assertFalse(task.done())
            dialogs[0].dismiss()
            self.assertEqual((await task)['text'], 'Editado')
            self.assertEqual(listeners, [])
            task = await self.start()
            listeners[0].onActivityPaused(activity)
            self.assertEqual(await task, native_dialogs.CANCELLED)
            self.assertEqual(listeners, [])


if __name__ == '__main__':
    unittest.main()

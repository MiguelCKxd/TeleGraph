"""Native presentation cannot carry an action into another account/context."""
import asyncio
from types import SimpleNamespace
import unittest

from tg_ascii_mobile.native_dialogs import CANCELLED, UNHANDLED, DialogService, validated


def request(**values):
    return {'id': 'a' * 32, 'kind': 'confirm', 'title': 'Confirmar', 'cancel': 'Cancelar',
            'actions': [{'label': 'Continuar'}], **values}


class DialogValidationTests(unittest.TestCase):
    def test_invalid_payloads_do_not_enter_native_presenter(self):
        for value in (None, request(kind='form'), request(id='../other'), request(cancel=''),
                      request(actions=[]), request(actions=[{'label': 'x'}] * 33),
                      request(kind='prompt', input_type='number'), request(kind='prompt', maxlength=True),
                      request(kind='prompt', value='😀', maxlength=1), request(title='x' * 4097)):
            with self.subTest(value=type(value)), self.assertRaises(ValueError):
                validated(value)

    def test_payload_drops_unknown_fields_and_keeps_exact_supported_values(self):
        data = validated(request(kind='prompt', input_type='password', value='😀', maxlength=2, unknown='discard'))
        self.assertNotIn('unknown', data)
        self.assertEqual(data['value'], '😀')
        self.assertEqual(data['maxlength'], 2)


class DialogLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.look = {'native_dialogs': True}
        self.core = SimpleNamespace(account='a', backend=object(), stage='ready', locked=False,
                                    appearance=lambda: self.look)
        self.presented, self.cancelled = [], []

        def present(data, done):
            self.presented.append((data, done))
            return lambda: self.cancelled.append(data['id'])
        self.service = DialogService(self.core, present, timeout=1)

    async def launch(self, data=None):
        task = asyncio.create_task(self.service.request(data or request(), 'a'))
        await asyncio.sleep(0)
        return task

    async def test_disabled_unsupported_and_wrong_account_never_present(self):
        self.look['native_dialogs'] = False
        self.assertEqual(await self.service.request(request(), 'a'), UNHANDLED)
        self.look['native_dialogs'] = True
        self.assertEqual(await self.service.request(request(), 'other'), UNHANDLED)
        self.core.locked = True
        self.assertEqual(await self.service.request(request(), 'a'), UNHANDLED)
        self.assertEqual(self.presented, [])

    async def test_accept_once_and_drop_untrusted_extra_response_fields(self):
        task = await self.launch()
        callback = self.presented[0][1]
        callback({'handled': True, 'cancelled': False, 'index': 0, 'extra': 'not returned'})
        callback({'handled': True, 'cancelled': False, 'index': 1})
        self.assertEqual(await task, {'handled': True, 'cancelled': False, 'index': 0})
        self.assertIsNone(self.service.pending)

    async def test_late_selection_cannot_survive_account_backend_lock_or_preference_change(self):
        for mutation in (lambda: setattr(self.core, 'account', 'b'),
                         lambda: setattr(self.core, 'backend', object()),
                         lambda: setattr(self.core, 'locked', True),
                         lambda: self.look.update(native_dialogs=False)):
            self.setUp()
            task = await self.launch()
            mutation()
            self.presented[0][1]({'handled': True, 'cancelled': False, 'index': 0})
            self.assertEqual(await task, CANCELLED)

    async def test_duplicate_request_does_not_open_a_second_native_modal(self):
        task = await self.launch()
        self.assertEqual(await self.service.request(request(), 'a'), CANCELLED)
        self.assertEqual(len(self.presented), 1)
        self.service.cancel()
        self.assertEqual(await task, CANCELLED)

    async def test_cancel_endpoint_only_closes_its_own_account_and_request(self):
        task = await self.launch()
        self.assertFalse(self.service.cancel('b' * 32, 'a'))
        self.assertFalse(self.service.cancel('a' * 32, 'b'))
        self.assertTrue(self.service.cancel('a' * 32, 'a'))
        self.assertEqual(await task, CANCELLED)
        self.assertTrue(self.cancelled)

    async def test_timeout_or_request_cancellation_dismisses_without_fallback(self):
        self.service.timeout = 0.001
        self.assertEqual(await self.service.request(request(), 'a'), CANCELLED)
        self.assertTrue(self.cancelled)
        self.service.timeout = 1
        task = await self.launch()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(self.service.pending)

    async def test_invalid_native_answers_cancel_instead_of_invoking_action(self):
        for answer in ({'index': True}, {'index': -1}, {'index': 7}, {'index': 0, 'text': '😀'}):
            task = await self.launch(request(kind='prompt', maxlength=1))
            self.presented[-1][1]({'handled': True, 'cancelled': False, **answer})
            self.assertEqual(await task, CANCELLED)

    async def test_native_unavailable_returns_web_fallback(self):
        task = await self.launch()
        self.presented[0][1](UNHANDLED)
        self.assertEqual(await task, UNHANDLED)


if __name__ == '__main__':
    unittest.main()

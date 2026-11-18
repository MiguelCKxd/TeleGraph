"""Authentication decisions are simulated; these tests never show an OS prompt."""
from contextlib import contextmanager,nullcontext
import ctypes
import threading
import unittest
from unittest.mock import Mock,patch
import uuid

from tg_ascii import native_auth as auth


@contextmanager
def mac_context(context):
    try:yield context,1
    finally:context.invalidate()


def context_with_reply(success=True,error=None):
    context=Mock();context.canEvaluatePolicy_error_.return_value=(True,None)
    context.evaluatePolicy_localizedReason_reply_.side_effect=lambda policy,reason,reply:reply(success,error)
    return context


class NativeAuthTests(unittest.TestCase):
    def test_unsupported_and_missing_native_backend_fail_closed(self):
        with patch.object(auth.sys,'platform','linux'):
            self.assertFalse(auth.availability()[0]);self.assertFalse(auth.authenticate('Unlock'))
        with patch.object(auth.sys,'platform','darwin'),patch.object(auth,'_mac_context',side_effect=ImportError()):
            self.assertFalse(auth.availability()[0]);self.assertFalse(auth.authenticate('Unlock'))

    def test_cancelled_request_never_calls_os_and_concurrent_prompt_is_rejected(self):
        cancel=threading.Event();cancel.set()
        with patch.object(auth.sys,'platform','darwin'),patch.object(auth,'_mac_authenticate') as native:
            self.assertFalse(auth.authenticate('Unlock',cancel_event=cancel));native.assert_not_called()
            auth._auth_lock.acquire()
            try:self.assertFalse(auth.authenticate('Unlock'))
            finally:auth._auth_lock.release()
            native.assert_not_called()

    def test_mac_requires_fresh_positive_reply_and_invalidates_every_context(self):
        for success,error,expected in ((True,None,True),(False,None,False),(True,object(),False)):
            context=context_with_reply(success,error)
            with self.subTest(success=success,error=bool(error)),patch.object(auth.sys,'platform','darwin'),patch.object(auth,'_mac_context',lambda:mac_context(context)):
                self.assertEqual(auth.authenticate('Unlock'),expected)
            context.invalidate.assert_called_once()
            context.setLocalizedFallbackTitle_.assert_called_once_with('')

    def test_mac_unavailable_does_not_prompt(self):
        context=context_with_reply();context.canEvaluatePolicy_error_.return_value=(False,object())
        with patch.object(auth,'_mac_context',lambda:mac_context(context)):
            self.assertFalse(auth._mac_authenticate('Unlock',threading.Event()))
        context.evaluatePolicy_localizedReason_reply_.assert_not_called();context.invalidate.assert_called_once()

    def test_mac_cancel_during_os_prompt_rejects_even_success_and_invalidates(self):
        context=context_with_reply();cancel=threading.Event()
        def reply(policy,reason,callback):cancel.set();callback(True,None)
        context.evaluatePolicy_localizedReason_reply_.side_effect=reply
        with patch.object(auth,'_mac_context',lambda:mac_context(context)):
            self.assertFalse(auth._mac_authenticate('Unlock',cancel))
        context.invalidate.assert_called_once()

    def test_mac_stalled_os_request_has_deadline_and_context_is_invalidated(self):
        context=context_with_reply();context.evaluatePolicy_localizedReason_reply_.side_effect=None
        with patch.object(auth,'_mac_context',lambda:mac_context(context)),patch.object(auth,'AUTH_TIMEOUT',0):
            self.assertFalse(auth._mac_authenticate('Unlock',threading.Event()))
        context.invalidate.assert_called_once()

    def test_native_exception_releases_request_lock_and_never_unlocks(self):
        with patch.object(auth.sys,'platform','darwin'),patch.object(auth,'_mac_authenticate',side_effect=OSError()):
            self.assertFalse(auth.authenticate('Unlock'))
        self.assertTrue(auth._auth_lock.acquire(False));auth._auth_lock.release()

    def test_windows_only_verified_enum_unlocks_and_preserves_cancellation(self):
        cancel=threading.Event()
        for result in (None,0,1,2,3,4,5,6):
            with self.subTest(result=result),patch.object(auth.sys,'platform','win32'),patch.object(auth,'_windows_request',return_value=result):
                self.assertEqual(auth.authenticate('Unlock',123,cancel),result==0)
        def reply(*args):cancel.set();return 0
        with patch.object(auth.sys,'platform','win32'),patch.object(auth,'_windows_request',side_effect=reply):
            self.assertFalse(auth.authenticate('Unlock',123,cancel))

    def test_windows_availability_does_not_request_verification(self):
        with patch.object(auth.sys,'platform','win32'),patch.object(auth,'_windows_request',return_value=2) as native:
            self.assertFalse(auth.availability()[0]);self.assertFalse(native.call_args.args[0])

    def test_guid_uses_exact_16_byte_little_endian_sdk_layout(self):
        guid=auth._GUID.parse(auth._INTEROP)
        self.assertEqual(ctypes.sizeof(guid),16)
        self.assertEqual(bytes(guid),uuid.UUID(auth._INTEROP).bytes_le)


class WindowsOperationTests(unittest.TestCase):
    def operation(self,status=1,result=0,error=False):
        calls=[]
        def method(pointer,slot,*types):
            def invoke(*args):
                calls.append((pointer,slot))
                if slot==7:args[-1]._obj.value=status
                if pointer=='operation' and slot==8:args[-1]._obj.value=result
                return -1 if error and slot==7 else 0
            return invoke
        return method,calls

    def test_result_delivered_only_after_completed_and_interfaces_closed(self):
        for status,expected in ((1,0),(2,None),(3,None)):
            method,calls=self.operation(status)
            with patch.object(auth,'_interface',return_value='info'),patch.object(auth,'_method',side_effect=method),patch.object(auth,'_release') as release:
                self.assertEqual(auth._await_windows('operation',threading.Event(),1),expected)
                release.assert_called_once_with('info')
            self.assertIn(('info',10),calls)
            self.assertEqual(('operation',8) in calls,status==1)

    def test_cancel_timeout_and_status_error_cancel_operation_without_reading_result(self):
        for cancelled,timeout,error in ((True,1,False),(False,0,False),(False,1,True)):
            method,calls=self.operation(0,error=error);cancel=threading.Event()
            if cancelled:cancel.set()
            with patch.object(auth,'_interface',return_value='info'),patch.object(auth,'_method',side_effect=method),patch.object(auth,'_release') as release:
                if error:
                    with self.assertRaises(OSError):auth._await_windows('operation',cancel,timeout)
                else:self.assertIsNone(auth._await_windows('operation',cancel,timeout))
                release.assert_called_once_with('info')
            self.assertIn(('info',9),calls);self.assertIn(('info',10),calls)
            self.assertNotIn(('operation',8),calls)

    def test_reject_invalid_window_before_any_winrt_initialization(self):
        with patch.object(auth,'_window_handle',side_effect=ValueError()),patch.object(auth,'_windows_api') as api:
            with self.assertRaises(ValueError):auth._windows_request(True,'Unlock',0,threading.Event(),1)
            api.assert_not_called()

    def test_windows_owner_must_be_live_and_belong_to_current_process(self):
        user=Mock();user.IsWindow.return_value=True;user.GetAncestor.return_value=456
        owner=[99]
        def process(hwnd,pointer):pointer._obj.value=owner[0];return 1
        user.GetWindowThreadProcessId.side_effect=process
        with patch.object(auth.ctypes,'WinDLL',return_value=user,create=True),patch.object(auth.os,'getpid',return_value=99):
            self.assertEqual(auth._window_handle(123),456)
            owner[0]=42
            with self.assertRaises(ValueError):auth._window_handle(123)
            user.IsWindow.return_value=False
            with self.assertRaises(ValueError):auth._window_handle(123)

    def test_windows_request_routes_to_desktop_interop_with_owner_and_cleans_com(self):
        api=Mock();api.RoInitialize.return_value=0
        def activate(name,guid,result):result._obj.value=11;return 0
        api.RoGetActivationFactory.side_effect=activate
        def native(pointer,hwnd,message,guid,result):
            self.assertEqual(hwnd,1234)
            self.assertEqual(bytes(guid._obj),uuid.UUID(auth._VERIFY_RESULT).bytes_le)
            result._obj.value=22;return 0
        with patch.object(auth,'_window_handle',return_value=1234),patch.object(auth,'_windows_api',return_value=api),patch.object(auth,'_hstring',lambda api,text:nullcontext(1)),patch.object(auth,'_method',return_value=native) as method,patch.object(auth,'_await_windows',return_value=0),patch.object(auth,'_release') as release:
            self.assertEqual(auth._windows_request(True,'Unlock',7,threading.Event(),1),0)
        self.assertEqual(method.call_args.args[1],6)
        self.assertEqual(release.call_count,2);api.RoUninitialize.assert_called_once()


if __name__=='__main__':unittest.main()

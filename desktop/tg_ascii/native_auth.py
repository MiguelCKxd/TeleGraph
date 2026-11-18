"""Optional OS authentication. Call both public functions from a worker, never Tk.

No passwords, biometric templates or successful decisions are cached. Every
request owns its context/COM operation and fails closed on cancellation/error.
"""
import ctypes
from contextlib import contextmanager
import os
import sys
import threading
import time
import uuid

from .i18n import tr

AUTH_TIMEOUT=120
_auth_lock=threading.Lock()


def availability():
    """Return (available, label or reason), without opening an auth prompt."""
    try:
        if sys.platform=='darwin':return _mac_available()
        if sys.platform=='win32':
            value=_windows_request(False,'',0,threading.Event(),10)
            setup=' '+tr('Set up a PIN, fingerprint or face in Windows Settings > Accounts > Sign-in options.')
            reasons={0:'Windows Hello',1:tr('Windows Hello: no device is available')+setup,
                     2:tr('Windows Hello is not configured')+setup,3:tr('Windows Hello is disabled by system policy'),
                     4:tr('Windows Hello is busy')}
            return value==0,reasons.get(value,tr('Windows Hello is unavailable'))
    except Exception:pass
    return False,tr('Device authentication is unavailable. Use your app password.')


def authenticate(reason,hwnd=0,cancel_event=None):
    """Blocking worker API; True only after a fresh, explicit OS success.

    Windows needs an HWND belonging to this process (capture it on the Tk
    thread). Closing the lock dialog must set cancel_event. Windows Hello may
    use its OS PIN as well as biometrics; macOS requests biometrics only.
    """
    cancel_event=cancel_event or threading.Event()
    if cancel_event.is_set() or not _auth_lock.acquire(blocking=False):return False
    try:
        reason=str(reason).strip()[:512]
        if not reason:return False
        if sys.platform=='darwin':verified=_mac_authenticate(reason,cancel_event)
        elif sys.platform=='win32':verified=_windows_request(True,reason,hwnd,cancel_event,AUTH_TIMEOUT)==0
        else:return False
        return bool(verified) and not cancel_event.is_set()
    except Exception:return False
    finally:_auth_lock.release()


@contextmanager
def _mac_context():
    import objc
    import LocalAuthentication as la
    with objc.autorelease_pool():
        context=la.LAContext.alloc().init()
        try:yield context,la.LAPolicyDeviceOwnerAuthenticationWithBiometrics
        finally:context.invalidate()


def _mac_available():
    with _mac_context() as (context,policy):
        available,_=context.canEvaluatePolicy_error_(policy,None)
        return bool(available),'Touch ID' if available else tr('Touch ID is unavailable or not configured')


def _mac_authenticate(reason,cancel_event):
    with _mac_context() as (context,policy):
        available,_=context.canEvaluatePolicy_error_(policy,None)
        if not available or cancel_event.is_set():return False
        context.setLocalizedFallbackTitle_('')
        completed=threading.Event();result=[False]
        def reply(success,error):
            result[0]=bool(success) and error is None
            completed.set()
        context.evaluatePolicy_localizedReason_reply_(policy,reason,reply)
        expires=time.monotonic()+AUTH_TIMEOUT
        while not completed.wait(.05):
            if cancel_event.is_set() or time.monotonic()>=expires:return False
        return result[0] and not cancel_event.is_set()


# ABI and IIDs from Microsoft's WinSDK UserConsentVerifierInterop.h,
# windows.security.credentials.ui.h and Windows.Foundation.IAsyncInfo.
# IInspectable occupies slots 0..5; all HRESULTs/enums are signed 32-bit.
_INTEROP='39e050c3-4e74-441a-8dc0-b81104df949c'
_STATICS='af4f3f91-564c-4ddc-b8b5-973447627c65'
_VERIFY_RESULT='fd596ffd-2318-558f-9dbe-d21df43764a5'
_ASYNC_INFO='00000036-0000-0000-c000-000000000046'
_CLASS='Windows.Security.Credentials.UI.UserConsentVerifier'


class _GUID(ctypes.Structure):
    _fields_=[('data1',ctypes.c_uint32),('data2',ctypes.c_uint16),('data3',ctypes.c_uint16),('data4',ctypes.c_ubyte*8)]

    @classmethod
    def parse(cls,value):return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def _checked(result):
    if result<0:raise OSError(f'Windows authentication HRESULT 0x{result & 0xffffffff:08x}')


def _method(pointer,slot,*types):
    table=ctypes.cast(pointer,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_int32,ctypes.c_void_p,*types)(table[slot])


def _release(pointer):
    if pointer:_method(pointer,2)(pointer)


def _interface(pointer,iid):
    result=ctypes.c_void_p();guid=_GUID.parse(iid)
    _checked(_method(pointer,0,ctypes.POINTER(_GUID),ctypes.POINTER(ctypes.c_void_p))(pointer,ctypes.byref(guid),ctypes.byref(result)))
    return result


def _windows_api():
    api=ctypes.WinDLL('combase.dll',winmode=0x800)  # System32 only.
    api.RoInitialize.argtypes=[ctypes.c_uint32];api.RoInitialize.restype=ctypes.c_int32
    api.RoUninitialize.argtypes=[];api.RoUninitialize.restype=None
    api.WindowsCreateString.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.POINTER(ctypes.c_void_p)]
    api.WindowsCreateString.restype=ctypes.c_int32
    api.WindowsDeleteString.argtypes=[ctypes.c_void_p];api.WindowsDeleteString.restype=ctypes.c_int32
    api.RoGetActivationFactory.argtypes=[ctypes.c_void_p,ctypes.POINTER(_GUID),ctypes.POINTER(ctypes.c_void_p)]
    api.RoGetActivationFactory.restype=ctypes.c_int32
    return api


@contextmanager
def _hstring(api,text):
    value=ctypes.c_void_p()
    _checked(api.WindowsCreateString(text,len(text.encode('utf-16-le'))//2,ctypes.byref(value)))
    try:yield value
    finally:api.WindowsDeleteString(value)


def _window_handle(hwnd):
    user=ctypes.WinDLL('user32.dll',winmode=0x800)
    user.IsWindow.argtypes=[ctypes.c_void_p];user.IsWindow.restype=ctypes.c_int32
    user.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
    user.GetWindowThreadProcessId.restype=ctypes.c_uint32
    user.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint32];user.GetAncestor.restype=ctypes.c_void_p
    if not hwnd or not user.IsWindow(hwnd):raise ValueError('A live application window is required')
    process=ctypes.c_uint32();user.GetWindowThreadProcessId(hwnd,ctypes.byref(process))
    if process.value!=os.getpid():raise ValueError('Authentication window belongs to another process')
    return user.GetAncestor(hwnd,2) or hwnd


_CREDENTIAL_DIALOG='Credential Dialog Xaml Host'
RPC_E_CHANGED_MODE=-2147417850  # 0x80010106: COM already initialised as STA here.


def _user32():
    user=ctypes.WinDLL('user32.dll',winmode=0x800)
    user.FindWindowW.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p];user.FindWindowW.restype=ctypes.c_void_p
    user.SetForegroundWindow.argtypes=[ctypes.c_void_p];user.SetForegroundWindow.restype=ctypes.c_int32
    user.AllowSetForegroundWindow.argtypes=[ctypes.c_uint32];user.AllowSetForegroundWindow.restype=ctypes.c_int32
    user.BringWindowToTop.argtypes=[ctypes.c_void_p];user.BringWindowToTop.restype=ctypes.c_int32
    return user


def _bring_forward(hwnd):
    """1.4.1 (Windows only): the Hello prompt opens behind a window that is not
    in the foreground and looks like nothing happened. Raise ours first."""
    try:
        user=_user32()
        user.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY: let the OS prompt take focus.
        if hwnd:
            user.BringWindowToTop(hwnd);user.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _focus_prompt(state):
    """Give the Windows Hello dialog the focus once it exists (as Bitwarden and
    KeePassXC do); harmless when it is already in front."""
    if state.get('focused') or time.monotonic()>state.get('until',0):return
    try:
        user=state.get('user') or _user32();state['user']=user
        dialog=user.FindWindowW(_CREDENTIAL_DIALOG,None)
        if dialog:
            user.SetForegroundWindow(dialog);state['focused']=True
    except Exception:
        state['focused']=True


def _await_windows(operation,cancel_event,timeout,focus=False):
    info=_interface(operation,_ASYNC_INFO)
    pending=True
    prompt={'until':time.monotonic()+8} if focus else None
    try:
        expires=time.monotonic()+timeout
        while True:
            if prompt is not None:_focus_prompt(prompt)
            if cancel_event.is_set() or time.monotonic()>=expires:
                return None
            status=ctypes.c_int32()
            _checked(_method(info,7,ctypes.POINTER(ctypes.c_int32))(info,ctypes.byref(status)))
            if status.value==1:
                pending=False
                result=ctypes.c_int32(-1)
                _checked(_method(operation,8,ctypes.POINTER(ctypes.c_int32))(operation,ctypes.byref(result)))
                return None if cancel_event.is_set() else result.value
            if status.value!=0:
                pending=False
                return None  # Canceled or Error never grants access.
            cancel_event.wait(.05)
    finally:
        # Close can report E_ILLEGAL_METHOD_CALL if the OS is still canceling;
        # release both owned interfaces regardless, without returning success.
        try:
            if pending:_method(info,9)(info)
            _method(info,10)(info)
        finally:_release(info)


def _windows_request(verify,reason,hwnd,cancel_event,timeout):
    if cancel_event.is_set():return None
    if verify:
        hwnd=_window_handle(hwnd)
        _bring_forward(hwnd)
    api=_windows_api()
    initialised=api.RoInitialize(1)  # worker MTA; balanced even for S_FALSE.
    if initialised==RPC_E_CHANGED_MODE:initialised=None  # Usable as is; never uninitialise it.
    else:_checked(initialised)
    factory=ctypes.c_void_p();operation=ctypes.c_void_p()
    try:
        with _hstring(api,_CLASS) as name:
            guid=_GUID.parse(_INTEROP if verify else _STATICS)
            _checked(api.RoGetActivationFactory(name,ctypes.byref(guid),ctypes.byref(factory)))
        if cancel_event.is_set():return None
        if verify:
            with _hstring(api,reason) as message:
                guid=_GUID.parse(_VERIFY_RESULT)
                _checked(_method(factory,6,ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(_GUID),ctypes.POINTER(ctypes.c_void_p))(
                    factory,hwnd,message,ctypes.byref(guid),ctypes.byref(operation)))
        else:
            # Check desktop interop too: an older OS may expose UWP statics only.
            interop=_interface(factory,_INTEROP);_release(interop)
            _checked(_method(factory,6,ctypes.POINTER(ctypes.c_void_p))(factory,ctypes.byref(operation)))
        return _await_windows(operation,cancel_event,timeout,focus=verify)
    finally:
        _release(operation);_release(factory)
        if initialised is not None:api.RoUninitialize()

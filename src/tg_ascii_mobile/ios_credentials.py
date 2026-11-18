"""Telegram application credentials in the unlocked iOS device's private keychain."""
from contextlib import ExitStack, contextmanager
import ctypes as C
from functools import lru_cache
import json


@lru_cache(maxsize=1)
def _libraries():
    cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    security = C.CDLL('/System/Library/Frameworks/Security.framework/Security')
    pointer = C.c_void_p
    signatures = (
        (cf.CFDictionaryCreateMutable, pointer, [pointer, C.c_long, pointer, pointer]),
        (cf.CFDictionarySetValue, None, [pointer, pointer, pointer]),
        (cf.CFDataCreate, pointer, [pointer, C.c_char_p, C.c_long]),
        (cf.CFDataGetBytePtr, pointer, [pointer]),
        (cf.CFDataGetLength, C.c_long, [pointer]),
        (cf.CFStringCreateWithCString, pointer, [pointer, C.c_char_p, C.c_uint32]),
        (cf.CFRelease, None, [pointer]),
        (security.SecItemCopyMatching, C.c_int32, [pointer, C.POINTER(pointer)]),
        (security.SecItemUpdate, C.c_int32, [pointer, pointer]),
        (security.SecItemAdd, C.c_int32, [pointer, C.POINTER(pointer)]),
        (security.SecItemDelete, C.c_int32, [pointer]),
    )
    for function, result, args in signatures:
        function.restype, function.argtypes = result, args
    return cf, security


@contextmanager
def _query():
    cf, security = _libraries()
    with ExitStack() as stack:
        def owned(value):
            if not value:
                raise MemoryError()
            stack.callback(cf.CFRelease, value)
            return value

        def constant(name):
            return C.c_void_p.in_dll(security, name).value

        def dictionary():
            return owned(cf.CFDictionaryCreateMutable(None, 0,
                C.byref(C.c_byte.in_dll(cf, 'kCFTypeDictionaryKeyCallBacks')),
                C.byref(C.c_byte.in_dll(cf, 'kCFTypeDictionaryValueCallBacks'))))

        query = dictionary()
        cf.CFDictionarySetValue(query, constant('kSecClass'), constant('kSecClassGenericPassword'))
        for key, value in (('kSecAttrService', b'TeleGraph.mobile.telegram-api'),
                           ('kSecAttrAccount', b'application')):
            string = owned(cf.CFStringCreateWithCString(None, value, 0x08000100))
            cf.CFDictionarySetValue(query, constant(key), string)
        yield query, dictionary, owned, constant


def _check(status):
    if status != 0:
        from tg_ascii.i18n import tr
        raise ValueError(tr('No se pudo acceder al llavero del dispositivo.'))


def load():
    cf, security = _libraries()
    with _query() as (query, _, owned, constant):
        cf.CFDictionarySetValue(query, constant('kSecReturnData'), C.c_void_p.in_dll(cf, 'kCFBooleanTrue'))
        result = C.c_void_p()
        status = security.SecItemCopyMatching(query, C.byref(result))
        if status == -25300:  # errSecItemNotFound
            return None
        _check(status)
        data = owned(result.value)
        payload = C.string_at(cf.CFDataGetBytePtr(data), cf.CFDataGetLength(data))
        from tg_ascii.auth import validate_credentials
        try:
            number, secret = json.loads(payload)
            return validate_credentials(number, secret)
        except (ValueError, TypeError):
            return None


def save(credentials):
    cf, security = _libraries()
    with _query() as (query, dictionary, owned, constant):
        encoded = json.dumps(list(credentials)).encode('utf-8')
        data = owned(cf.CFDataCreate(None, encoded, len(encoded)))
        changes = dictionary()

        def set_data(target):
            cf.CFDictionarySetValue(target, constant('kSecValueData'), data)
            cf.CFDictionarySetValue(target, constant('kSecAttrAccessible'),
                                    constant('kSecAttrAccessibleWhenUnlockedThisDeviceOnly'))

        set_data(changes)
        status = security.SecItemUpdate(query, changes)
        if status == -25300:
            set_data(query)
            status = security.SecItemAdd(query, None)
        _check(status)


def delete():
    _, security = _libraries()
    with _query() as (query, _, _, _):
        status = security.SecItemDelete(query)
        if status != -25300:
            _check(status)

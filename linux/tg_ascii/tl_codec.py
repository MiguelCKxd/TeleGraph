"""JSON-safe encoding of the values the app keeps offline (1.5.3).

Telegram objects (photos, documents, entities, keyboards, users, channels,
folders) are stored as their own TL bytes and read back with Telethon's
reader, the same format Telegram uses on the wire. Nothing here uses pickle:
a damaged or edited file can only produce data, never run code.
"""
import base64
from dataclasses import fields, is_dataclass
from datetime import datetime
from pathlib import Path


class Unsupported(Exception):
    """A value that cannot be stored (kept in memory only)."""


def encode(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, tuple):
        return {'__t__': [encode(item) for item in value]}
    if isinstance(value, list):
        return [encode(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            return {'__d__': [[encode(key), encode(item)] for key, item in value.items()]}
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, datetime):
        return {'__dt__': value.isoformat()}
    if isinstance(value, Path):
        return {'__p__': str(value)}
    if isinstance(value, (bytes, bytearray)):
        return {'__b__': base64.b64encode(bytes(value)).decode('ascii')}
    from telethon.tl.tlobject import TLObject
    if isinstance(value, TLObject):
        try:
            return {'__tl__': base64.b64encode(bytes(value)).decode('ascii')}
        except Exception as exc:
            raise Unsupported(type(value).__name__) from exc
    raise Unsupported(type(value).__name__)


def decode(value):
    if isinstance(value, list):
        return [decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    if len(value) == 1:
        (key, inner), = value.items()
        if key == '__t__':
            return tuple(decode(item) for item in inner)
        if key == '__d__':
            return {decode(k): decode(v) for k, v in inner}
        if key == '__dt__':
            return datetime.fromisoformat(inner)
        if key == '__p__':
            return Path(inner)
        if key == '__b__':
            return base64.b64decode(inner)
        if key == '__tl__':
            from telethon.extensions import BinaryReader
            with BinaryReader(base64.b64decode(inner)) as reader:
                return reader.tgread_object()
    return {key: decode(item) for key, item in value.items()}


def encode_record(item, drop=()):
    """A dataclass as a dict; fields that cannot be stored become None."""
    record = {}
    for field in fields(item):
        if field.name in drop:
            continue
        try:
            record[field.name] = encode(getattr(item, field.name))
        except Unsupported:
            record[field.name] = None
    return record


def decode_record(cls, record):
    known = {field.name for field in fields(cls)}
    return cls(**{key: decode(value) for key, value in record.items() if key in known})


def storable(value):
    try:
        encode(value)
        return True
    except Unsupported:
        return False


__all__ = ['Unsupported', 'encode', 'decode', 'encode_record', 'decode_record', 'storable', 'is_dataclass']

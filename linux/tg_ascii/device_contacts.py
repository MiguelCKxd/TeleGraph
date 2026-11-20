"""Native address book of this device (macOS Contacts, Windows People).

TG-ASCII keeps two separate sets internally, like the official apps:

* Telegram contacts: the account's contact list on Telegram's servers
  (``contacts.getContacts``). This is the only list shown in the app.
* Device contacts: entries of the operating system's address book. They are
  read only when the user enables "Sync contacts" (or imports a vCard file)
  and are uploaded with ``contacts.importContacts``, exactly what Telegram's
  own "Sync Contacts" does. Nothing is read in the background otherwise.

All functions here block (system frameworks) and must run off the Tk thread.
"""
from . import APP_NAME
from dataclasses import dataclass, field
from pathlib import Path
import re
import sys
import threading


class DeviceContactsUnavailable(Exception):
    """The address book cannot be used here (no permission, no framework)."""


@dataclass
class DeviceContact:
    first: str
    last: str = ''
    phones: list = field(default_factory=list)
    source_id: str = ''

    def display(self):
        return (self.first + ' ' + self.last).strip()


def normalize_phone(value):
    """Digits with an optional leading '+'; '' when not a usable number."""
    value = str(value or '').strip()
    plus = value.startswith('+') or value.startswith('00')
    digits = re.sub(r'\D', '', value)
    if value.startswith('00'):
        digits = digits[2:]
    if not 5 <= len(digits) <= 17:
        return ''
    return ('+' if plus else '') + digits


def _clean(contacts):
    result = []
    for contact in contacts:
        phones = list(dict.fromkeys(phone for phone in map(normalize_phone, contact.phones) if phone))
        first, last = (contact.first or '').strip()[:64], (contact.last or '').strip()[:64]
        if phones and (first or last):
            result.append(DeviceContact(first or last, last if first else '', phones, contact.source_id))
    return result


# --------------------------------------------------------------------------- macOS
def _mac_store(write=False):
    try:
        import Contacts
    except ImportError as error:
        raise DeviceContactsUnavailable('Contacts framework unavailable') from error
    store = Contacts.CNContactStore.alloc().init()
    status = Contacts.CNContactStore.authorizationStatusForEntityType_(Contacts.CNEntityTypeContacts)
    if status == Contacts.CNAuthorizationStatusNotDetermined:
        done, granted = threading.Event(), [False]

        def answered(value, _error):
            granted[0] = bool(value)
            done.set()

        store.requestAccessForEntityType_completionHandler_(Contacts.CNEntityTypeContacts, answered)
        if not done.wait(120) or not granted[0]:
            raise DeviceContactsUnavailable('Access to Contacts was not granted')
    elif status not in (Contacts.CNAuthorizationStatusAuthorized,
                        getattr(Contacts, 'CNAuthorizationStatusLimited', -1)):
        raise DeviceContactsUnavailable('Access to Contacts is denied in System Settings › Privacy › Contacts')
    return Contacts, store


def _mac_read():
    Contacts, store = _mac_store()
    keys = [Contacts.CNContactGivenNameKey, Contacts.CNContactFamilyNameKey,
            Contacts.CNContactPhoneNumbersKey, Contacts.CNContactIdentifierKey]
    request = Contacts.CNContactFetchRequest.alloc().initWithKeysToFetch_(keys)
    found = []

    def visit(contact, _stop):
        phones = [str(item.value().stringValue()) for item in contact.phoneNumbers() or ()]
        found.append(DeviceContact(str(contact.givenName() or ''), str(contact.familyName() or ''),
                                   phones, str(contact.identifier() or '')))

    ok, error = store.enumerateContactsWithFetchRequest_error_usingBlock_(request, None, visit)
    if not ok:
        raise DeviceContactsUnavailable(str(error) if error else 'Contacts could not be read')
    return found


def _mac_save(contact):
    Contacts, store = _mac_store(write=True)
    entry = Contacts.CNMutableContact.alloc().init()
    entry.setGivenName_(contact.first)
    entry.setFamilyName_(contact.last)
    numbers = [Contacts.CNLabeledValue.labeledValueWithLabel_value_(
        Contacts.CNLabelPhoneNumberMobile, Contacts.CNPhoneNumber.phoneNumberWithStringValue_(phone))
        for phone in contact.phones]
    entry.setPhoneNumbers_(numbers)
    request = Contacts.CNSaveRequest.alloc().init()
    request.addContact_toContainerWithIdentifier_(entry, None)
    ok, error = store.executeSaveRequest_error_(request, None)
    if not ok:
        raise DeviceContactsUnavailable(str(error) if error else 'The contact could not be saved')


# --------------------------------------------------------------------------- Windows
def _run(coroutine):
    import asyncio
    return asyncio.run(coroutine)


def _windows_read():
    try:
        from winrt.windows.applicationmodel.contacts import ContactManager, ContactStoreAccessType
    except ImportError as error:
        raise DeviceContactsUnavailable('Windows contacts API unavailable') from error

    async def read():
        store = await ContactManager.request_store_async(ContactStoreAccessType.ALL_CONTACTS_READ_ONLY)
        if store is None:
            raise DeviceContactsUnavailable('Access to contacts is turned off in Windows privacy settings')
        found = []
        for item in await store.find_contacts_async():
            phones = [phone.number for phone in item.phones]
            found.append(DeviceContact(item.first_name or item.display_name or '', item.last_name or '',
                                       phones, item.id or ''))
        return found
    return _run(read())


def _windows_save(contact):
    try:
        from winrt.windows.applicationmodel.contacts import (ContactManager, ContactStoreAccessType, Contact,
                                                             ContactPhone, ContactPhoneKind)
    except ImportError as error:
        raise DeviceContactsUnavailable('Windows contacts API unavailable') from error

    async def save():
        store = await ContactManager.request_store_async(ContactStoreAccessType.APP_CONTACTS_READ_WRITE)
        if store is None:
            raise DeviceContactsUnavailable('Access to contacts is turned off in Windows privacy settings')
        lists = await store.find_contact_lists_async()
        target = next((item for name in (APP_NAME, 'TG-ASCII') for item in lists if item.display_name == name), None)
        if target is None:
            target = await store.create_contact_list_async(APP_NAME)
        entry = Contact()
        entry.first_name, entry.last_name = contact.first, contact.last
        for number in contact.phones:
            phone = ContactPhone()
            phone.number, phone.kind = number, ContactPhoneKind.MOBILE
            entry.phones.append(phone)
        await target.save_contact_async(entry)
    _run(save())


# --------------------------------------------------------------------------- vCard
def _unfold(text):
    return re.sub(r'\r?\n[ \t]', '', text)


def read_vcard(path, limit=20000):
    """Contacts from a .vcf export (any OS, Google, Outlook…). FN/N and TEL only."""
    data = Path(path).read_bytes()[:16 * 1024 * 1024].decode('utf-8', 'replace')
    contacts = []
    for block in re.findall(r'BEGIN:VCARD(.*?)END:VCARD', _unfold(data), flags=re.S | re.I):
        first = last = full = ''
        phones = []
        for line in block.splitlines():
            if ':' not in line:
                continue
            name, value = line.split(':', 1)
            key = name.split(';', 1)[0].upper()
            if key == 'N':
                parts = (value.split(';') + ['', ''])[:2]
                last, first = parts[0].strip(), parts[1].strip()
            elif key == 'FN':
                full = value.strip()
            elif key == 'TEL':
                phones.append(value.strip())
        if not first and not last and full:
            first = full
        contacts.append(DeviceContact(first, last, phones))
        if len(contacts) >= limit:
            break
    return _clean(contacts)


def vcard_text(contact):
    escape = lambda value: value.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
    lines = ['BEGIN:VCARD', 'VERSION:3.0', f'N:{escape(contact.last)};{escape(contact.first)};;;',
             f'FN:{escape(contact.display())}']
    lines += [f'TEL;TYPE=CELL:{phone}' for phone in contact.phones]
    lines.append('END:VCARD')
    return '\r\n'.join(lines) + '\r\n'


# --------------------------------------------------------------------------- public
def native_supported():
    return sys.platform in ('darwin', 'win32')


def read_device_contacts():
    if sys.platform == 'darwin':
        return _clean(_mac_read())
    if sys.platform == 'win32':
        return _clean(_windows_read())
    raise DeviceContactsUnavailable('No native address book on this system; import a .vcf file instead')


def save_device_contact(first, last, phone):
    contact = DeviceContact(first.strip(), last.strip(), [normalize_phone(phone)] if normalize_phone(phone) else [])
    if not contact.first and not contact.last:
        raise ValueError('Name required')
    if sys.platform == 'darwin':
        return _mac_save(contact)
    if sys.platform == 'win32':
        return _windows_save(contact)
    raise DeviceContactsUnavailable('No native address book on this system')

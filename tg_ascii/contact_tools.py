"""Contact tools of 1.4, modelled on the official apps.

* Contact cards from the contact list, one window per selected person.
* Share one or several contacts with a chat.
* Edit contact: private note (contacts.updateContactNote), suggest a photo or
  set a personal photo only you see (photos.uploadContactProfilePhoto), and
  suggest a birthday to people who have none (users.suggestBirthday).
"""
import asyncio
from datetime import date
import tkinter as tk
from tkinter import ttk

from telethon import functions, types, utils

from .i18n import tr


# ------------------------------------------------------------------- RPCs
async def save_contact_note(backend, peer, text):
    user = utils.get_input_user(await backend.client.get_input_entity(peer))
    note = types.TextWithEntities(text=str(text or '')[:4096], entities=[])
    return await backend.client(functions.contacts.UpdateContactNoteRequest(user, note))


async def contact_photo(backend, peer, path=None, *, suggest=False):
    """Suggest (suggest=True) or set a personal photo; path=None removes it."""
    user = utils.get_input_user(await backend.client.get_input_entity(peer))
    uploaded = await backend.client.upload_file(str(path)) if path else None
    # Telegram needs the action stated (NEED_ACTION_MISSING otherwise):
    # save sets (with a file) or removes (without) the personal photo.
    return await backend.client(functions.photos.UploadContactProfilePhotoRequest(
        user, suggest=bool(suggest) or None, save=None if suggest else True, file=uploaded))


async def suggest_birthday(backend, peer, day, month, year=None):
    date(year or 2000, month, day)  # Validates the calendar date (29 Feb with year 2000).
    user = utils.get_input_user(await backend.client.get_input_entity(peer))
    return await backend.client(functions.users.SuggestBirthdayRequest(
        user, types.Birthday(day=day, month=month, year=year)))


async def share_people(backend, target, people):
    """Contact cards for people with a known phone, a link for the rest."""
    sent = 0
    for person in people:
        phone = getattr(person, 'phone', None)
        first = getattr(person, 'first_name', '') or utils.get_display_name(person) or str(person.id)
        last = getattr(person, 'last_name', '') or ''
        if phone:
            await backend.send_contact_card(target, first, last, '+' + str(phone).lstrip('+'))
        else:
            username = getattr(person, 'username', None)
            link = f'https://t.me/{username}' if username else f'tg://user?id={person.id}'
            await backend.send(target, f'{utils.get_display_name(person) or first}\n{link}')
        sent += 1
        await asyncio.sleep(0.3)  # Gentle pacing for multiple cards.
    return sent


# ------------------------------------------------------------------- UI
def open_contact_cards(app, peers):
    """One independent contact card window per person (does not open the chat)."""
    from .contact_profile import ContactProfile
    for peer in list(dict.fromkeys(peers))[:20]:
        ContactProfile(app, peer, standalone=True)


def share_contacts_dialog(app, people):
    if app.busy or app.demo or not people:
        return
    from .chat_capabilities import chat_capabilities
    from .app_dialogs import messagebox
    account, backend = app.ui_account, app.service.backend
    window, body = app.dialog('Share contact', '540x520')
    names = ', '.join(utils.get_display_name(person) or str(person.id) for person in people[:5])
    if len(people) > 5:
        names += f' (+{len(people) - 5})'
    ttk.Label(body, text=names, wraplength=480).pack(fill='x', pady=6)
    chats = [chat for chat in app.chats if chat_capabilities(app, chat.id, chat=chat).writable]
    listing = tk.Listbox(body, exportselection=False)
    listing.pack(fill='both', expand=True)
    for chat in chats:
        listing.insert('end', chat.name)

    def send():
        if app.busy or not listing.curselection() or account != app.ui_account:
            return
        chat = chats[listing.curselection()[0]]
        if not messagebox.askyesno(tr('Share contact'), tr('Share {count} contact(s) with {name}?').format(
                count=len(people), name=chat.name), parent=window):
            return
        app.call(share_people(backend, chat.id, people),
                 lambda _: (window.destroy() if window.winfo_exists() else None, app.status.set(tr('Contact shared.'))),
                 tr('Enviando...'))

    ttk.Button(body, text=tr('Enviar >'), command=send).pack(fill='x', pady=8)
    listing.bind('<Double-Button-1>', lambda _: send())


def extend_edit_contact(app, frame, profile, backend, valid):
    """Note, personal/suggested photo and birthday suggestion in 'Edit contact'."""
    peer = profile['id']
    ttk.Label(frame, text=tr('Note (only you can see it)')).pack(anchor='w', pady=(10, 3))
    note = tk.Text(frame, height=3, wrap='word')
    note.insert('1.0', profile.get('note') or '')
    note.pack(fill='x')

    def choose_photo(suggest):
        from .app_dialogs import filedialog, messagebox
        path = filedialog.askopenfilename(parent=frame.winfo_toplevel(),
                                          filetypes=[(tr('Photos'), '*.jpg *.jpeg *.png *.webp')])
        if not path or not valid():
            return
        question = (tr('Suggest this photo to {name}? They decide whether to use it.') if suggest else
                    tr('Set this photo for {name}? Only you will see it.')).format(name=profile.get('name', ''))
        if messagebox.askyesno(tr('Edit contact'), question, parent=frame.winfo_toplevel()):
            app.call(contact_photo(backend, peer, path, suggest=suggest),
                     lambda _: app.status.set(tr('Photo suggested.') if suggest else tr('Photo saved.')), tr('Guardando...'))

    photos = ttk.Frame(frame)
    photos.pack(fill='x', pady=6)
    ttk.Button(photos, text=tr('Suggest a photo'), command=lambda: choose_photo(True)).pack(side='left')
    ttk.Button(photos, text=tr('Set a photo for this contact'), command=lambda: choose_photo(False)).pack(side='left', padx=4)
    if profile.get('personal_photo'):
        ttk.Button(photos, text=tr('Remove the photo you set'), command=lambda: app.call(
            contact_photo(backend, peer, None), lambda _: app.status.set(tr('Photo removed.')), tr('Guardando...'))).pack(side='left')
    if not profile.get('birthday'):
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=6)
        ttk.Label(row, text=tr('Suggest a birthday')).pack(side='left')
        day, month, year = tk.StringVar(master=frame), tk.StringVar(master=frame), tk.StringVar(master=frame)
        for variable, width, hint in ((day, 3, 'DD'), (month, 3, 'MM'), (year, 5, 'YYYY')):
            ttk.Label(row, text=hint, style='Muted.TLabel').pack(side='left', padx=(6, 2))
            ttk.Entry(row, textvariable=variable, width=width).pack(side='left')

        def suggest():
            try:
                values = int(day.get()), int(month.get()), int(year.get()) if year.get().strip() else None
                if values[2] is not None and not 1900 <= values[2] <= date.today().year:
                    raise ValueError
                date(values[2] or 2000, values[1], values[0])
            except ValueError:
                app.show_error(ValueError(tr('Invalid date.')))
                return
            app.call(suggest_birthday(backend, peer, *values),
                     lambda _: app.status.set(tr('Birthday suggested.')), tr('Guardando...'))
        ttk.Button(row, text=tr('Suggest'), command=suggest).pack(side='left', padx=6)

    def note_value():
        return note.get('1.0', 'end-1c').strip()

    return note_value

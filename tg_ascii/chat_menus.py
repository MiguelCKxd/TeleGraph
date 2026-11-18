"""Shared chat tools for the chat-list context menu and the in-chat ⋯ menu (1.4).

Both menus now offer the same tools. Exclusive entries stay where they make
sense: the list keeps "Select", "Preview chat — unread" and the new "Mark as
read"; the in-chat menu gets the new "Select messages".

Chat tools that act on the open chat (search, shared media, calls, …) can be
started from the list for another chat: that chat is opened first, then the
tool runs once it is the active one.
"""
from .i18n import tr

OPEN_TIMEOUT_MS = 4000


def run_in_chat(app, peer, action):
    if app.active == peer:
        return action()
    widget = getattr(app, 'chat_list', None)
    if widget is None or not widget.exists(str(peer)):
        return None
    account = app.ui_account
    widget.selection_set(str(peer))
    widget.see(str(peer))
    waited = [0]

    def ready():
        if account != app.ui_account or getattr(app, 'closed', False):
            return
        if app.active == peer and not getattr(app, 'busy', False):
            action()
        elif waited[0] < OPEN_TIMEOUT_MS:
            waited[0] += 50
            app.root.after(50, ready)
    app.root.after(50, ready)
    return None


def in_chat_entries(app, peer, *, include_pin=True):
    """Tools of the in-chat ⋯ menu, for ``peer`` (opened first when needed)."""
    from .advanced_features import feature_enabled
    from .chat_capabilities import chat_capabilities
    from .desktop_calls import call_allowed
    caps = chat_capabilities(app, peer)
    active = peer == app.active
    wrap = lambda callback: (lambda: run_in_chat(app, peer, callback))
    entries = [(tr('Informacion'), wrap(app.contact_info)), (tr('Search in chat'), wrap(app.search_chat)),
               (tr('Shared media'), wrap(app.shared_media))]
    if caps.kind != 'secret':
        entries.append((tr('Pinned messages'), wrap(app.pinned_dialog)))
    if include_pin:
        entries.append((tr('Fijar / Desfijar'), wrap(app.toggle_pin)))
    if caps.kind == 'secret':
        entries.extend([
            (tr('Clave de cifrado y autodestrucción'), wrap(lambda: app.secret_chat_dialog(peer))),
            (tr('Rotar clave ahora (PFS)'), wrap(lambda: app.rekey_secret_chat_action(peer))),
            (tr('Cerrar chat secreto'), wrap(lambda: app.close_secret_chat_action(peer))),
        ])
    elif caps.kind == 'user':
        entries.append((tr('Iniciar chat secreto'), lambda: app.start_secret_chat(peer)))
    if caps.allows('schedule'):
        entries.append((tr('Scheduled messages'), wrap(app.scheduled_messages)))
    for label, video in (('Call', False), ('Video call', True)):
        if call_allowed(app, peer, video=video):
            entries.append((tr(label), wrap(lambda v=video: app.start_call(video=v))))
    if call_allowed(app, peer):
        entries.append((tr('Conference call'), wrap(lambda: app.start_group_call(conference=True))))
    elif not app.demo:
        full = getattr(app.service.backend, '_capability_full', {}).get(peer)
        if feature_enabled(app, 'calls') and getattr(full, 'call', None) is not None:
            entries.append((tr('Group call'), wrap(app.channel_call_settings)))
        elif feature_enabled(app, 'calls') and caps.kind in ('group', 'channel'):
            entity = getattr(app.service.backend, '_capability_entities', {}).get(peer)
            if getattr(entity, 'creator', False) or getattr(getattr(entity, 'admin_rights', None), 'manage_call', False):
                entries.append((tr('Group call'), wrap(lambda: app.start_group_call(create=True))))
    if not app.demo and caps.kind in ('group', 'channel') and feature_enabled(app, 'calls'):
        entries.append((tr('Calls and video'), wrap(app.channel_call_settings)))
    if caps.allows('wallpaper'):
        entries.append((tr('Chat background'), wrap(app.choose_wallpaper)))
    if active:
        # Bot shortcuts depend on the open chat's header state.
        for label, callback in [('Bot commands', app.commands_menu), ('Open Mini App', app.open_bot_app)]:
            if not getattr(app.bot_buttons.get(label), 'flow_hidden', True):
                entries.append((tr(label), callback))
    if app.preferences.values['local_pins']:
        entries.append((tr('Pin locally / Unpin locally'), wrap(app.toggle_local_pin)))
    return entries


def list_entries(app, peer, chat, *, include_pin=True):
    """Tools of the chat-list context menu that are not list-exclusive."""
    from .chat_capabilities import chat_capabilities
    from telethon import utils
    backend, account = app.service.backend, app.ui_account
    caps = chat_capabilities(app, peer)

    def done(_):
        if account == app.ui_account:
            app.refresh()

    def perform(operation):
        if not app.busy and account == app.ui_account:
            app.call(operation(), done, tr('Guardando...'))

    def folders():
        def loaded(records):
            if account != app.ui_account:
                return
            if not records:
                app.status.set(tr('No folders yet. Create one in Folders.'))
                return
            from .app_dialogs import popup_menu
            from .desktop_folders import FolderLabel
            from .telegram_features import matches_folder
            popup_menu(app.root, [(FolderLabel(app, f, '✓ ' if matches_folder(chat, f) else ''),
                lambda folder=f, include=not matches_folder(chat, f): perform(lambda: backend.folder_membership(folder, peer, include)))
                for f in records])
        app.call(backend.folders(), loaded, tr('Cargando...'))

    folder = app.selected_folder()
    pinned = any(utils.get_peer_id(p) == peer for p in folder.pinned_peers) if folder else chat.pinned
    entries = [(tr('Unmute' if chat.muted else 'Mute'),
                lambda: perform(lambda: backend.mute_chat(peer, False)) if chat.muted else app.mute_menu(peer))]
    if include_pin:
        entries.append((tr('Fijar / Desfijar'), lambda: perform(lambda: backend.pin_in_folder(folder, peer, not pinned)
                                                                if folder else backend.pin(peer, not chat.pinned))))
    entries += [(tr('Unarchive' if chat.archived else 'Archive'), lambda: perform(lambda: backend.archive_chat(peer, not chat.archived))),
                (tr('Add to folder'), folders)]
    if caps.can_join or caps.can_leave:
        entries.append((tr('Unirse' if caps.can_join else 'Salir del grupo o canal'),
                        lambda: app.membership_action(peer, leave=caps.can_leave)))
    if caps.allows('clear_history'):
        entries.append((tr('Clear history'), lambda: app.chat_history_action(peer, True)))
    entries.append((tr('Delete chat'), lambda: app.chat_history_action(peer, False)))
    return entries


def mark_chat_read(app, peer):
    """List-exclusive: read everything in a chat without opening it."""
    if app.busy or app.demo:
        return
    account, backend = app.ui_account, app.service.backend

    async def read():
        from .secret_chats import is_secret_peer
        if is_secret_peer(peer):
            await backend.mark_read(peer, None)
            return True
        latest = await backend.client.get_messages(peer, limit=1)
        if latest:
            await backend.mark_read(peer, latest[0].id)
        return True

    def done(_):
        if account != app.ui_account:
            return
        for chat in app.chats:
            if chat.id == peer:
                chat.unread = 0
        app.render_chats()
        app.status.set(tr('Chat marked as read.'))
    app.call(read(), done, tr('Saving...'))


def select_messages(app):
    """In-chat exclusive: enter message selection mode with nothing selected."""
    if app.active is None or app.busy:
        return
    app.selection_kind = 'messages'
    app.selection_scope = (app.ui_account, app.active)
    app.selected_messages, app.selected_chats = set(), set()
    app.refresh_selection()
    app.status.set(tr('Click messages to select them.'))

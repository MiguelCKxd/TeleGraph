"""Presentation-only chat translation; source messages always remain intact."""
from dataclasses import replace


def presentation(app, message):
    account, peer = getattr(app, 'ui_account', None), getattr(app, 'active', None)
    from .advanced_features import feature_enabled
    from .chat_capabilities import account_premium
    # Called for each visible message: account facts are O(1), without scanning
    # the chat list or checking the subscription over the network.
    enabled = feature_enabled(app, 'chat_translation') and account_premium(app)
    backend = getattr(getattr(app, 'service', None), 'backend', None)
    profiles = getattr(backend, '_capability_full', {})
    if isinstance(profiles, dict) and getattr(profiles.get(peer), 'translations_disabled', False) is True:
        enabled = False
    language = getattr(app, 'chat_translations', {}).get(f'{account}:{peer}') if enabled else None
    key = (account, peer, message.id, language, message.text)
    value = getattr(app, 'translated', {}).get(key) if language else None
    if not value or not getattr(value, 'text', '').strip():
        return message, None, ''
    if key in getattr(app, '_translation_originals', set()):
        return message, key, 'Show translation'
    translated = replace(message, text=value.text, raw_text=value.text,
                         entities=tuple(getattr(value, 'entities', ()) or ()), custom_emojis=())
    return translated, key, 'Show original'


def toggle_original(app, key):
    if getattr(app, 'selection_kind', None) == 'messages': return
    if key[:2] != (app.ui_account, app.active): return
    message = next((m for m in app.messages if m.id == key[2]), None)
    if message is None or presentation(app, message)[1] != key: return
    originals = getattr(app, '_translation_originals', set())
    # Retain only entries whose translations are still cached.
    originals.intersection_update(getattr(app, 'translated', {}))
    if key in originals: originals.remove(key)
    else: originals.add(key)
    app._translation_originals = originals
    app.render_messages(False)


def clear_buttons(app):
    for button in getattr(app, '_translation_buttons', []): button.destroy()
    app._translation_buttons = []


def insert_button(app, key, label):
    if key is None: return
    from tkinter import ttk
    from .i18n import tr
    button = ttk.Button(app.history, text=tr(label), command=lambda: toggle_original(app, key))
    if getattr(app, 'selection_kind', None) == 'messages': button.state(['disabled'])
    app._translation_buttons.append(button)
    app.history.window_create('end', window=button, pady=3)
    app.history.insert('end', '\n')

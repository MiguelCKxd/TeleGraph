"""Gift preview: the gift's own TGS animation, plus its official web page.

Before 1.4 "Preview gift" sent the gift sticker to the generic file viewer,
which can only decode raster images/video. Gift stickers are Lottie (TGS)
documents, so the preview failed. This window renders the original TGS with
the same native pipeline as stickers/custom emoji (rlottie, see animation.py)
and always offers the official web page as an alternative.
"""
import tkinter as tk
from tkinter import ttk

from .i18n import tr

PREVIEW_SIDE = 256
FRAGMENT_GIFTS = 'https://fragment.com/gifts'


def official_gift_url(gift):
    """Public page for a gift: the collectible itself, its auction, or the catalogue."""
    slug = getattr(gift, 'slug', None)
    if isinstance(slug, str) and slug:
        return 'https://t.me/nft/' + slug
    auction = getattr(gift, 'auction_slug', None)
    if isinstance(auction, str) and auction:
        return 'https://t.me/auction/' + auction
    return FRAGMENT_GIFTS


def gift_document(gift):
    """The animated sticker of a regular gift, or the model of a collectible."""
    from telethon import types
    sticker = getattr(gift, 'sticker', None)
    if sticker is not None:
        return sticker
    for attribute in getattr(gift, 'attributes', None) or ():
        if isinstance(attribute, types.StarGiftAttributeModel):
            return getattr(attribute, 'document', None)
    return None


def open_gift_preview(app, gift, *, account=None, backend=None, title=None):
    account = app.ui_account if account is None else account
    backend = backend or app.service.backend
    window = tk.Toplevel(app.root)
    window.title(title or getattr(gift, 'title', None) or tr('Telegram gift'))
    window.geometry('360x430')
    window.minsize(300, 360)
    from .scrolling import Viewport, fit_to_content
    viewport = Viewport(window, minimum=(280, 300))
    viewport.pack(fill='both', expand=True)
    body = viewport.content
    body.configure(padding=14)
    fit_to_content(window, viewport)
    picture = ttk.Label(body, anchor='center', text=tr('Loading...'))
    picture.pack(fill='both', expand=True)
    status = tk.StringVar(master=window, value='')
    ttk.Label(body, textvariable=status, wraplength=300).pack(fill='x', pady=6)
    url = official_gift_url(gift)
    label = tr('View on the official website') if url != FRAGMENT_GIFTS else tr('Browse gifts on Fragment (official)')
    ttk.Button(body, text=label, command=lambda: app.open_link(url, browser_only=True)).pack(fill='x', pady=4)
    ttk.Button(body, text=tr('Close'), command=window.destroy).pack(fill='x')
    window.bind('<Escape>', lambda _: window.destroy())
    from .themes import apply_widget
    apply_widget(window)
    if hasattr(app, 'popups'):
        app.popups.append(window)

    def current():
        try:
            return bool(window.winfo_exists()) and account == app.ui_account
        except tk.TclError:
            return False

    def unavailable(_error=None):
        if current():
            picture.configure(text='◇', image='')
            status.set(tr('This gift cannot be previewed here. Open it on the official website.'))

    document = gift_document(gift)
    if document is None or getattr(app, 'demo', False):
        unavailable()
        return window

    def loaded(path):
        if not path or not current():
            unavailable()
            return

        def painted(photo):
            if current():
                picture.image = photo
                picture.configure(image=photo or '', text='' if photo else '◇')

        app.request_photo(path, (PREVIEW_SIDE, PREVIEW_SIDE), painted, owner=picture, valid=current)

    async def render():
        from .animation import emoji_file
        return await emoji_file(app, document, account, backend, side=PREVIEW_SIDE)

    app.worker.submit(render(), loaded, unavailable)
    return window

"""Native article text, formatting, links and foldable blocks; no web engine."""
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from telethon import types as t

from .advanced_features import feature_enabled
from .i18n import tr
from .rich_articles import block_text, rich_text
from .ui_work import bind_text_action


class ArticleView(ttk.Frame):
    def __init__(self, parent, app, rich, backend=None):
        super().__init__(parent)
        self.app, self.fonts, self.counter, self.folds = app, [], 0, {}
        # 1.4: photos of the article, for carousels and inline pictures.
        self.backend = backend if backend is not None else getattr(getattr(app, 'service', None), 'backend', None)
        self.photo_index = {photo.id: photo for photo in (getattr(rich, 'photos', None) or ()) if isinstance(photo, t.Photo)}
        self.carousels = []
        self.text = tk.Text(self, wrap='word', height=22, padx=10, pady=8)
        bar = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y'); self.text.pack(fill='both', expand=True)
        base = tkfont.nametofont('TkDefaultFont')
        for name, changes in [('bold', {'weight': 'bold'}), ('italic', {'slant': 'italic'}),
                              ('title', {'weight': 'bold', 'size': max(14, abs(base.cget('size')) + 6)}),
                              ('header', {'weight': 'bold', 'size': max(12, abs(base.cget('size')) + 3)})]:
            font = tkfont.Font(root=self.text, **{**base.actual(), **changes})
            self.fonts.append(font); self.text.tag_configure(name, font=font)
        self.text.tag_configure('code', font='TkFixedFont')
        self.text.tag_configure('underline', underline=True)
        self.text.tag_configure('strike', overstrike=True)
        self.text.tag_configure('quote', lmargin1=18, lmargin2=18, spacing1=4, spacing3=4)
        if rich.rtl: self.text.tag_configure('rtl', justify='right')
        for block in rich.blocks[:500]: self.insert_block(block)
        if rich.rtl: self.text.tag_add('rtl', '1.0', 'end')
        self.text.configure(state='disabled')

    def next_tag(self, prefix):
        self.counter += 1
        return prefix + str(self.counter)

    def insert_rich(self, value, tags=(), depth=0):
        if depth > 16 or value is None: return
        if isinstance(value, str): self.text.insert('end', value, tags); return
        if isinstance(value, t.TextConcat):
            for item in value.texts[:500]: self.insert_rich(item, tags, depth + 1)
            return
        styles = {t.TextBold: 'bold', t.TextItalic: 'italic', t.TextUnderline: 'underline',
                  t.TextStrike: 'strike', t.TextFixed: 'code'}
        if type(value) in styles:
            self.insert_rich(value.text, tags + (styles[type(value)],), depth + 1); return
        if isinstance(value, t.TextUrl) and feature_enabled(self.app, 'links'):
            tag = self.next_tag('url_'); self.text.tag_configure(tag, underline=True)
            bind_text_action(self.text, tag, '<Button-1>', lambda _, url=value.url:
                             self.app.open_link(url) if feature_enabled(self.app, 'links') else None)
            self.insert_rich(value.text, tags + (tag,), depth + 1); return
        if isinstance(value, t.TextPlain): self.text.insert('end', value.text, tags); return
        content = getattr(value, 'text', None)
        if content is not None: self.insert_rich(content, tags, depth + 1)
        else: self.text.insert('end', rich_text(value), tags)

    def insert_fold(self, title, blocks, opened, depth):
        label = self.next_tag('fold_title_')
        hidden = self.next_tag('fold_body_')
        self.text.insert('end', '▾ ' if opened else '▸ ', (label, 'bold'))
        self.insert_rich(title, (label, 'bold'), depth + 1)
        self.text.insert('end', '\n')
        start = self.text.index('end-1c')
        for block in blocks[:500]: self.insert_block(block, depth + 1)
        finish = self.text.index('end-1c')
        self.text.tag_add(hidden, start, finish)
        self.text.tag_configure(hidden, elide=not opened)
        self.folds[hidden] = bool(opened)
        def toggle(_):
            opened = not self.folds[hidden]
            self.folds[hidden] = opened
            self.text.tag_configure(hidden, elide=not opened)
        bind_text_action(self.text, label, '<Button-1>', toggle)

    def insert_carousel(self, block):
        # Same switch as chats: with 'Show media previews inside chats' off the
        # article keeps its textual [Photo]/[Video] placeholders.
        values = getattr(getattr(self.app, 'preferences', None), 'values', {})
        if self.backend is None or getattr(self.app, 'demo', False) or not values.get('inline_media', True) \
                or not values.get('photo_previews', True):
            return False
        from .article_carousel import PhotoCarousel, slide_items
        items = slide_items(block, self.photo_index)
        if not items or not any(photo is not None for photo, _, _ in items):
            return False
        caption = getattr(block, 'caption', None)
        caption = rich_text(getattr(caption, 'text', caption)) if caption is not None and not isinstance(block, t.PageBlockPhoto) else ''
        carousel = PhotoCarousel(self.text, self.app, self.backend, items, caption)
        self.carousels.append(carousel)
        self.text.window_create('end', window=carousel, stretch=True)
        self.text.insert('end', '\n')
        return True

    def insert_block(self, block, depth=0):
        if depth > 16: return
        if isinstance(block, (t.PageBlockSlideshow, t.PageBlockCollage, t.PageBlockPhoto)) and self.insert_carousel(block):
            pass
        elif isinstance(block, t.PageBlockDetails):
            self.insert_fold(block.title, block.blocks, bool(block.open), depth)
        elif isinstance(block, t.PageBlockBlockquote) and block.collapsed:
            self.insert_fold(block.caption or t.TextPlain(tr('Quote')), [t.PageBlockParagraph(block.text)], False, depth)
        elif isinstance(block, t.PageBlockTable):
            self.insert_rich(block.title, ('header',), depth + 1); self.text.insert('end', '\n')
            for row in block.rows[:500]:
                for index, cell in enumerate(row.cells[:20]):
                    if index: self.text.insert('end', '  |  ')
                    self.insert_rich(cell.text, ('bold',) if cell.header else (), depth + 1)
                self.text.insert('end', '\n')
        elif isinstance(block, (t.PageBlockList, t.PageBlockOrderedList)):
            for index, item in enumerate(block.items[:500]):
                marker = (str(getattr(item, 'num', None) or index + 1) + '. ') if isinstance(block, t.PageBlockOrderedList) else '• '
                if getattr(item, 'checkbox', False): marker = '☑ ' if item.checked else '☐ '
                self.text.insert('end', marker)
                if hasattr(item, 'text'): self.insert_rich(item.text, (), depth + 1); self.text.insert('end', '\n')
                for child in getattr(item, 'blocks', ()) or (): self.insert_block(child, depth + 1)
        elif isinstance(block, (t.PageBlockTitle, t.PageBlockHeader, t.PageBlockSubheader,
                                t.PageBlockParagraph, t.PageBlockPreformatted, t.PageBlockBlockquote,
                                t.PageBlockFooter, t.PageBlockSubtitle)):
            tags = ('title',) if isinstance(block, t.PageBlockTitle) else ('header',) if isinstance(block, (t.PageBlockHeader, t.PageBlockSubheader)) else ('code',) if isinstance(block, t.PageBlockPreformatted) else ('quote',) if isinstance(block, t.PageBlockBlockquote) else ()
            self.insert_rich(block.text, tags, depth + 1)
            if isinstance(block, t.PageBlockBlockquote) and block.caption:
                self.text.insert('end', '\n'); self.insert_rich(block.caption, ('italic',), depth + 1)
        else:
            self.text.insert('end', block_text(block, depth))
        self.text.insert('end', '\n\n')

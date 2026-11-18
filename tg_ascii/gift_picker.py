"""Visual gift selection; purchasing remains in the existing confirmation flow."""
from .appearance import app_palette
from .i18n import tr
from .sticker_picker import StickerGrid


def gift_title(gift):
    return getattr(gift, 'title', None) or tr('Gift')


def gift_price(gift):
    stars = getattr(gift, 'stars', None)
    return f'{stars} ★' if type(stars) is int and stars >= 0 else tr('Price unavailable')


def gift_status(gift):
    if getattr(gift, 'auction', False) or getattr(gift, 'auction_slug', None):
        return tr('Auction')
    if (getattr(gift, 'sold_out', False) or getattr(gift, 'availability_remains', None) == 0):
        return tr('Sold out')
    if getattr(gift, 'per_user_remains', None) == 0:
        return tr('Limit reached')
    remains = getattr(gift, 'availability_remains', None)
    return f'{tr("Available")}: {remains}' if remains is not None else tr('Available')


def filter_gifts(gifts, query='', mode='all'):
    needle = query.strip().casefold()
    result = []
    for gift in gifts:
        auction = bool(getattr(gift, 'auction', False) or getattr(gift, 'auction_slug', None))
        sold = bool(getattr(gift, 'sold_out', False) or getattr(gift, 'availability_remains', None) == 0)
        available = not (auction or sold or getattr(gift, 'per_user_remains', None) == 0)
        if mode == 'available' and not available or mode == 'auction' and not auction or mode == 'sold_out' and not sold:
            continue
        if needle and needle not in f'{gift_title(gift)} {gift.id} {gift_price(gift)}'.casefold():
            continue
        result.append(gift)
    return result


class GiftGrid(StickerGrid):
    """Reuse the bounded sticker loader, with virtualized labelled gift cards."""
    card_width, card_height = 152, 168

    def __init__(self, parent, app, account, backend, changed):
        self.gifts, self.filtered, self.selected_id = [], [], None
        self.query, self.mode = '', 'all'
        super().__init__(parent, app, account, backend, changed)
        self.cell = 78  # Existing loader prepares a 64px thumbnail.
        self.changed = changed

    def selection(self):
        return next((gift for gift in self.filtered if gift.id == self.selected_id), None)

    def set_gifts(self, gifts):
        self.gifts = list(gifts)
        if not any(gift.id == self.selected_id for gift in self.gifts):
            self.selected_id = None
        self.set_filter(self.query, self.mode)

    def set_filter(self, query='', mode='all'):
        self.cancel_loads()
        self.version += 1
        self.query, self.mode = query, mode
        self.filtered = filter_gifts(self.gifts, query, mode)
        self.documents = [gift.sticker for gift in self.filtered if getattr(gift, 'sticker', None)]
        self.selected = self.selection()
        self._wanted.clear()
        self._cells.clear()
        self.canvas.delete('tile')
        self.canvas.yview_moveto(0)
        self.layout()
        self.changed(self.selected)

    def layout(self):
        if not self.winfo_exists():
            return
        columns = max(1, self.canvas.winfo_width() // self.card_width)
        if columns != getattr(self, 'columns', None):
            self.canvas.delete('tile')
            self._cells.clear()
        self.columns = columns
        rows = (len(self.filtered) + columns - 1) // columns
        region = (0, 0, self.canvas.winfo_width(), max(1, rows * self.card_height))
        if region != getattr(self, '_region', None):
            self.canvas.configure(scrollregion=region)
            self._region = region
        self.repaint.request()

    def paint(self):
        if not self.winfo_exists() or not self.winfo_viewable() or not hasattr(self, 'columns'):
            return
        colors = app_palette(self.app.preferences.values)
        if self.canvas.cget('bg') != colors['bg']:
            self.canvas.configure(bg=colors['bg'])
        first = max(0, int(self.canvas.canvasy(0) // self.card_height) * self.columns)
        last = min(len(self.filtered), (int(self.canvas.canvasy(self.canvas.winfo_height()) // self.card_height) + 2) * self.columns)
        visible = self.filtered[first:last]
        self._wanted = {gift.sticker.id for gift in visible if getattr(gift, 'sticker', None)}
        for index in list(self._cells):
            if not first <= index < last:
                self.canvas.delete(f'tile:{index}')
                del self._cells[index]
        self.canvas.delete('gift:empty')
        if not self.filtered:
            self.canvas.create_text(max(1, self.canvas.winfo_width()) / 2, 48,
                text=tr('No matching gifts'), fill=colors['muted'], tags=('tile', 'gift:empty'))
        for index in range(first, last):
            gift = self.filtered[index]
            doc = getattr(gift, 'sticker', None)
            photo = self.photos.get(doc.id) if doc else None
            if photo is None and doc:
                self.load(doc)
            selected = gift.id == self.selected_id
            state = (gift.id, photo, selected, gift_title(gift), gift_price(gift), gift_status(gift), tuple(colors.items()))
            if self._cells.get(index) == state:
                continue
            x, y = index % self.columns * self.card_width, index // self.columns * self.card_height
            tag = f'tile:{index}'
            tags = ('tile', tag)
            self.canvas.delete(tag)
            self.canvas.create_rectangle(x + 3, y + 3, x + self.card_width - 3, y + self.card_height - 3,
                fill=colors['selected'] if selected else colors['panel'],
                outline=colors['strong'] if selected else colors['line'], tags=tags)
            center = x + self.card_width / 2
            if photo:
                self.canvas.create_image(center, y + 40, image=photo, tags=tags)
            else:
                self.canvas.create_text(center, y + 40, text='◇', fill=colors['muted'], tags=tags)
            for offset, text, color in ((88, gift_title(gift)[:22], colors['text']),
                                        (116, gift_price(gift), colors['strong']),
                                        (146, gift_status(gift), colors['muted'])):
                self.canvas.create_text(center, y + offset, text=text, width=self.card_width - 12, fill=color, tags=tags)
            self._cells[index] = state
        for ident in list(self.photos):
            if ident not in self._wanted:
                self.photos.pop(ident, None)

    def select_index(self, index):
        if not 0 <= index < len(self.filtered):
            return
        self.selected = self.filtered[index]
        self.selected_id = self.selected.id
        self.repaint.request()
        self.changed(self.selected)  # Selection alone never sends or purchases.

    def click(self, event):
        self.canvas.focus_set()
        column = int(event.x // self.card_width)
        if 0 <= column < self.columns:
            self.select_index(int(self.canvas.canvasy(event.y) // self.card_height) * self.columns + column)
        return 'break'

    def navigate(self, direction):
        if not self.filtered:
            return 'break'
        index = next((i for i, gift in enumerate(self.filtered) if gift.id == self.selected_id), -1)
        if direction in ('home', 'end'):
            index = 0 if direction == 'home' else len(self.filtered) - 1
        else:
            delta = -self.columns if direction == 'up' else self.columns if direction == 'down' else direction
            index = 0 if index < 0 else max(0, min(len(self.filtered) - 1, index + delta))
        self.select_index(index)
        y = index // self.columns * self.card_height
        top, height = self.canvas.canvasy(0), self.canvas.winfo_height()
        total = max(1, ((len(self.filtered) + self.columns - 1) // self.columns) * self.card_height)
        if y < top:
            self.canvas.yview_moveto(y / total)
        elif y + self.card_height > top + height:
            self.canvas.yview_moveto((y + self.card_height - height) / total)
        return 'break'

"""Opt-in layout editing over existing widgets, with no idle polling."""
from copy import deepcopy
import tkinter as tk
from tkinter import ttk
import uuid

from .interface_store import rectangle, snapped_rect, tile_rectangles


def caption(en, es):
    from .i18n import get_language
    language = get_language()
    if language == 'es-419':
        from .spanish_latam import latam
        return latam(es)
    return es if language.startswith('es') else en


class LayoutRuntime:
    def __init__(self, app, store):
        self.app, self.store = app, store
        self.widgets, self.names, self.custom_widgets = {}, {}, {}
        self.editing = False
        self.editor = None
        self.selected = None
        self._drag = None
        self._bindings = []
        self._image_jobs = {}
        self._invoking = set()

    def detach(self):
        self.set_editing(False)
        for widget in list(self._image_jobs):
            self.cancel_image(widget)
        self.widgets.clear()
        self.custom_widgets.clear()

    def attach(self, force=False):
        self.widgets, self.names, self.custom_widgets = {}, {}, {}
        # The default interface needs neither a widget registry nor Tcl reads.
        # Discover editable controls only when a design or the editor needs them.
        if not force and not self.store.document['enabled'] and self.editor is None:
            return
        roots = [('conversation', self.app.chat_conversation)] if getattr(self.app, '_chat_only', False) else [
            ('accounts', self.app.account_bar), ('sidebar', self.app.chat_sidebar),
            ('conversation', self.app.chat_conversation), ('stories', self.app.story_page)]
        def walk(widget, key):
            self.widgets[key] = widget
            try:
                text = str(widget.cget('text'))[:70]
            except tk.TclError:
                text = ''
            self.names[key] = text or widget.winfo_class()
            if isinstance(widget, (tk.Text, tk.Canvas, ttk.Treeview)):
                return
            for i, child in enumerate(widget.winfo_children()):
                walk(child, key+'/'+str(i))
        for key, widget in roots:
            walk(widget, key)
        if self.store.document['enabled']:
            self.apply()
        if self.editor is not None and self.editor.window.winfo_exists():
            self.set_editing(True)
            self.editor.populate()

    def _forget(self, widget):
        manager = widget.winfo_manager()
        if manager == 'pack':
            widget.pack_forget()
        elif manager == 'grid':
            widget.grid_forget()
        elif manager == 'place':
            widget.place_forget()
        elif manager in ('panedwindow', 'ttk::panedwindow'):
            widget.master.forget(widget)

    def apply(self):
        document = self.store.document
        for item in document['items']:
            if item['hidden']:
                continue
            # Old saved designs may still contain the retired global shortcut.
            # Opening linked chats now belongs exclusively to Chat tools.
            if item['kind'] == 'button' and not self.action_available(item['action']):
                continue
            parent = self.app.chat_page
            kind = item['kind']
            if kind == 'button':
                widget = ttk.Button(parent, text=item['text'], command=lambda a=item['action']: self.invoke(a))
            elif kind == 'menu':
                widget = ttk.Button(parent, text=item['text']+' ▾')
                def opened(w=widget, spec=item):
                    from .app_dialogs import popup_menu
                    entries = spec['entries']
                    if spec['resource']:
                        from .preferences import read_json
                        try:
                            data = read_json(self.store.resource(spec['resource']), {})
                            entries = data.get('entries', entries)
                        except (OSError, ValueError):
                            pass
                    if not isinstance(entries, list):
                        return
                    popup_menu(self.app.root, [(str(e.get('text', '')), lambda a=e.get('action', ''): self.invoke(a))
                                              for e in self.available_entries(entries) if self.action_available(e.get('action', ''))], anchor=w)
                widget.configure(command=opened)
            elif kind == 'image':
                widget = ttk.Label(parent, text=item['text'], anchor='center')
                widget.bind('<Configure>', lambda event, w=widget, resource=item['resource']: self.resize_image(w, resource, event.width, event.height))
                widget.bind('<Destroy>', lambda event, w=widget: self.cancel_image(w) if event.widget is w else None)
            elif kind == 'panel':
                widget = ttk.LabelFrame(parent, text=item['text'], padding=4)
                for index, entry in enumerate(item['entries']):
                    if not self.action_available(entry['action']):
                        continue
                    button = ttk.Button(widget, text=entry['text'], command=lambda a=entry['action']: self.invoke(a))
                    button._layout_entry_index = index
                    button.pack(fill='x', pady=2)
            else:
                widget = ttk.Label(parent, text=item['text'], anchor='center', wraplength=260)
                widget.bind('<Configure>', lambda e, w=widget: w.configure(wraplength=max(30, e.width-8)))
            key = 'custom/'+item['id']
            self.widgets[key] = self.custom_widgets[key] = widget
            self.names[key] = item['text'] or kind
            if kind == 'panel':
                for child in widget.winfo_children():
                    child_key = key+'/'+str(child._layout_entry_index)
                    self.widgets[child_key] = child
                    self.names[child_key] = str(child.cget('text'))
            self.place(widget, item['rect'])
            widget.lift()

        for key, spec in document['overrides'].items():
            widget = self.widgets.get(key)
            if widget is None:
                continue
            self.guard_geometry(widget, spec)
            if spec.get('hidden'):
                widget._layout_hidden = True
                self._forget(widget)
            elif 'rect' in spec:
                widget.master._manual_layout = True
                self.freeze_geometry(widget.master)
                self._forget(widget)
                self.place(widget, spec['rect'])
            if 'text' in spec:
                try:
                    widget.configure(text=spec['text'])
                    self.names[key] = spec['text']
                except tk.TclError:
                    pass
        for key, spec in document['overrides'].items():
            if spec.get('front') and key in self.widgets:
                self.widgets[key].lift()

    @staticmethod
    def custom_root(key):
        return key.startswith('custom/') and key.count('/') == 1

    @staticmethod
    def available_entries(entries):
        return [entry for entry in entries if isinstance(entry, dict)
                and entry.get('action') != 'new-window']

    def cancel_image(self, widget):
        widget._layout_photo_request = None
        job = self._image_jobs.pop(widget, None)
        if job is not None:
            try:
                widget.after_cancel(job)
            except tk.TclError:
                pass

    def resize_image(self, widget, resource, width, height):
        # Coalesce resize events; decoding/cache entries are created only for
        # the final geometry, never for every pixel of a drag.
        size = (max(1, min(2048, width-8)), max(1, min(2048, height-8)))
        self.cancel_image(widget)
        if size == getattr(widget, '_layout_photo_size', None):
            return
        if width < 2 or height < 2:
            return
        token = widget._layout_photo_request = object()
        def current():
            return widget.winfo_exists() and widget._layout_photo_request is token
        def loaded(photo):
            if current() and photo is not None:
                widget.configure(image=photo, compound='center')
                widget._layout_photo = photo
                widget._layout_photo_size = size
        def load():
            self._image_jobs.pop(widget, None)
            try:
                if not current():
                    return
                path = self.store.resource(resource)
                from .motion import get_motion
                self.app.request_photo(path, size, loaded, owner=widget,
                    valid=current, enabled=get_motion(self.app)['enabled'])
            except (OSError, ValueError, ImportError, tk.TclError):
                pass
        self._image_jobs[widget] = widget.after(120, load)

    def place(self, widget, rect):
        x, y, w, h = rect
        gap = self.store.document['gap']
        place = getattr(widget, '_layout_geometry', {}).get('place', widget.place)
        place(relx=x, rely=y, relwidth=w, relheight=h, x=gap//2, y=gap//2, width=-gap, height=-gap)

    @staticmethod
    def guard_geometry(widget, spec):
        """Native refreshes keep working without re-packing a user's override."""
        widget._layout_override = bool(spec.get('hidden') or 'rect' in spec)
        widget._layout_hidden = bool(spec.get('hidden'))
        if hasattr(widget, '_layout_geometry'):
            return
        methods = widget._layout_geometry = {}
        for name in ('pack', 'grid', 'place'):
            original = methods[name] = getattr(widget, name)
            def guarded(*args, original=original, **kwargs):
                if not widget._layout_override:
                    return original(*args, **kwargs)
            setattr(widget, name, guarded)

    @staticmethod
    def freeze_geometry(parent):
        if getattr(parent, '_layout_frozen', False):
            return
        parent._layout_frozen = True
        # Preserve its natural minimum rather than a fixed window-sized width.
        # Relative child rectangles still scale when the parent is resized.
        requested = parent.winfo_reqheight()
        try:
            parent.configure(height=requested)
            parent.pack_propagate(False)
            parent.grid_propagate(False)
        except tk.TclError:
            pass

    def native_layout_changed(self):
        return self.store.document['enabled'] and any(k in self.store.document['overrides'] for k in ('sidebar', 'conversation'))

    def action_available(self, action, seen=None):
        if not isinstance(action, str) or action == 'new-window':
            return False
        child = getattr(self.app, '_chat_only', False)
        if child and action in ('settings', 'customize', 'contacts', 'saved', 'folders'):
            return False
        if action.startswith('widget:'):
            key = action[7:]
            if child and not key.startswith(('conversation/', 'custom/')):
                return False
            if key.startswith('custom/'):
                seen = set() if seen is None else seen
                if key in seen: return False
                seen.add(key)
                parts = key.split('/')
                item = next((item for item in self.store.document['items'] if item['id'] == parts[1]), None)
                if item is not None:
                    if len(parts) == 2 and item['kind'] == 'button':
                        return self.action_available(item['action'], seen)
                    if len(parts) == 3 and parts[2].isdigit() and int(parts[2]) < len(item.get('entries', ())):
                        return self.action_available(item['entries'][int(parts[2])]['action'], seen)
        return True

    def actions(self):
        result = {'settings': caption('Settings', 'Ajustes'), 'customize': caption('Customize', 'Personalizar'),
                  'refresh': caption('Refresh chats', 'Actualizar chats'), 'saved': caption('Saved Messages', 'Mensajes guardados'),
                  'contacts': caption('Contacts', 'Contactos'), 'folders': caption('Folders', 'Carpetas'),
                  'emoji': caption('Custom emoji', 'Emojis personalizados'), 'stickers': 'Stickers',
                  'attach': caption('Attach file', 'Adjuntar archivo'), 'send': caption('Send', 'Enviar')}
        for key, widget in self.widgets.items():
            if self.custom_root(key):
                continue
            if isinstance(widget, (ttk.Button, ttk.Checkbutton, ttk.Radiobutton)):
                result['widget:'+key] = self.names[key]+' · '+key
        return {action: label for action, label in result.items() if self.action_available(action)}

    def invoke(self, action):
        if self.editing or self.app.closed or self.app.closing:
            return
        if not self.action_available(action):
            return
        if action.startswith('widget:'):
            if action in self._invoking:
                return
            self._invoking.add(action)
            try:
                key = action[7:]
                widget = self.widgets.get(key)
                if widget is not None and hasattr(widget, 'invoke') and widget.winfo_exists():
                    widget.invoke()
                elif key.startswith('custom/'):
                    # Hiding an original panel must not disable its copies.
                    parts = key.split('/')
                    item = next((item for item in self.store.document['items'] if item['id'] == parts[1]), None)
                    if item is not None and len(parts) == 2 and item['kind'] == 'button':
                        self.invoke(item['action'])
                    elif item is not None and len(parts) == 3 and parts[2].isdigit():
                        index = int(parts[2])
                        if index < len(item['entries']):
                            self.invoke(item['entries'][index]['action'])
            finally:
                self._invoking.discard(action)
            return
        actions = {'settings': self.app.open_fixed_settings, 'customize': self.app.open_customization,
                   'refresh': lambda: self.app.refresh(reconnect=True), 'saved': self.app.saved_messages, 'contacts': self.app.open_contacts,
                   'folders': self.app.folder_dialog, 'emoji': lambda: self.app.telegram_picker(True),
                   'stickers': self.app.telegram_picker, 'attach': self.app.pick_attachment, 'send': self.app.send}
        command = actions.get(action)
        if command:
            command()

    def set_editing(self, enabled):
        if not enabled and not self.editing and not self._bindings:
            self._drag = self._preview = None
            return
        self.editing = enabled
        if not enabled:
            self._drag = self._preview = None
        tag = 'LayoutEditor'+str(id(self))
        for widget in self.widgets.values():
            try:
                tags = tuple(t for t in widget.bindtags() if t != tag)
                widget.bindtags((tag,)+tags if enabled else tags)
            except tk.TclError:
                pass
        if enabled and not self._bindings:
            for event, handler in [('<ButtonPress-1>', self.press), ('<B1-Motion>', self.motion), ('<ButtonRelease-1>', self.release)]:
                ident = self.app.root.bind_class(tag, event, handler)
                self._bindings.append((event, ident))
        elif not enabled:
            for event, ident in self._bindings:
                self.app.root.unbind_class(tag, event)
                # Python 3.15 unbind_class already deletes its Tcl commands;
                # older Tkinter versions leave them registered.
                if ident and self.app.root.tk.call('info', 'commands', ident):
                    self.app.root.deletecommand(ident)
            self._bindings.clear()

    def press(self, event):
        key = next((k for k, w in self.widgets.items() if w is event.widget), None)
        if key is None:
            return 'break'
        self.selected = key
        widget = event.widget
        rect = self.current_rect(widget)
        self._drag = (key, event.x_root, event.y_root, rect, bool(event.state & 1))
        if self.editor:
            self.editor.select(key)
        return 'break'

    def current_rect(self, widget):
        parent = widget.master
        width, height = max(1, parent.winfo_width()), max(1, parent.winfo_height())
        return rectangle([widget.winfo_x()/width, widget.winfo_y()/height, widget.winfo_width()/width, widget.winfo_height()/height])

    def motion(self, event):
        if not self._drag:
            return 'break'
        key, x, y, rect, resize = self._drag
        widget = self.widgets[key]
        dx = (event.x_root-x)/max(1, widget.master.winfo_width())
        dy = (event.y_root-y)/max(1, widget.master.winfo_height())
        changed = [rect[0], rect[1], max(.01, rect[2]+dx), max(.01, rect[3]+dy)] if resize else [max(0, rect[0]+dx), max(0, rect[1]+dy), rect[2], rect[3]]
        spec = self.store.document
        self._preview = snapped_rect(changed, spec['columns'], spec['rows'], spec['snap'])
        # Only move an overlay during the gesture; the live widgets retain their
        # geometry until mouse-up, avoiding hundreds of disk writes/rebuilds.
        self.editor.preview_rect(self._preview) if self.editor else None
        return 'break'

    def release(self, event):
        if self._drag:
            key = self._drag[0]
            preview = getattr(self, '_preview', None)
            self._drag = None
            self._preview = None
            if preview:
                self.move(key, preview)
        return 'break'

    def frozen_siblings(self, document, widget):
        """Preserve existing geometry when one packed child becomes movable."""
        parent = widget.master
        for key, sibling in self.widgets.items():
            if sibling.master is parent and not self.custom_root(key) and sibling.winfo_manager():
                spec = document['overrides'].setdefault(key, {'hidden': False})
                if 'rect' not in spec:
                    spec['rect'] = self.current_rect(sibling)

    def change(self, document):
        document['enabled'] = True
        if self.store.commit(document):
            self.app.rebuild_screen()

    def move(self, key, rect):
        document = deepcopy(self.store.document)
        if self.custom_root(key):
            item = next(i for i in document['items'] if 'custom/'+i['id'] == key)
            item['rect'] = rectangle(rect)
        else:
            self.frozen_siblings(document, self.widgets[key])
            document['overrides'].setdefault(key, {})['rect'] = rectangle(rect)
        self.change(document)

    def add(self, kind, text, action='', entries=None, resource='', rect=None):
        document = deepcopy(self.store.document)
        ident = uuid.uuid4().hex
        document['items'].append({'id': ident, 'kind': kind, 'text': text, 'action': action,
                                  'entries': entries or [], 'resource': resource,
                                  'rect': rect or [.35, .1, .25, .12]})
        self.selected = 'custom/'+ident
        self.change(document)
        return self.selected

    def duplicate(self, key):
        if self.custom_root(key):
            document = deepcopy(self.store.document)
            item = deepcopy(next(i for i in document['items'] if 'custom/'+i['id'] == key))
            item['id'] = uuid.uuid4().hex
            item['hidden'] = False
            new_key = 'custom/'+item['id']
            document['items'].append(item)
            for old_key, spec in list(document['overrides'].items()):
                if old_key.startswith(key+'/'):
                    document['overrides'][new_key+old_key[len(key):]] = deepcopy(spec)
            self.selected = new_key
            self.change(document)
            return new_key
        widget = self.widgets[key]
        if hasattr(widget, 'invoke'):
            return self.add('button', self.names[key], 'widget:'+key)
        entries = [{'text': self.names[k], 'action': 'widget:'+k} for k, w in self.widgets.items()
                   if k.startswith(key+'/') and hasattr(w, 'invoke')]
        if entries:
            return self.add('panel', self.names[key], entries=entries)
        return self.add('label', self.names[key])

    def hide(self, key):
        self.store.archive()
        document = deepcopy(self.store.document)
        if self.custom_root(key):
            next(i for i in document['items'] if 'custom/'+i['id'] == key)['hidden'] = True
        else:
            document['overrides'].setdefault(key, {})['hidden'] = True
        self.change(document)

    def tile(self, columns=2):
        if not self.selected or self.selected not in self.widgets:
            return
        widget = self.widgets[self.selected]
        siblings = [(k, w) for k, w in self.widgets.items() if w.master is widget.master and w.winfo_manager()]
        document = deepcopy(self.store.document)
        items = {'custom/'+item['id']: item for item in document['items']}
        for (key, widget), rect in zip(siblings, tile_rectangles(len(siblings), columns)):
            if self.custom_root(key):
                items[key]['rect'] = rect
            else:
                document['overrides'][key] = {'hidden': False, 'rect': rect}
        self.change(document)

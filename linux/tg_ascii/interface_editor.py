"""A small inspector for live layout changes, profiles and recoverable resources."""
from . import APP_NAME
from copy import deepcopy
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .app_dialogs import filedialog, messagebox, simpledialog
from .interface_layout import caption
from .interface_store import default_layout, appearance, write_layout


class InterfaceEditor:
    def __init__(self, runtime):
        self.runtime, self.app, self.store = runtime, runtime.app, runtime.store
        self.window = tk.Toplevel(self.app.root)
        self.window.title(caption('Customize interface · Local', 'Personalizar interfaz · Local'))
        self.window.geometry('510x750')
        self.window.minsize(380, 500)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        runtime.editor = self
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill='both', expand=True, padx=8, pady=8)
        from .app_dialogs import scrollable
        tabs = []
        for en, es in [('Layout', 'Diseño'), ('Profiles', 'Diseños guardados'), ('Files / recovery', 'Archivos / recuperar')]:
            page = ttk.Frame(notebook)
            notebook.add(page, text=caption(en, es))
            tabs.append(scrollable(page))
        self.build_layout(tabs[0])
        built = {0}
        def selected(_=None):
            index = notebook.index(notebook.select())
            if index in built:
                return
            # Profile/resource scans and forms are irrelevant while arranging
            # controls. Construct them only when their tab is first opened.
            (self.build_profiles if index == 1 else self.build_files)(tabs[index])
            built.add(index)
        notebook.bind('<<NotebookTabChanged>>', selected)
        footer = ttk.Frame(self.window, padding=8)
        footer.pack(fill='x')
        ttk.Button(footer, text=caption('Finish editing', 'Terminar edición'), command=self.close).pack(side='right')
        ttk.Button(footer, text=caption('Restore defaults', 'Restaurar valores iniciales'), command=self.app.restore_interface_defaults).pack(side='left')
        runtime.set_editing(True)
        self.populate()

    def button(self, parent, en, es, command):
        widget = ttk.Button(parent, text=caption(en, es), command=lambda: self.run(command))
        widget.pack(fill='x', pady=3)
        return widget

    def run(self, command):
        try:
            command()
        except (OSError, ValueError, tk.TclError, KeyError) as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.window)

    def build_layout(self, parent):
        ttk.Label(parent, text=caption('Local only: Telegram does not synchronize widget positions or custom menus.\nClick a control in the app, drag to move it, Shift-drag to resize. Actions are paused while editing.',
            'Solo local: Telegram no sincroniza posiciones ni menús propios.\nPulsa un control en la app; arrastra para mover y Mayús + arrastrar para cambiar tamaño. Las acciones se pausan mientras editas.'), wraplength=440).pack(fill='x', pady=8)
        self.items = ttk.Treeview(parent, show='tree', height=8, selectmode='browse')
        self.items.pack(fill='x')
        self.items.bind('<<TreeviewSelect>>', self.changed_selection)
        self.selected_label = ttk.Label(parent, wraplength=440)
        self.selected_label.pack(fill='x', pady=4)
        form = ttk.Frame(parent)
        form.pack(fill='x')
        self.coords = []
        for index, label in enumerate(('X %', 'Y %', caption('Width %', 'Ancho %'), caption('Height %', 'Alto %'))):
            ttk.Label(form, text=label).grid(row=0, column=index)
            value = tk.DoubleVar(value=0)
            ttk.Spinbox(form, from_=0, to=100, increment=1, textvariable=value, width=8).grid(row=1, column=index, sticky='ew')
            form.columnconfigure(index, weight=1)
            self.coords.append(value)
        self.button(parent, 'Apply position and size', 'Aplicar posición y tamaño', self.apply_position)
        row = ttk.Frame(parent)
        row.pack(fill='x')
        for en, es, action in [('Duplicate', 'Duplicar', self.duplicate), ('Hide / remove', 'Ocultar / quitar', self.remove),
                               ('Undo', 'Deshacer', lambda: self.history(False)), ('Redo', 'Rehacer', lambda: self.history(True))]:
            ttk.Button(row, text=caption(en, es), command=lambda fn=action: self.run(fn)).pack(side='left', padx=2)
        self.button(parent, 'Rename selected label', 'Cambiar texto seleccionado', self.rename)
        grid = ttk.Frame(parent)
        grid.pack(fill='x', pady=8)
        self.columns = tk.IntVar(value=self.store.document['columns'])
        self.rows = tk.IntVar(value=self.store.document['rows'])
        self.gap = tk.IntVar(value=self.store.document['gap'])
        for column, (en, es, value, maximum) in enumerate([('Columns', 'Columnas', self.columns, 100), ('Rows', 'Filas', self.rows, 100), ('Spacing', 'Separación', self.gap, 48)]):
            ttk.Label(grid, text=caption(en, es)).grid(row=0, column=column)
            ttk.Spinbox(grid, from_=0 if column==2 else 1, to=maximum, textvariable=value, width=8).grid(row=1, column=column)
        self.snap = tk.BooleanVar(value=self.store.document['snap'])
        ttk.Checkbutton(parent, text=caption('Snap movement to rows / columns', 'Ajustar movimiento a filas / columnas'), variable=self.snap).pack(anchor='w')
        self.button(parent, 'Apply grid', 'Aplicar cuadrícula', self.apply_grid)
        self.button(parent, 'Arrange siblings in columns', 'Distribuir controles hermanos en columnas', lambda: self.runtime.tile(self.columns.get()))
        ttk.Label(parent, text=caption('Controls may overlap. New controls are added above existing panels. Duplicates use the same action.',
            'Puedes superponer controles. Los nuevos se colocan sobre los paneles. Los duplicados conservan la misma acción.'), wraplength=440).pack(fill='x', pady=6)
        for kind, en, es in [('button', 'Add button', 'Añadir botón'), ('menu', 'Add menu', 'Añadir menú'),
                             ('panel', 'Add button panel', 'Añadir panel de botones'), ('label', 'Add text', 'Añadir texto'), ('image', 'Add image', 'Añadir imagen')]:
            self.button(parent, en, es, lambda k=kind: self.add(k))
        self.button(parent, 'Bring selected item to front', 'Traer elemento al frente', self.to_front)
        self.button(parent, 'Restore hidden controls', 'Recuperar controles ocultos', self.restore_hidden)

    def populate(self):
        previous = getattr(self, '_item_labels', {})
        names = self.runtime.names
        removed = previous.keys() - names.keys()
        if removed:
            self.items.delete(*removed)
        for key, name in names.items():
            label = name+'  ['+key+']'
            if key not in previous:
                self.items.insert('', 'end', iid=key, text=label)
            elif previous[key] != name:
                self.items.item(key, text=label)
        if tuple(previous) != tuple(names):
            self.items.set_children('', *names)
        self._item_labels = dict(names)
        if self.runtime.selected in self.runtime.widgets:
            self.select(self.runtime.selected)

    def select(self, key):
        if self.items.exists(key):
            if self.items.selection() != (key,):
                self.items.selection_set(key)
            self.items.see(key)
            self.selected_label.configure(text=self.runtime.names.get(key, key))
            self.preview_rect(self.runtime.current_rect(self.runtime.widgets[key]))

    def changed_selection(self, _=None):
        keys = self.items.selection()
        if keys:
            self.runtime.selected = keys[0]
            self.select(keys[0])

    def preview_rect(self, rect):
        for var, value in zip(self.coords, rect):
            var.set(round(value*100, 2))

    def apply_position(self):
        if self.runtime.selected:
            values = [v.get()/100 for v in self.coords]
            if any(v<0 or v>1 for v in values) or min(values[2:])<=0:
                raise ValueError(caption('Enter percentages between 0 and 100.', 'Introduce porcentajes entre 0 y 100.'))
            self.runtime.move(self.runtime.selected, values)

    def duplicate(self):
        if self.runtime.selected:
            self.runtime.duplicate(self.runtime.selected)

    def remove(self):
        if self.runtime.selected and messagebox.askyesno(APP_NAME, caption('Hide this item? You can recover it with Undo or Restore hidden controls.',
                '¿Ocultar este elemento? Puedes recuperarlo con Deshacer o Recuperar controles ocultos.'), parent=self.window):
            self.runtime.hide(self.runtime.selected)

    def history(self, redo):
        if (self.store.redo() if redo else self.store.undo()):
            self.app.rebuild_screen()

    def apply_grid(self):
        columns, rows, gap = self.columns.get(), self.rows.get(), self.gap.get()
        if not 1<=columns<=100 or not 1<=rows<=100 or not 0<=gap<=48:
            raise ValueError(caption('Grid values are out of range.', 'Valores de cuadrícula fuera de rango.'))
        document = deepcopy(self.store.document)
        document.update(columns=columns, rows=rows, gap=gap, snap=self.snap.get())
        self.runtime.change(document)

    def rename(self):
        key = self.runtime.selected
        if not key:
            return
        text = simpledialog.askstring(APP_NAME, caption('Label text', 'Texto del control'), initialvalue=self.runtime.names[key], parent=self.window)
        if text is None:
            return
        document = deepcopy(self.store.document)
        if self.runtime.custom_root(key):
            next(i for i in document['items'] if 'custom/'+i['id']==key)['text'] = text
        else:
            document['overrides'].setdefault(key, {})['text'] = text
        self.runtime.change(document)

    def add(self, kind):
        window = tk.Toplevel(self.window)
        window.title(caption('Add item', 'Añadir elemento'))
        window.geometry('430x440')
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=caption('Name / text', 'Nombre / texto')).pack(anchor='w')
        text = ttk.Entry(frame)
        text.pack(fill='x')
        text.insert(0, kind)
        actions = self.runtime.actions()
        keys = list(actions)
        ttk.Label(frame, text=caption('Action', 'Acción')).pack(anchor='w', pady=(8, 0))
        choice = ttk.Combobox(frame, values=list(actions.values()), state='readonly')
        choice.pack(fill='x')
        choice.current(0)
        selected = []
        entries = tk.Listbox(frame, height=6)
        if kind in ('menu', 'panel'):
            entries.pack(fill='both', expand=True, pady=8)
            def add_entry():
                key = keys[choice.current()]
                selected.append({'text': actions[key], 'action': key})
                entries.insert('end', actions[key])
            ttk.Button(frame, text=caption('Add this action to menu', 'Añadir esta acción al menú'), command=add_entry).pack(fill='x')
        resource = tk.StringVar()
        if kind == 'image':
            def choose_image():
                path = filedialog.askopenfilename(parent=window, filetypes=[('Images', '*.png *.jpg *.jpeg *.webp *.gif')])
                if path:
                    resource.set(self.store.import_resource(path))
            ttk.Button(frame, text=caption('Choose image', 'Elegir imagen'), command=lambda: self.run(choose_image)).pack(fill='x', pady=8)
            ttk.Label(frame, textvariable=resource, wraplength=390).pack(fill='x')
        def create():
            if kind in ('menu', 'panel') and not selected:
                selected.append({'text': actions[keys[choice.current()]], 'action': keys[choice.current()]})
            self.runtime.add(kind, text.get(), keys[choice.current()], selected, resource.get())
            window.destroy()
        ttk.Button(frame, text=caption('Add', 'Añadir'), command=lambda: self.run(create)).pack(fill='x', pady=12)

    def to_front(self):
        key = self.runtime.selected
        if not key:
            return
        if self.runtime.custom_root(key):
            document = deepcopy(self.store.document)
            item = next(i for i in document['items'] if 'custom/'+i['id']==key)
            document['items'].remove(item)
            document['items'].append(item)
            self.runtime.change(document)
        else:
            document = deepcopy(self.store.document)
            parent = self.runtime.widgets[key].master
            for other, widget in self.runtime.widgets.items():
                if widget.master is parent and other in document['overrides']:
                    document['overrides'][other].pop('front', None)
            document['overrides'].setdefault(key, {})['front'] = True
            self.runtime.change(document)

    def restore_hidden(self):
        document = deepcopy(self.store.document)
        for spec in document['overrides'].values():
            spec['hidden'] = False
        for item in document['items']:
            item['hidden'] = False
        self.runtime.change(document)

    def build_profiles(self, parent):
        ttk.Label(parent, text=caption('Save layouts and appearance together. The selected layout is restored automatically at startup. Profiles are local; export shares their layout and colors.',
            'Guarda el diseño y la apariencia juntos. El seleccionado se activa al iniciar. Son locales; exportar comparte su distribución y colores.'), wraplength=440).pack(fill='x', pady=8)
        self.profiles = tk.Listbox(parent, height=9)
        self.profiles.pack(fill='x')
        self.profile_paths = []
        self.button(parent, 'Save current design', 'Guardar diseño actual', self.save_profile)
        self.button(parent, 'Activate selected design', 'Activar diseño seleccionado', self.activate_profile)
        self.button(parent, 'Import design JSON', 'Importar diseño JSON', self.import_profile)
        self.button(parent, 'Export current design', 'Exportar diseño actual', self.export_profile)
        self.button(parent, 'Remove saved design', 'Eliminar diseño guardado', self.delete_profile)
        self.button(parent, 'Default layout, keep colors', 'Distribución inicial, conservar colores', self.default_positions)
        self.button(parent, 'Reload files from disk', 'Recargar archivos del disco', self.reload_files)
        self.load_profiles()

    def load_profiles(self):
        self.profiles.delete(0, 'end')
        self.profile_paths = self.store.profiles()
        from .preferences import read_json
        for path in self.profile_paths:
            self.profiles.insert('end', str(read_json(path, {}).get('name', path.stem)))

    def save_profile(self):
        name = simpledialog.askstring(APP_NAME, caption('Design name', 'Nombre del diseño'), parent=self.window)
        if name:
            from .motion import get_motion
            self.store.save_profile(name, self.app.preferences.values, get_motion(self.app))
            self.load_profiles()

    def activate_profile(self):
        selected = self.profiles.curselection()
        if selected:
            self.activate(self.profile_paths[selected[0]])

    def activate(self, path):
        self.store.archive()
        document = self.store.load(path)
        self.app.preferences.save(document['appearance'])
        if 'motion' in document:
            from .motion import save_motion
            save_motion(self.app, document['motion'])
        self.app.rebuild_screen()

    def import_profile(self):
        path = filedialog.askopenfilename(parent=self.window, filetypes=[('Interface JSON', '*.json')])
        if path:
            self.activate(path)

    def export_profile(self):
        path = filedialog.asksaveasfilename(parent=self.window, defaultextension='.json', initialfile='tg-ascii-layout.json')
        if path:
            document = deepcopy(self.store.document)
            document['appearance'] = appearance(self.app.preferences.values)
            from .motion import get_motion
            document['motion'] = get_motion(self.app)
            # Export no absolute local paths, account data or session material.
            document['appearance'].pop('interface_background', None)
            write_layout(path, document)

    def delete_profile(self):
        selected = self.profiles.curselection()
        if selected and messagebox.askyesno(APP_NAME, caption('Move this design to the recoverable trash?', '¿Mover este diseño a la papelera recuperable?'), parent=self.window):
            self.store.trash(self.profile_paths[selected[0]])
            self.load_profiles()
            self.load_files()

    def default_positions(self):
        self.store.archive()
        self.store.commit(default_layout())
        self.app.rebuild_screen()

    def reload_files(self):
        document = self.store.reload()
        self.app.preferences.save(document['appearance'])
        from .motion import reload_motion
        reload_motion(self.app)
        self.app.rebuild_screen()

    def build_files(self, parent):
        ttk.Label(parent, text=caption('Editable folders for images, icons, menus, buttons and fonts. Removed resources go to Trash; previous layouts are kept in History. App code and account sessions are kept separate.',
            'Carpetas editables para imágenes, iconos, menús, botones y fuentes. Los recursos eliminados van a Papelera; los diseños anteriores quedan en Historial. El código y las sesiones se guardan aparte.'), wraplength=440).pack(fill='x', pady=8)
        self.button(parent, 'Open customization folder', 'Abrir carpeta de personalización', self.app.open_interface_folder)
        self.file_list = tk.Listbox(parent, height=9)
        self.file_list.pack(fill='x')
        self.file_paths = []
        self.button(parent, 'Import resource', 'Importar recurso', self.import_file)
        self.button(parent, 'Move selected file to trash', 'Mover archivo seleccionado a papelera', self.delete_file)
        self.trash_list = tk.Listbox(parent, height=5)
        self.trash_list.pack(fill='x', pady=8)
        self.button(parent, 'Recover selected file', 'Recuperar archivo seleccionado', self.restore_file)
        self.history_list = tk.Listbox(parent, height=5)
        self.history_list.pack(fill='x', pady=8)
        self.button(parent, 'Recover previous layout', 'Recuperar diseño anterior', self.recover_history)
        self.button(parent, 'Refresh file lists', 'Actualizar listas de archivos', self.load_files)
        self.load_files()

    def load_files(self):
        if not hasattr(self, 'file_list'):
            return
        from .preferences import read_json
        self.store.ensure()
        self.file_paths = sorted(p for p in (self.store.root/'resources').rglob('*') if p.is_file())
        self.file_list.delete(0, 'end')
        for path in self.file_paths:
            self.file_list.insert('end', path.relative_to(self.store.root/'resources').as_posix())
        self.trash_paths = sorted(p for p in (self.store.root/'trash').iterdir() if p.is_dir())
        self.trash_list.delete(0, 'end')
        for path in self.trash_paths:
            self.trash_list.insert('end', str(read_json(path/'metadata.json', {}).get('path', path.name)))
        self.history_paths = self.store.profiles(history=True)
        self.history_list.delete(0, 'end')
        for path in self.history_paths:
            self.history_list.insert('end', path.stem)

    def import_file(self):
        path = filedialog.askopenfilename(parent=self.window)
        if path:
            extension = Path(path).suffix.lower()
            category = 'menus' if extension=='.json' else 'fonts' if extension in ('.ttf', '.otf') else 'images'
            self.store.import_resource(path, category)
            self.load_files()

    def delete_file(self):
        selected = self.file_list.curselection()
        if selected and messagebox.askyesno(APP_NAME, caption('Remove this resource? You can restore it from Trash.', '¿Eliminar este recurso? Puedes recuperarlo de la Papelera.'), parent=self.window):
            self.store.trash(self.file_paths[selected[0]])
            self.load_files()

    def restore_file(self):
        selected = self.trash_list.curselection()
        if selected:
            self.store.restore(self.trash_paths[selected[0]])
            self.load_files()

    def recover_history(self):
        selected = self.history_list.curselection()
        if selected:
            self.activate(self.history_paths[selected[0]])

    def close(self):
        self.runtime.set_editing(False)
        self.runtime.editor = None
        self.window.destroy()

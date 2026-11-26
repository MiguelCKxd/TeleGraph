"""On-demand, local contact-card editor with protected recovery controls."""
import re
import tkinter as tk
from tkinter import ttk
from .app_dialogs import colorchooser

from .app_dialogs import Choice, scrollable
from .appearance import app_palette
from .contact_appearance import (
    ACTIONS,
    CONTACT_DEFAULTS,
    DENSITIES,
    SECTIONS,
    save_contact_preferences,
    validated_contact,
)
from .interface_layout import caption

LABELS = {
    'call': ('Call', 'Llamar'), 'video_call': ('Video call', 'Videollamada'),
    'gifs': ('GIFs', 'GIF'), 'polls': ('Polls', 'Encuestas'), 'posts': ('Posts', 'Publicaciones'),
    'gifts': ('Gifts', 'Regalos'), 'profile_music': ('Profile music', 'Música del perfil'),
    'similar': ('Similar channels', 'Canales similares'), 'membership': ('Join / leave', 'Unirse / salir'),
    'edit_self': ('Edit my profile', 'Editar mi perfil'), 'profile_design': ('Profile design', 'Diseño del perfil'),
    'info': ('Information', 'Información'), 'photos': ('Photos', 'Fotos'),
    'files': ('Files', 'Archivos'), 'audio': ('Music', 'Música'),
    'voice': ('Voice messages', 'Mensajes de voz'), 'links': ('Links', 'Enlaces'),
    'settings': ('Settings', 'Ajustes'), 'message': ('Message', 'Mensaje'),
    'share': ('Share contact', 'Compartir contacto'),
    'notifications': ('Notifications', 'Notificaciones'), 'edit_contact': ('Edit contact', 'Editar contacto'),
    'add_username': ('Add by username', 'Añadir por usuario'), 'refresh': ('Refresh', 'Actualizar'),
    'manage': ('Manage / settings', 'Gestionar / ajustes'),
}


def open_contact_settings(app, on_saved=None):
    current = getattr(app, '_contact_settings_window', None)
    if current is not None and current.winfo_exists():
        current.lift()
        return current
    window, frame = app.dialog(caption('Contact card appearance', 'Apariencia de la ficha de contacto'), '600x680')
    app._contact_settings_window = window
    footer = ttk.Frame(frame, padding=(0, 8))
    footer.pack(side='bottom', fill='x')
    notebook = ttk.Notebook(frame)
    notebook.pack(fill='both', expand=True)
    pages = []
    for en, es in (('Appearance', 'Apariencia'), ('Sections', 'Secciones'), ('Buttons', 'Botones')):
        page = ttk.Frame(notebook)
        notebook.add(page, text=caption(en, es))
        pages.append(scrollable(page))
    appearance = pages[0]
    ttk.Label(appearance, text=caption(
        'Local only. These choices are saved with interface designs. Telegram does not synchronize contact-card layouts; hidden data stays unavailable.',
        'Solo local. Estas opciones se guardan con los diseños de interfaz. Telegram no sincroniza el diseño de la ficha; los datos ocultos siguen sin estar disponibles.'),
        wraplength=470).pack(fill='x', pady=8)
    current_values = validated_contact(app.preferences.values)
    variables, choices = {}, {}
    for key, labels, options in (
            ('contact_density', [('Compact', 'Compacta'), ('Comfortable', 'Normal'), ('Spacious', 'Amplia')], DENSITIES),
            ('contact_alignment', [('Left alignment', 'Alineación izquierda'), ('Centered', 'Centrada')], ('left', 'center'))):
        choice = Choice(appearance, values=[caption(*label) for label in labels])
        choice.pack(fill='x', pady=4)
        choice.current(options.index(current_values[key]))
        choices[key] = (choice, options)
    for key, en, es, low, high in (
            ('contact_card_width', 'Preferred width (px)', 'Ancho preferido (px)', 320, 1200),
            ('contact_avatar_size', 'Avatar size (px)', 'Tamaño del avatar (px)', 48, 192),
            ('contact_border_width', 'Border width (px)', 'Grosor del borde (px)', 0, 8)):
        row = ttk.Frame(appearance)
        row.pack(fill='x', pady=5)
        ttk.Label(row, text=caption(en, es)).pack(side='left')
        value = variables[key] = tk.IntVar(value=current_values[key])
        ttk.Spinbox(row, from_=low, to=high, textvariable=value, width=7).pack(side='right')
    variables['contact_round_avatar'] = tk.BooleanVar(value=current_values['contact_round_avatar'])
    ttk.Checkbutton(appearance, text=caption('Round avatar', 'Avatar circular'),
                    variable=variables['contact_round_avatar']).pack(anchor='w', pady=6)
    color_labels = [('background', 'Header background', 'Fondo de cabecera'), ('text', 'Header text', 'Texto de cabecera'),
                    ('accent', 'Avatar accent', 'Acento del avatar'), ('border_color', 'Header border', 'Borde de cabecera')]
    for suffix, en, es in color_labels:
        key = 'contact_' + suffix
        variable = variables[key] = tk.StringVar(value=current_values[key])
        row = ttk.Frame(appearance)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text=caption(en, es), width=20).pack(side='left')
        ttk.Entry(row, textvariable=variable, width=10).pack(side='left', padx=3)
        def choose(k=key, role=suffix):
            palette = app_palette(app.preferences.values)
            fallback = palette['bg' if role == 'background' else 'text']
            selected = variables[k].get()
            color = colorchooser.askcolor(color=selected if re.fullmatch(r'#[0-9a-fA-F]{6}', selected) else fallback, parent=window)[1]
            if color:
                variables[k].set(color.lower())
        ttk.Button(row, text=caption('Choose', 'Elegir'), command=choose).pack(side='left')
        ttk.Button(row, text=caption('Inherit', 'Heredar'), command=lambda v=variable: v.set('')).pack(side='left')
    ttk.Label(appearance, text=caption(
        'Blank colors inherit the app theme. Buttons retain the global borders, shadows and text effects. The width adapts to the available window space.',
        'Los colores vacíos heredan el tema. Los botones conservan los bordes, sombras y efectos de texto globales. El ancho se adapta al espacio disponible.'),
        wraplength=470).pack(fill='x', pady=8)

    orders, hidden, lists, refreshers = {}, {}, {}, []
    for page, group, available, protected in zip(pages[1:], ('section', 'action'), (SECTIONS, ACTIONS), ('settings', 'manage')):
        orders[group] = list(current_values[f'contact_{group}_order'])
        hidden[group] = set(current_values[f'contact_hidden_{group}s'])
        ttk.Label(page, text=caption('Select an item, then move or hide it. Settings remain accessible.',
                                    'Selecciona un elemento para moverlo u ocultarlo. Los ajustes siguen accesibles.'),
                  wraplength=470).pack(fill='x', pady=8)
        listing = lists[group] = tk.Listbox(page, height=9, exportselection=False)
        listing.pack(fill='both', expand=True)
        def refresh(g=group):
            box = lists[g]
            selection = box.curselection()
            box.delete(0, 'end')
            for ident in orders[g]:
                prefix = '○ ' if ident in hidden[g] else '● '
                box.insert('end', prefix + caption(*LABELS[ident]))
            if selection:
                box.selection_set(min(selection[0], len(orders[g])-1))
        refreshers.append(refresh)
        refresh()
        def move(delta, g=group, update=refresh):
            selected = lists[g].curselection()
            if selected and 0 <= selected[0] + delta < len(orders[g]):
                start, end = selected[0], selected[0] + delta
                orders[g][start], orders[g][end] = orders[g][end], orders[g][start]
                update()
                lists[g].selection_clear(0, 'end')
                lists[g].selection_set(end)
        def toggle(g=group, keep=protected, update=refresh):
            selected = lists[g].curselection()
            if not selected:
                return
            ident = orders[g][selected[0]]
            if ident != keep:
                hidden[g].symmetric_difference_update({ident})
                update()
        buttons = ttk.Frame(page)
        buttons.pack(fill='x', pady=6)
        for label, command in ((('Up', 'Subir'), lambda m=move: m(-1)),
                               (('Down', 'Bajar'), lambda m=move: m(1)),
                               (('Show / hide', 'Mostrar / ocultar'), toggle)):
            ttk.Button(buttons, text=caption(*label), command=command).pack(side='left', padx=2)

    def reset_fields():
        for key, variable in variables.items():
            variable.set(CONTACT_DEFAULTS[key])
        for key, (choice, options) in choices.items():
            choice.current(options.index(CONTACT_DEFAULTS[key]))
        for group, order in orders.items():
            order[:] = CONTACT_DEFAULTS[f'contact_{group}_order']
            hidden[group].clear()
        for refresh in refreshers:
            refresh()

    def save(reset=False):
        try:
            if reset:
                values = CONTACT_DEFAULTS
            else:
                values = {key: variable.get() for key, variable in variables.items()}
                for suffix, _, _ in color_labels:
                    key = 'contact_' + suffix
                    values[key] = values[key].strip().lower()
                values.update({key: options[choice.current()] for key, (choice, options) in choices.items()})
                for group, order in orders.items():
                    values[f'contact_{group}_order'] = order
                    values[f'contact_hidden_{group}s'] = list(hidden[group])
                if validated_contact(values) != values:
                    raise ValueError(caption('Use valid sizes and #RRGGBB colors, or leave colors blank.',
                                             'Usa tamaños válidos y colores #RRGGBB, o deja los colores vacíos.'))
            save_contact_preferences(app, values, on_saved)
        except (ValueError, OSError, tk.TclError) as error:
            app.show_error(error)
            return
        if reset:
            reset_fields()
        else:
            window.destroy()

    ttk.Button(footer, text=caption('Restore contact defaults', 'Restaurar ficha predeterminada'),
               command=lambda: save(True)).pack(side='left')
    ttk.Button(footer, text=caption('Save', 'Guardar'), command=save).pack(side='right')
    return window

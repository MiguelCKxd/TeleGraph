"""Compact category-based settings with a persistent save footer."""
import sys
import tkinter as tk
from tkinter import ttk
from . import APP_NAME
from .app_dialogs import colorchooser
from .app_dialogs import Choice,scrollable
from .scrolling import FlowFrame
from .i18n import tr
from .interface_layout import caption


class DesktopSettings:
    def build_settings_tab(self):
        # No appearance galleries/forms are constructed on the default chat
        # path. Their widgets are needed only when the user opens Settings.
        page = self.settings_page
        page._settings_built = False
        def selected(_=None):
            if page.winfo_exists() and self.notebook.select()==str(page) and not page._settings_built:
                page._settings_built = True
                try:
                    self.build_settings_contents()
                except Exception as exc:
                    page._settings_built = False
                    for widget in page.winfo_children():
                        widget.destroy()
                    if hasattr(self, 'show_error'):
                        self.show_error(exc)
                    raise
        self.notebook.bind('<<NotebookTabChanged>>', selected, add='+')

    def build_settings_contents(self):
        page=self.settings_page
        footer=ttk.Frame(page,padding=(8,6));footer.pack(side='bottom',fill='x')
        navigation=ttk.Frame(page,padding=8);navigation.pack(side='top',fill='x')
        body=ttk.Frame(page);body.pack(fill='both',expand=True)
        self.viewport.minimum=(440,420);self.viewport.fit_content()
        categories=['Apariencia','Customization','Chats','Notifications','Cuenta','Windows','App logos','Updates','Funciones complejas']
        picker=Choice(navigation,values=[caption('Customization','Personalización') if v=='Customization' else tr(v) for v in categories]);picker.pack(fill='x')
        selected=getattr(self,'_settings_category',0);picker.current(selected)
        pages=[];sections={}
        for label in categories:
            container=ttk.Frame(body);pages.append(container);sections[label]=scrollable(container)
        def choose(event=None):
            index=max(0,picker.current());self._settings_category=index
            for i,container in enumerate(pages):
                if i==index:container.pack(fill='both',expand=True)
                else:container.pack_forget()
        picker.bind('<<ComboboxSelected>>',choose);choose()
        self._settings_picker=picker
        self._settings_choose=choose
        wrap_width = None
        style = ttk.Style(self.root)
        def resized(event):
            nonlocal wrap_width
            width = max(120,event.width-48)
            if width != wrap_width:
                wrap_width = width
                style.configure('Settings.TCheckbutton',wraplength=width)
        body.bind('<Configure>',resized)
        appearance=sections['Apariencia'];chats=sections['Chats'];account=sections['Cuenta'];logos=sections['App logos']
        self.add_language_picker(appearance)
        display_name = tk.StringVar(value=self.preferences.values.get('app_display_name', ''))
        ttk.Label(appearance, text=caption('App display name', 'Nombre visible de la app')).pack(anchor='w')
        ttk.Entry(appearance, textvariable=display_name).pack(fill='x')
        choices={}
        for key,label,parent in [('theme','Interface theme',appearance),('logo_theme','Logo theme',logos)]:
            ttk.Label(parent,text=tr(label)).pack(anchor='w',pady=(10,2))
            choice=Choice(parent,values=[tr('Dark'),tr('Light'),tr('System')]);choice.current(('dark','light','system').index(self.preferences.values[key]));choice.pack(fill='x',pady=3);choices[key]=choice
            if key=='logo_theme':self.logo_theme_picker=choice
        font_choice,families=self.font_picker(appearance);font_choice.pack_configure(fill='x')
        size=tk.IntVar(value=self.preferences.values['font_size'])
        ttk.Label(appearance,text=tr('Tamaño del texto')).pack(anchor='w',pady=(10,2))
        ttk.Spinbox(appearance,from_=10,to=20,textvariable=size,width=6).pack(anchor='w')
        color_options = {
            'text_color': (tr('Text color'), 'text'), 'background_color': (tr('Background color'), 'bg'),
            'accent_color': (tr('Accent color'), 'strong'),
            'bubble_in_color': (caption('Incoming bubble color', 'Color de burbujas recibidas'), 'panel'),
            'bubble_out_color': (caption('Outgoing bubble color', 'Color de burbujas enviadas'), 'selected'),
        }
        colors={key:tk.StringVar(value=self.preferences.values.get(key,'')) for key in color_options}
        from .appearance import app_palette
        preview=tk.Label(appearance,text=f'{APP_NAME}  > Hello / Hola',padx=12,pady=18);preview.pack(fill='x',pady=8)
        def preview_colors():
            values={**self.preferences.values,**{k:v.get() for k,v in colors.items()},'theme':('dark','light','system')[choices['theme'].current()]}
            palette=app_palette(values);preview.configure(bg=palette['bg'],fg=palette['text'])
        def pick_color(key):
            palette=app_palette(self.preferences.values)
            value=colorchooser.askcolor(color=colors[key].get() or palette[color_options[key][1]],parent=self.root,title=color_options[key][0])[1]
            if value:colors[key].set(value.lower());preview_colors()
        for key, (label, _) in color_options.items():
            row=FlowFrame(appearance);row.pack(fill='x',pady=3)
            ttk.Button(row,text=label,command=lambda k=key:pick_color(k)).pack(side='left')
            ttk.Button(row,text=tr('Default'),command=lambda k=key:(colors[k].set(''),preview_colors())).pack(side='left')
        choices['theme'].bind('<<ComboboxSelected>>',lambda _:preview_colors());preview_colors()
        background=tk.StringVar(value=self.preferences.values.get('interface_background',''))
        background_preview=ttk.Label(appearance);background_preview.pack(fill='x',pady=4)
        def background_changed(path):
            background.set(path)
            background_preview.image=None
            background_preview.configure(image='',text='' if path else tr('No interface image'))
            if path:
                def current():
                    return background_preview.winfo_exists() and background.get()==path
                def loaded(photo):
                    if current():
                        background_preview.image=photo
                        background_preview.configure(image=photo or '')
                self.request_photo(path,(320,130),loaded,owner=background_preview,valid=current)
        background_changed(background.get())
        from .interface_background import choose_interface_background
        row=FlowFrame(appearance);row.pack(fill='x',pady=4)
        ttk.Button(row,text=tr('Interface background image'),command=lambda:choose_interface_background(self,background_changed)).pack(side='left')
        ttk.Button(row,text=tr('Remove background'),command=lambda:background_changed('')).pack(side='left')
        ttk.Label(appearance,text=tr('Chat backgrounds stay independent and appear over the interface image.'),wraplength=480).pack(fill='x',pady=6)
        radii={}
        for key,label in [('button_radius','Button corners'),('menu_radius','Panel corners'),('bubble_radius','Bubble corners')]:
            ttk.Label(appearance,text=tr(label)+' (0–24 px)').pack(anchor='w',pady=(8,2))
            radii[key]=tk.IntVar(value=self.preferences.values.get(key,0))
            ttk.Spinbox(appearance,from_=0,to=24,textvariable=radii[key],width=6).pack(anchor='w')
        ttk.Label(appearance,text=tr('System menus keep the shape chosen by your operating system.'),wraplength=480).pack(fill='x',pady=10)
        from .visual_effects import build_effect_settings
        effects=build_effect_settings(appearance,self.preferences.values)
        effects.frame.pack(fill='x',pady=8)
        flags={}
        from .advanced_features import build_feature_settings
        advanced_flags = build_feature_settings(sections['Funciones complejas'], self.preferences)
        ttk.Button(sections['Funciones complejas'], text=tr('Calls and video'), command=self.call_settings).pack(fill='x', pady=5)
        flags['ask_account_startup']=tk.BooleanVar(value=self.preferences.values.get('ask_account_startup',True))
        ttk.Checkbutton(account,text=caption('Choose account at startup when several are saved','Elegir cuenta al iniciar si hay varias guardadas'),variable=flags['ask_account_startup'],style='Settings.TCheckbutton').pack(fill='x',pady=8)
        ttk.Label(account,text=caption('With one account the app opens directly. Turn this off to always open the last account.','Con una cuenta la app entra directamente. Desactívalo para abrir siempre la última cuenta.'),wraplength=480).pack(fill='x',pady=4)
        # 1.5.4: aliases, order and sign-out per account; windows and start.
        from .window_settings import build_accounts_section,build_windows_section
        build_accounts_section(self,account)
        build_windows_section(self,sections['Windows'])
        # 1.5.3: offline copy, cache and all data.
        ttk.Label(account,text=tr('App data'),style='Title.TLabel').pack(anchor='w',pady=(14,4))
        flags['offline_copy']=tk.BooleanVar(value=self.preferences.values.get('offline_copy',True))
        ttk.Checkbutton(account,text=tr('Keep a copy of my chats on this device to use the app offline'),variable=flags['offline_copy'],style='Settings.TCheckbutton').pack(fill='x',pady=4)
        ttk.Label(account,text=tr('Without a connection the app opens with this copy, and what you do waits and is sent when the connection returns.'),style='Muted.TLabel',wraplength=480).pack(fill='x',pady=(0,6))
        from .app_data import clear_cache,delete_all_data,cache_size,human_size
        cache_button=ttk.Button(account,text=tr('Clear cache'),command=lambda:clear_cache(self))
        cache_button.pack(fill='x',pady=4)
        def measured(size):
            try:
                if cache_button.winfo_exists():cache_button.configure(text=tr('Clear cache')+f' ({human_size(size)})')
            except tk.TclError:pass
        import threading
        root_folder=self.service.root
        threading.Thread(target=lambda:self.worker.events.put((measured,cache_size(root_folder))),daemon=True,name='tg-cache-size').start()
        ttk.Button(account,text=tr('Delete all app data'),command=lambda:delete_all_data(self)).pack(fill='x',pady=4)
        ttk.Label(account,text=tr('Clearing the cache keeps accounts, drafts and settings. Deleting all data signs out and leaves the app as newly installed.'),style='Muted.TLabel',wraplength=480).pack(fill='x',pady=(0,6))
        custom=sections['Customization']
        ttk.Label(custom,text=caption('Local: layouts, widget positions, duplicate controls, fonts, borders, shadows, animations and app icons. Telegram does not synchronize these client-specific changes.',
            'Local: diseños, posiciones, controles duplicados, fuentes, bordes, sombras, animaciones e iconos de la app. Telegram no sincroniza estos cambios propios del cliente.'),wraplength=480).pack(fill='x',pady=8)
        from .customization_sync import open_chat_themes
        from .profile_customization import open_profile_customization
        from .motion import open_motion_settings
        from .contact_settings import open_contact_settings
        for en,es,action in [
            ('Edit layout / saved designs','Editar interfaz / diseños guardados',self.open_customization),
            ('Contact card appearance','Apariencia de la ficha de contacto',lambda:open_contact_settings(self)),
            ('Animations / motion files','Animaciones / archivos de movimiento',lambda:open_motion_settings(self)),
            ('Open customization files','Abrir archivos de personalización',self.open_interface_folder),
            ('New independent app window','Nueva ventana de app independiente',self.open_independent_window),
            ('Restore default interface','Restaurar interfaz predeterminada',self.restore_interface_defaults),
            ('Telegram chat themes','Temas de chat de Telegram',lambda:open_chat_themes(self)),
            ('Profile design and configuration','Diseño y configuración del perfil',lambda:open_profile_customization(self)),
            ('Refresh Premium account status','Actualizar estado Premium de la cuenta',self.refresh_premium_status),
        ]:
            ttk.Button(custom,text=caption(en,es),command=action).pack(fill='x',pady=4)
        # 1.4: the official open-source client, as a source of original assets.
        ttk.Label(custom,text=caption('Official Telegram source code: download icons, sounds, emoji and styles from its resources and replace the files in "Open customization files".',
            'Código fuente oficial de Telegram: descarga iconos, sonidos, emojis y estilos de sus recursos y sustituye los archivos de «Abrir archivos de personalización».'),wraplength=480).pack(fill='x',pady=(12,4))
        for en,es,url in [
            ('Official Telegram Desktop repository (GitHub)','Repositorio oficial de Telegram Desktop (GitHub)','https://github.com/telegramdesktop/tdesktop'),
            ('Telegram Desktop resources folder','Carpeta de recursos de Telegram Desktop','https://github.com/telegramdesktop/tdesktop/tree/dev/Telegram/Resources'),
        ]:
            ttk.Button(custom,text=caption(en,es),command=lambda url=url:self.open_link(url,browser_only=True)).pack(fill='x',pady=4)
        flags['sync_customizations']=tk.BooleanVar(value=self.preferences.values.get('sync_customizations',True))
        ttk.Checkbutton(custom,text=caption('Synchronize supported appearance changes with Telegram','Sincronizar cambios de apariencia compatibles con Telegram'),variable=flags['sync_customizations'],style='Settings.TCheckbutton').pack(fill='x',pady=8)
        ttk.Label(custom,text=caption('Enabled by default. Save to apply this choice. Chat themes, wallpapers and supported profile appearance use Telegram when enabled. Local-only changes are marked in each editor. Privacy and account security always describe the real server settings.',
            'Activado por defecto. Guarda para aplicar la elección. Temas, fondos y apariencia de perfil compatibles usan Telegram al activarlo. Cada editor indica los cambios locales. Privacidad y seguridad de cuenta muestran siempre los ajustes reales del servidor.'),wraplength=480).pack(fill='x',pady=8)
        flags['animated_emoji']=tk.BooleanVar(value=self.preferences.values.get('animated_emoji',True))
        ttk.Checkbutton(chats,text=tr('Animated emoji'),variable=flags['animated_emoji'],style='Settings.TCheckbutton').pack(fill='x',pady=6)
        from .animation import renderer_available
        unavailable=[name for mime,name in [('application/x-tgsticker','TGS'),('video/webm','WebM')] if not renderer_available(mime)]
        if unavailable:ttk.Label(chats,text=tr('Static preview: animation engine unavailable')+' ('+', '.join(unavailable)+')',wraplength=480).pack(fill='x',pady=4)
        flags['telegram_backgrounds']=tk.BooleanVar(value=self.preferences.values.get('telegram_backgrounds',False))
        ttk.Checkbutton(chats,text=tr('Use Telegram chat backgrounds'),variable=flags['telegram_backgrounds'],style='Settings.TCheckbutton').pack(fill='x',pady=6)
        from .telegram_wallpapers import open_gallery
        ttk.Button(chats,text=tr('Telegram backgrounds'),command=lambda:open_gallery(self,enabled=flags['telegram_backgrounds'].get())).pack(fill='x',pady=4)
        for key,label,parent in [('show_seconds','Show seconds in timestamps',chats),('ascii_text','Mostrar texto en ASCII (oculta emojis)',appearance),('enter_send','Enter envia mensajes',chats),('compact','Lista de chats compacta',chats),('bubbles','Message bubbles',chats),('inline_media','Show media previews inside chats',chats),('local_pins','Unlimited local pins (not synchronized)',chats),('background_notifications','Keep connected when closing the window',sections['Notifications'])]:
            flags[key]=tk.BooleanVar(value=self.preferences.values[key]);ttk.Checkbutton(parent,text=tr(label),variable=flags[key],style='Settings.TCheckbutton').pack(fill='x',pady=6)
        # 1.4.1: keyboard shortcuts for sending and for a new line.
        from .composer_keys import options as shortcut_options, LABELS as SHORTCUT_LABELS
        option_values={}
        def option_row(parent,key,label,values,labels):
            row=ttk.Frame(parent);row.pack(fill='x',pady=4)
            ttk.Label(row,text=tr(label)).pack(side='left')
            box=ttk.Combobox(row,state='readonly',values=[tr(labels[value]) for value in values],width=26)
            current=self.preferences.values.get(key)
            box.current(values.index(current) if current in values else 0)
            box.pack(side='right')
            option_values[key]=(box,values)
            return box
        shortcuts=shortcut_options()
        option_row(chats,'shortcut_send','Send message with',shortcuts,SHORTCUT_LABELS)
        option_row(chats,'shortcut_newline','New line with',shortcuts,SHORTCUT_LABELS)
        ttk.Label(chats,text=tr('Automatic: with "Enter sends messages" on, Enter sends and Shift/{modifier}+Enter adds a line; with it off, Enter adds a line and {modifier}+Enter sends.').format(modifier='⌘' if sys.platform=='darwin' else 'Ctrl'),style='Muted.TLabel',wraplength=480).pack(fill='x',pady=(0,6))
        # 1.4.1: what happens to a word that does not fit at the end of a line.
        breaks=['auto','word','char','hyphen','syllable']
        break_labels={'auto':'Automatic (as until now)','word':'Move the whole word to the next line',
                      'char':'Cut the word at the line end, no mark (justified)',
                      'hyphen':'Cut at the line end with a hyphen (justified)',
                      'syllable':'Hyphen after the last syllable that fits'}
        option_row(appearance,'line_breaking','Line breaks',breaks,break_labels)
        ttk.Label(appearance,text=tr('Each language keeps its own rules: Chinese and Japanese break between characters, Arabic and Hebrew never use hyphens, and syllables follow the dictionary of the app language. Hyphen modes use the canvas chat view.'),style='Muted.TLabel',wraplength=480).pack(fill='x',pady=(0,6))
        # 1.5.2: undo any drag of the divider (also a list dragged out of sight).
        ttk.Label(appearance,text=tr('Chat list size'),style='Title.TLabel').pack(anchor='w',pady=(14,4))
        def restore_list_size():
            from .pane_memory import reset
            reset(self)
            self.status.set(tr('The chat list is back to its default size.'))
        ttk.Button(appearance,text=tr('Restore chat list size'),command=restore_list_size).pack(anchor='w')
        ttk.Label(appearance,text=tr('Applies at once. Use it if you dragged the list too small or out of sight.'),style='Muted.TLabel',wraplength=480).pack(fill='x',pady=(2,6))
        # 1.5: system resources and startup preparation (Customization).
        ttk.Label(custom,text=tr('System resources'),style='Title.TLabel').pack(anchor='w',pady=(14,4))
        levels=['limited','normal','unlimited']
        level_labels={'limited':'Limited','normal':'Normal (as until now)','unlimited':'Unlimited'}
        for key,label in (('resource_cpu','Processor (CPU)'),('resource_ram','Memory (RAM)'),('resource_gpu','Graphics (GPU / animations)'),('resource_network','Network (parallel downloads)')):
            option_row(custom,key,label,levels,level_labels)
        frame_labels={'auto':'Automatic (as until now)','15':'15 fps','24':'24 fps','30':'30 fps','60':'60 fps','120':'120 fps','unlimited':'Unlimited'}
        option_row(custom,'frame_limit','Frame rate limit',['auto','15','24','30','60','120','unlimited'],frame_labels)
        ttk.Label(custom,text=tr('Limited saves battery and memory; Unlimited uses more of your computer for speed. Graphics sets how many animations play at once and their frame rate. Thread and priority changes apply fully after restarting.'),style='Muted.TLabel',wraplength=480).pack(fill='x',pady=(0,6))
        # 3.0.0.2: one switch that stills every animation (off by default).
        flags['reduce_animations']=tk.BooleanVar(value=self.preferences.values.get('reduce_animations',False))
        ttk.Checkbutton(custom,text=tr('Disable all animations'),variable=flags['reduce_animations'],style='Settings.TCheckbutton').pack(fill='x',pady=6)
        ttk.Label(custom,text=tr('Animated emoji, stickers, transitions and effects stay still, so the app runs smoothly on slower devices. Off by default.'),style='Muted.TLabel',wraplength=480).pack(fill='x',pady=(0,6))
        flags['preload_startup']=tk.BooleanVar(value=self.preferences.values.get('preload_startup',False))
        ttk.Checkbutton(custom,text=tr('Prepare everything at startup (slower start, smoother use)'),variable=flags['preload_startup'],style='Settings.TCheckbutton').pack(fill='x',pady=6)
        ttk.Label(custom,text=tr('For powerful computers: once the chat list loads, all profile photos, the latest messages of your first chats and their emoji are prepared in advance.'),style='Muted.TLabel',wraplength=480).pack(fill='x',pady=(0,6))
        # 1.5.1: device or app menus. Replaces the three 'Always … with the
        # system …' switches (their choices are migrated to 'Custom').
        from .menu_style import KINDS, MODES, platform_name
        from .advanced_features import feature_enabled as _feature_on
        ttk.Label(custom,text=tr('Menus and windows'),style='Title.TLabel').pack(anchor='w',pady=(14,4))
        menus_on=_feature_on(self,'custom_menus')
        if not menus_on:
            # 1.5.2: without Customizable menus every menu uses its lightest version.
            ttk.Label(custom,text=tr('Each menu uses its lightest, smoothest version. Turn on Complex features › Customizable menus to choose and customize them.'),style='Muted.TLabel',wraplength=480).pack(fill='x',pady=(0,6))
        menus_parent=ttk.Frame(custom)
        if menus_on:menus_parent.pack(fill='x')
        mode_labels={'default':'Default (as until now)','system':'Prefer the device menus','app':'Prefer the app menus','custom':'Custom'}
        option_row(menus_parent,'menu_style','Menus to use',list(MODES),mode_labels)
        ttk.Label(menus_parent,text=tr('Device menus look like the rest of {system}; app menus follow the TG-ASCII theme. If a kind has no version on one side, the other one is used.').format(system=platform_name()),style='Muted.TLabel',wraplength=480).pack(fill='x',pady=(0,4))
        ttk.Label(menus_parent,text=tr('📁 opens the folder of each menu: edit its style.json or add a menu.py to make it yours; that version is then used every time the menu opens.'),style='Muted.TLabel',wraplength=480).pack(fill='x',pady=(0,4))
        kind_labels={'context_menu':'Right-click and ⋯ menus','message_box':'Notices and confirmations','file_picker':'Open and save files','color_picker':'Colour picker','emoji_picker':'Emoji palette','image_viewer':'Photo viewer','video_player':'Video player','audio_player':'Audio player','file_viewer':'Received files','media_editor':'Edit photos and videos before sending','file_preview':'Preview files before sending'}
        side_labels={'system':'Device','app':'App'}
        custom_frame=ttk.Frame(menus_parent);custom_frame.pack(fill='x')
        from . import custom_menus as _custom_menus
        stored=dict(self.preferences.values.get('menu_custom') or {})
        menu_boxes={}
        for kind,default in KINDS:
            row=ttk.Frame(custom_frame);row.pack(fill='x',pady=2)
            ttk.Label(row,text=tr(kind_labels[kind])).pack(side='left')
            box=ttk.Combobox(row,state='readonly',values=[tr(side_labels['system'])+' ('+platform_name()+')',f"{tr(side_labels['app'])} ({APP_NAME})"],width=22)
            box.current(0 if stored.get(kind,default)=='system' else 1)
            folder_button=ttk.Button(row,text='📁',width=3,command=lambda kind=kind:_custom_menus.open_folder(kind,on_error=lambda error:self.worker.events.put((self.show_error,error))))
            folder_button.pack(side='right',padx=(4,0))
            box.pack(side='right')
            if _custom_menus.active(kind):
                ttk.Label(row,text='★ '+tr('Customized'),style='Muted.TLabel').pack(side='right',padx=6)
            menu_boxes[kind]=box
        mode_box=option_values['menu_style'][0]
        def custom_state(*_):
            enabled=mode_box.current()==list(MODES).index('custom')
            for box in menu_boxes.values():box.configure(state='readonly' if enabled else 'disabled')
        mode_box.bind('<<ComboboxSelected>>',custom_state,add='+');custom_state()
        self._settings_menu_boxes=menu_boxes
        self._settings_option_row=option_row
        self._settings_option_values=option_values
        from .advanced_features import feature_enabled
        push_label = 'macOS push notifications' if sys.platform == 'darwin' else 'Windows push notifications'
        flags['push_notifications'] = tk.BooleanVar(value=feature_enabled(self, 'push_notifications'))
        ttk.Checkbutton(sections['Notifications'], text=tr(push_label), variable=flags['push_notifications'], style='Settings.TCheckbutton').pack(fill='x', pady=6)
        if 'push_notifications' in advanced_flags:
            flags['push_notifications'].trace_add('write', lambda *_: advanced_flags['push_notifications'].set(flags['push_notifications'].get()))
            advanced_flags['push_notifications'].trace_add('write', lambda *_: flags['push_notifications'].set(advanced_flags['push_notifications'].get()))
        from .notification_history import open_history
        from .desktop_contacts import open_contact_sync
        from .desktop_devices import open_devices
        actions={
            'Chats':[('Default reaction',lambda:self.reaction_picker()),('All chats in this app',lambda:self.choose_wallpaper(True))],
            'Notifications':[('Notifications',self.notification_dialog),('Notification history',lambda:open_history(self))],
            'Cuenta':[('Ver mi perfil',self.show_my_profile),('Editar perfil de Telegram',self.edit_profile),('Sync Telegram contacts',self.sync_contacts),('Device contacts',lambda:open_contact_sync(self)),('Privacy',self.privacy_dialog),('Devices',lambda:open_devices(self)),('+ Cuenta',lambda:self.switch_account()),('Log out this account',self.logout_account)],
            'Updates':[('Updates',self.update_dialog),('Quit TeleGraph',self.close)]}
        from .app_lock import open_lock_settings
        actions['Cuenta'].insert(0,('App lock',lambda:open_lock_settings(self)))
        for section,entries in actions.items():
            for label,action in entries:ttk.Button(sections[section],text=tr(label),command=action).pack(fill='x',pady=4)
        for parent,label in [(chats,'Local pins affect only this app. Turning them off restores Telegram order.'),(account,'Las cuentas permanecen conectadas al alternar. Cerrar la app conserva las sesiones.'),(sections['Notifications'],'Quit stops notifications. Closing the window keeps the app running.')]:
            ttk.Label(parent,text=tr(label),wraplength=480).pack(fill='x',pady=10)
        from .official_icons import open_official_icons
        ttk.Button(logos,text=tr('Official Telegram icons'),command=lambda:open_official_icons(self)).pack(fill='x',pady=5)
        from .custom_icon import choose_icon,reset_icon
        ttk.Button(logos,text=tr('Custom app icon'),command=lambda:choose_icon(self)).pack(fill='x',pady=5)
        ttk.Button(logos,text=tr('Restore TeleGraph icon'),command=lambda:reset_icon(self)).pack(fill='x',pady=5)
        self.logo_gallery(logos)
        def save():
            if self.busy:return
            try:
                values={**effects.read_values(),**{k:v.get() for k,v in flags.items()},**{k:v.get() for k,v in colors.items()},**{k:v.get() for k,v in radii.items()},**{k:('dark','light','system')[v.current()] for k,v in choices.items()},'font_size':size.get(),'font_family':families[font_choice.current()-1] if font_choice.current()>0 else ''}
                if not 10<=values['font_size']<=20 or any(not 0<=values[k]<=24 for k in radii):raise ValueError(tr('Value out of range.'))
                name = display_name.get().strip()
                if len(name) > 64 or (name and not name.isprintable()):
                    raise ValueError(tr('Value out of range.'))
                values['app_display_name'] = name
                values['interface_background']=background.get()
                for key,(box,options) in option_values.items():
                    if box.winfo_exists() and box.current()>=0:values[key]=options[box.current()]
                values['menu_custom']={kind:('system' if box.current()==0 else 'app') for kind,box in menu_boxes.items() if box.winfo_exists()}
                if values.get('shortcut_send') and values.get('shortcut_send')==values.get('shortcut_newline'):
                    raise ValueError(tr('Sending and new line need different shortcuts.'))
                values['advanced_features'] = {key: variable.get() for key, variable in advanced_flags.items()}
                values['advanced_features']['push_notifications'] = flags['push_notifications'].get()
                self.preferences.save(values)
                if hasattr(self, 'configure_push_notifications'): self.configure_push_notifications()
            except (ValueError,OSError,tk.TclError) as exc:self.show_error(exc);return
            self.rebuild_screen();self.notebook.select(self.settings_page);self.status.set(tr('Ajustes guardados.'))
        ttk.Button(footer,text=tr('Guardar ajustes'),command=save).pack(fill='x')

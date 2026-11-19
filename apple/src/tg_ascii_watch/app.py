"""TG-ASCII on Wear OS: the mobile app's core (tg_ascii_mobile.core, the
desktop's tg_ascii underneath) with a small native Toga interface for a
round screen. Watches have no WebView, so nothing here uses the web UI.

Screens: sign-in (QR code to scan from Telegram on the phone, or phone
number + code), chat list, and a chat with the latest messages, quick
replies and a text field (keyboard, handwriting or voice on the watch).
"""
import asyncio
import io
import json
import textwrap

import toga
from toga.style import Pack

BG, PANEL, FG, MUTED, STRONG, DANGER = '#08100c', '#0e1b13', '#8cf5a6', '#80a98c', '#bdffcd', '#ff8f8f'
MONO = 'monospace'
PALETTE = {BG: 'bg', PANEL: 'panel', FG: 'text', MUTED: 'muted', STRONG: 'strong'}
TYPEFACES = {'courier': 'monospace', 'sans': 'sans-serif', 'serif': 'serif'}
QUICK = ('👍', '❤', '😂', 'OK', '¿?')
# Round screens: keep everything inside the circle.
SIDE, TOP = 32, 30


def tr(text):
    try:
        from tg_ascii.i18n import tr as translate
        return translate(text)
    except Exception:
        return text


class Events:
    """A core subscriber: events reach the app's (UI) loop."""

    def __init__(self, app):
        self.app = app

    def qsize(self):
        return 0

    def put_nowait(self, data):
        self.app.loop.call_soon_threadsafe(self.app.on_event, json.loads(data))


class TgAsciiWatch(toga.App):
    def startup(self):
        from tg_ascii_mobile.app import data_folder, device_locale
        from tg_ascii_mobile.core import Core
        self.core = Core(data_folder(self.paths.data, 'Android'), 'Wear OS', device_locale())
        self.core.start()
        self.phone_look = None
        self.phone_revision = 0
        self.wear_link_available = False
        self.use_phone_style = True
        self.effective_icon = None
        self.look_path = self.core.root / 'mobile' / 'wear-look.json'
        self.load_wear_look()
        self.core.subscribers.add(Events(self))
        self.stage, self.chats, self.open_peer, self.messages, self.screen = 'loading', [], None, [], None
        self.main_window = toga.MainWindow(title=self.formal_name)
        self.show_note(tr('Conectando...'))
        self.main_window.show()
        self.adapt_chrome()
        self.loop.create_task(self.refresh())

    @property
    def look(self):
        return self.phone_look if self.wear_link_available and self.use_phone_style and self.phone_look else {}

    def colour(self, value):
        if value == STRONG and self.core.prefs and self.core.prefs.values.get('accent_color'):
            return self.core.prefs.values['accent_color']
        return self.look.get(PALETTE.get(value), value)

    def load_wear_look(self):
        from tg_ascii_mobile.wear_sync import decode_appearance

        try:
            stored = self.look_path.read_text('utf-8')
            values = json.loads(stored)
            self.use_phone_style = values.get('enabled') is not False
            decoded = decode_appearance(stored)
            if decoded:
                self.phone_revision, self.phone_look = decoded
        except (AttributeError, OSError, ValueError):
            pass

    def save_wear_look(self):
        self.look_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.look_path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'enabled': self.use_phone_style, 'revision': self.phone_revision,
                                         'appearance': self.phone_look}), encoding='utf-8')
        temporary.replace(self.look_path)

    def apply_wear_look(self):
        from android.graphics import Color

        activity = self._impl.native
        activity.getWindow().getDecorView().setBackgroundColor(Color.parseColor(self.colour(BG)))
        icon = self.look.get('icon') or self.core.appearance()['icon']
        if icon != self.effective_icon and self.core.native_icon is not None:
            self.effective_icon = icon
            self.core.native_icon(icon, lambda ok: self.loop.call_soon_threadsafe(self.icon_applied, icon, ok))
        if self.screen == 'chats':
            self.show_chats()
        elif self.screen == 'chat':
            self.show_chat()
        elif self.screen == 'logos':
            self.show_logos()
        elif self.stage == 'phone':
            self.show_phone()

    def icon_applied(self, icon, ok):
        if not ok and self.effective_icon == icon:
            self.effective_icon = None

    def receive_wear_look(self, result):
        if result and result[0] >= self.phone_revision and result != (self.phone_revision, self.phone_look):
            self.phone_revision, self.phone_look = result
            self.save_wear_look()
            if self.use_phone_style:
                self.apply_wear_look()

    def change_wear_link(self, widget):
        self.use_phone_style = widget.value
        self.save_wear_look()
        self.apply_wear_look()

    # -- plumbing -----------------------------------------------------------------
    async def call(self, method, **params):
        future = asyncio.run_coroutine_threadsafe(self.core.call(method, params), self.core.loop)
        return await asyncio.wrap_future(future)

    def run(self, method, done=None, **params):
        async def task():
            try:
                result = await self.call(method, **params)
            except Exception as exc:
                from tg_ascii.auth import error_message
                self.toast(error_message(exc))
                return
            if done:
                done(result)
        self.loop.create_task(task())

    async def refresh(self):
        for _ in range(100):
            try:
                snapshot = await self.call('state')
                break
            except Exception:
                await asyncio.sleep(0.2)
        else:
            return
        self.stage = snapshot['stage']
        if self.stage == 'choose_account':
            # One account at a time on the watch: open the last one used.
            accounts = snapshot.get('accounts') or []
            current = next((item['key'] for item in accounts if item.get('current')), accounts[0]['key'] if accounts else None)
            if current:
                self.run('choose_account', key=current, ask=True)
            return
        self.route()

    def on_event(self, packet):
        kind, data = packet.get('type'), packet.get('data')
        if kind == 'stage':
            if data['stage'] == 'choose_account':
                self.loop.create_task(self.refresh())
                return
            changed = data['stage'] != self.stage
            self.stage = data['stage']
            if changed or self.stage != 'ready':
                self.route(data.get('error', ''))
        elif kind == 'qr' and self.stage == 'qr':
            self.show_qr(data['url'])
        elif kind == 'chats':
            self.chats = data
            if self.screen == 'chats':
                self.show_chats()
        elif kind == 'chat':
            index = next((i for i, c in enumerate(self.chats) if c['id'] == data['id']), 0)
            self.chats = [chat for chat in self.chats if chat['id'] != data['id']]
            if not data.get('archived'):
                pinned = sum(1 for chat in self.chats if chat.get('pinned'))
                self.chats.insert(index if data.get('pinned') else pinned, data)
            if self.screen == 'chats':
                self.show_chats()
        elif kind == 'message' and self.screen == 'chat' and data['peer'] == self.open_peer:
            if data['message'] and not any(item['id'] == data['message']['id'] for item in self.messages):
                self.messages.append(data['message'])
                self.show_chat()
        elif kind == 'history' and self.screen == 'chat' and data['peer'] == self.open_peer:
            self.messages = data['messages']
            self.show_chat()
        elif kind == 'connection' and self.screen == 'chats':
            self.show_chats()
        elif kind == 'toast':
            self.toast(data.get('text', ''))

    def route(self, error=''):
        if self.stage == 'ready':
            self.run('chats', done=self.got_chats)
        elif self.stage == 'phone':
            self.show_phone(error)
        elif self.stage == 'code':
            self.show_secret('login.code', 'code', tr('Codigo de Telegram'), error)
        elif self.stage == 'password':
            self.show_secret('login.password', 'password', tr('Contraseña de verificacion en dos pasos'), error, password=True)
        elif self.stage == 'signup':
            self.page(self.label(tr('New account'), 15, STRONG),
                      self.label('Telegram (Android / iOS)', 11),
                      self.button(tr('Sign in again'), lambda: self.run('login_back')))
        elif self.stage == 'qr':
            self.show_note(tr('Cargando...'))
        elif self.stage == 'error':
            self.show_note(error or tr('Error'), retry=True)
        else:
            self.show_note(tr('Conectando...'))

    def got_chats(self, chats):
        self.chats = chats
        if self.screen not in ('chat', 'logos'):
            self.show_chats()

    # -- layout helpers --------------------------------------------------------------
    def page(self, *children, scroll=True):
        box = toga.Box(children=list(children),
                       style=Pack(direction='column', background_color=self.colour(BG), margin=(TOP, SIDE, TOP + 10, SIDE)))
        content = toga.ScrollContainer(content=box, horizontal=False, style=Pack(background_color=self.colour(BG), flex=1)) if scroll else box
        self.main_window.content = content
        return box

    def text_style(self, size=11, color=FG, bold=False, **extra):
        look = self.look
        return Pack(color=self.colour(color), background_color=self.colour(BG),
                    font_family=TYPEFACES.get(look.get('font'), MONO),
                    font_size=round(size * look.get('scale', 1)),
                    font_weight='bold' if bold or look.get('bold') else 'normal',
                    font_style='italic' if look.get('italic') else 'normal', **extra)

    def label(self, text, size=11, color=FG, bold=False, **extra):
        # Labels do not wrap by themselves: wrap to the round screen's width
        # (monospace, so characters per line follow from the font size).
        width = max(12, int(250 / (size * self.look.get('scale', 1))))
        wrapped = '\n'.join(textwrap.fill(line, width) if line else '' for line in str(text).split('\n'))
        return toga.Label(wrapped, style=self.text_style(size, color, bold, margin_bottom=4, **extra))

    def button(self, text, action, color=FG, size=11):
        widget = toga.Button(text, on_press=lambda widget: action(),
                             style=self.text_style(size, color, margin_bottom=5))
        widget.style.background_color = self.colour(PANEL)
        try:
            widget._impl.native.setAllCaps(False)  # Material buttons are upper case by default.
        except Exception:
            pass
        return widget

    def toast(self, text):
        if not text:
            return
        try:
            from android.widget import Toast
            Toast.makeText(self._impl.native, str(text), Toast.LENGTH_SHORT).show()
        except Exception:
            print('watch:', text)

    # -- screens -----------------------------------------------------------------------
    def show_note(self, text, retry=False):
        self.screen = 'note'
        children = [self.label('TeleGraph', 13, STRONG, True, text_align='center'), self.label(text, 11, MUTED, text_align='center')]
        if retry:
            children.append(self.button(tr('Reintentar'), lambda: self.run('retry')))
            children.append(self.button(tr('App logos'), self.show_logos))
        self.page(*children)

    def show_phone(self, error=''):
        self.screen = 'login'
        phone = toga.TextInput(placeholder='+34…', style=self.text_style(12, margin_bottom=6))
        children = [self.label('TeleGraph', 13, STRONG, True, text_align='center'),
                    self.button(tr('Entrar con codigo QR'), self.start_qr),
                    self.label(tr('Numero de telefono'), 10, MUTED), phone,
                    self.button(tr('Continuar'), lambda: self.run('login.phone', phone=phone.value.strip())),
                    self.button(tr('App logos'), self.show_logos),
                    self.button(tr('Accent color'), self.show_accents)]
        if error:
            children.insert(1, self.label(error, 10, DANGER))
        self.page(*children)

    def show_secret(self, method, field, title, error='', password=False):
        self.screen = 'login'
        widget = (toga.PasswordInput if password else toga.TextInput)(style=self.text_style(12, margin_bottom=6))
        children = [self.label(title, 11, STRONG, True), widget,
                    self.button(tr('Continuar'), lambda: self.run(method, **{field: widget.value.strip()}))]
        if error:
            children.insert(1, self.label(error, 10, DANGER))
        self.page(*children)

    def start_qr(self):
        # The page keeps the 'qr' stage itself; so does the watch.
        self.stage = 'qr'
        self.show_note(tr('Cargando...'))
        self.run('login.qr')

    def show_qr(self, url):
        import qrcode
        self.screen = 'login'
        picture = qrcode.make(url, border=2, box_size=6).convert('RGB')
        data = io.BytesIO()
        picture.save(data, format='PNG')
        image = toga.ImageView(toga.Image(data.getvalue()), style=Pack(width=150, height=150, margin_bottom=6))
        def cancel():
            self.stage = 'phone'
            self.run('login.qr_cancel', done=lambda _: self.route())
        self.page(image, self.label(tr('Escanea este codigo desde Telegram en otro dispositivo: Ajustes > Dispositivos > Vincular dispositivo.'), 9, MUTED),
                  self.button(tr('Volver'), cancel))

    def close_logos(self):
        if self.stage == 'ready':
            self.show_chats()
        else:
            self.route()

    def show_chats(self):
        self.screen = 'chats'
        offline = self.core.connection in ('offline', 'reconnecting')
        from tg_ascii.logos import png_bytes
        look = self.look.get('brand_logo') or self.core.appearance()['brand_logo']
        logo = toga.Image(png_bytes(look['variant'], look['theme'], 128, color=look['color']))
        logo_row = toga.Box(children=[toga.ImageView(logo, style=Pack(width=64, height=64))],
                            style=Pack(direction='row', justify_content='center'))
        children = [logo_row,
                    self.label('TeleGraph' + ('  ○' if offline else ''), 13, STRONG, True, text_align='center'),
                    self.button(tr('App logos'), self.show_logos),
                    self.button(tr('Accent color'), self.show_accents)]
        if not self.chats:
            children.append(self.label(tr('Cargando...') if not offline else tr('Sin conexion'), 10, MUTED, text_align='center'))
        for chat in self.chats[:40]:
            unread = chat.get('unread') or ('•' if chat.get('unread_mark') else '')
            title = chat['name'][:26] + (f'  [{unread}]' if unread else '')
            children.append(self.button(title, lambda chat=chat: self.open_chat(chat), color=STRONG if unread else FG))
        self.page(*children)

    def show_accents(self):
        choices = [('Default', ''), ('Blue', '#58aaff'), ('Orange', '#ffb347'), ('Pink', '#ff9ad5'), ('Red', '#ff7777')]
        self.page(self.label(tr('Accent color'), 13, STRONG),
                  *[self.button(tr(label), lambda value=value: self.run('settings', values={'accent_color': value},
                              done=lambda _: self.show_chats())) for label, value in choices])

    def show_logos(self, appearance=None):
        from tg_ascii.logos import LOGO_PALETTES, VARIANTS, png_bytes
        self.screen = 'logos'
        appearance = appearance or self.core.appearance()
        selected = self.look.get('brand_logo') or appearance['brand_logo']
        variants = {label: key for key, label in VARIANTS.items()}
        color_labels = {'default': tr('Default'), 'light': tr('Light'), 'orange': tr('Orange'),
                        'blue': tr('Blue'), 'red': tr('Red'), 'pink': tr('Pink'), 'monochrome': tr('Monochrome')}
        colors = {label: key for key, label in color_labels.items() if key in LOGO_PALETTES}
        themes = {tr('Dark'): 'dark', tr('Light'): 'light'}
        variant = toga.Selection(items=list(variants), value=VARIANTS[selected['variant']])
        color = toga.Selection(items=list(colors), value=color_labels[selected['color']])
        theme = toga.Selection(items=list(themes), value=next(label for label, key in themes.items() if key == selected['theme']))
        preview = toga.ImageView(style=Pack(width=76, height=76))
        preview_row = toga.Box(children=[preview], style=Pack(direction='row', justify_content='center'))

        def chosen():
            return {'variant': variants[variant.value], 'color': colors[color.value], 'theme': themes[theme.value]}

        def draw(_widget=None):
            current = chosen()
            preview.image = toga.Image(png_bytes(current['variant'], current['theme'], 128, color=current['color']))

        for control in (variant, color, theme):
            control.on_change = draw
        draw()
        def refresh(value):
            self.effective_icon = value['icon']
            if self.screen == 'logos':
                self.show_logos(value)

        controls = [self.button('< ' + tr('Volver'), self.close_logos)]
        if self.wear_link_available:
            controls.append(toga.Switch(tr('Use phone appearance'), value=self.use_phone_style,
                                        on_change=self.change_wear_link, style=self.text_style()))
        if self.wear_link_available and self.use_phone_style:
            controls.append(preview_row)
            if self.phone_look is None:
                controls.append(self.label(tr('Waiting for phone appearance…'), 10, MUTED))
        else:
            controls.extend([
                variant, color, theme, preview_row,
                self.button(tr('Apply'), lambda: self.run('appearance', done=refresh, values={'brand_logo': chosen(), 'apply_native_logo': True})),
            ])
        self.page(*controls)

    def open_chat(self, chat):
        self.open_peer, self.open_name, self.messages = chat['id'], chat['name'], []
        self.open_kind = chat.get('kind')
        self.chat_draft, self.translations = '', {}
        self.translating = False
        self.show_chat()

        def opened(data):
            if self.open_peer == chat['id']:
                if data.get('chat') and data['chat'].get('kind'):
                    self.open_kind = data['chat']['kind']
                self.messages = data.get('messages') or []
                self.show_chat()
        self.run('open', done=opened, peer=chat['id'])

    def message_text(self, message):
        if message.get('service'):
            return message.get('text') or ''
        text = (message.get('caption') if message.get('visual') else message.get('text')) or ''
        if message.get('visual'):
            kind = {'photo': tr('Foto'), 'image': tr('Foto'), 'video': tr('Vídeo'), 'sticker': 'Sticker'}.get(message.get('kind'), message.get('kind') or '')
            text = f'[{kind}] {text}'.strip()
        return text

    def show_chat(self, scroll_to_latest=True):
        position = getattr(self.main_window.content, 'vertical_position', 0)
        self.screen = 'chat'

        def save_draft(widget):
            self.chat_draft = widget.value or ''

        field = toga.TextInput(value=self.chat_draft, placeholder=tr('Escribe un mensaje'),
                               on_change=save_draft, style=self.text_style(11, margin_bottom=5))

        def send(text):
            text = (text or '').strip()
            if text:
                self.run('send', peer=self.open_peer, text=text)
                self.chat_draft = field.value = ''
        is_secret = getattr(self, 'open_kind', None) == 'secret'
        children = [self.button('< ' + self.open_name[:22], self.close_chat, color=STRONG)]
        chat = next((c for c in self.chats if c['id'] == self.open_peer), {})
        if chat.get('pinned') and not is_secret:
            for direction, label in [(-1, 'Move pin up'), (1, 'Move pin down')]:
                children.append(self.button(tr(label), lambda step=direction: self.run(
                    'move_pin', peer=self.open_peer, direction=step, account=self.core.account)))
        if is_secret:
            children.append(self.button('🔒 ' + tr('Clave de cifrado y autodestrucción'), self.show_secret_info, color=MUTED, size=10))
        elif getattr(self, 'open_kind', None) == 'user':
            children.append(self.button('🔒 ' + tr('Iniciar chat secreto'), self.start_secret_chat, color=MUTED, size=10))
        if not self.messages:
            children.append(self.label(tr('Cargando...'), 10, MUTED))
        translatable = []
        for message in self.messages[-20:]:
            ident = str(message['id'])
            who = tr('Tu') if message.get('out') else (message.get('sender') or '')
            header = self.label(f"{who} · {message.get('time', '')}", 9, MUTED)
            body = self.label(self.translations.get(ident) or self.message_text(message),
                              11, STRONG if message.get('out') else FG)
            if self.look.get('bubbles'):
                background = self.colour(PANEL)
                header.style.background_color = body.style.background_color = background
                children.append(toga.Box(children=[header, body], style=Pack(
                    direction='column', background_color=background, padding=4, margin_bottom=4)))
            else:
                children.extend([header, body])
            if not is_secret and not message.get('service') and message.get('translatable'):
                translatable.append(message['id'])
                label = tr('Show original') if ident in self.translations else tr('Translate')
                children.append(self.button(label, lambda ident=ident: self.toggle_translation(ident), color=MUTED))
        if translatable and not is_secret:
            children.append(self.button(tr('Translate chat'), lambda: self.translate_chat(translatable, chat=True)))
        rows = [toga.Box(children=[self.button(item, lambda item=item: send(item), size=12) for item in QUICK[index:index + 2]],
                         style=Pack(direction='row', background_color=self.colour(BG))) for index in range(0, len(QUICK), 2)]
        children += [*rows, field, self.button(tr('Enviar'), lambda: send(field.value))]
        box = self.page(*children)
        # Newest messages at the bottom: scroll there once laid out.
        content = self.main_window.content

        def to_bottom():
            try:
                content.vertical_position = content.max_vertical_position if scroll_to_latest else position
            except Exception:
                pass
        self.loop.call_later(0.25, to_bottom)
        self.loop.call_later(0.8, to_bottom)
        return box

    def toggle_translation(self, ident):
        if ident in self.translations:
            self.translations.pop(ident)
            self.show_chat(scroll_to_latest=False)
        else:
            self.translate_chat([int(ident)])

    def translate_chat(self, ids, chat=False):
        if self.translating or self.open_peer is None:
            return
        self.translating = True
        peer = self.open_peer
        translations = self.translations

        async def translate():
            try:
                values = await self.call('watch', request={'op': 'translate', 'peer': peer, 'ids': ids, 'chat': chat})
                if self.open_peer == peer and self.translations is translations:
                    if values.get('error'):
                        self.toast(values['error'])
                    elif values:
                        translations.update(values)
                        self.show_chat(scroll_to_latest=False)
                    else:
                        self.toast(tr('Sin resultados.'))
            except Exception as exc:
                from tg_ascii.auth import error_message
                if self.translations is translations:
                    self.toast(error_message(exc))
            finally:
                if self.translations is translations:
                    self.translating = False

        self.loop.create_task(translate())

    def start_secret_chat(self):
        if self.open_peer is None:
            return
        self.toast(tr('Iniciando chat secreto cifrado de extremo a extremo...'))
        self.run('secret_start', done=lambda chat: self.open_chat(chat) if chat and chat.get('id') else None, peer=self.open_peer)

    def show_secret_info(self):
        if self.open_peer is None:
            return
        peer = self.open_peer

        def render_info(info):
            if self.open_peer != peer or not info:
                return
            self.screen = 'secret_info'
            emojis = '  '.join(info.get('fingerprint_emojis') or ()) or '🔒'
            ttl_val = int(info.get('ttl') or 0)
            children = [
                self.button('< ' + self.open_name[:20], lambda: self.show_chat(scroll_to_latest=False), color=STRONG),
                self.label(emojis, 15, STRONG, True, text_align='center'),
                self.label(info.get('fingerprint_hex') or '', 9, MUTED, text_align='center'),
                self.label(f"{tr('Capa MTProto:')} {info.get('layer', 144)} · TTL: {ttl_val}s", 9, MUTED, text_align='center'),
            ]
            for sec, lbl in ((0, tr('Desactivado')), (5, '5s'), (30, '30s'), (60, '1m'), (3600, '1h')):
                children.append(self.button(
                    ('✓ ' if ttl_val == sec else '') + f'TTL {lbl}',
                    lambda sec=sec: self.run('secret_ttl', done=render_info, peer=peer, seconds=sec),
                    color=STRONG if ttl_val == sec else FG, size=10))
            children.append(self.button(
                tr('Rotar clave ahora (PFS)'),
                lambda: self.run('secret_rekey', done=render_info, peer=peer), size=10))
            children.append(self.button(
                tr('Cerrar chat secreto'),
                lambda: self.run('secret_discard', done=lambda _: self.close_chat(), peer=peer, delete_history=True),
                color=DANGER, size=10))
            self.page(*children)

        self.run('secret_info', done=render_info, peer=peer)

    def close_chat(self):
        if self.open_peer is not None:
            self.run('close', peer=self.open_peer)
        self.open_peer = None
        self.show_chats()

    # -- Android chrome and the back gesture (swipe right on Wear OS) --------------------------
    def adapt_chrome(self):
        try:
            activity = self._impl.native
            bar = activity.getSupportActionBar()
            if bar is not None:
                bar.hide()
            from android.graphics import Color
            window = activity.getWindow()
            window.getDecorView().setBackgroundColor(Color.parseColor(BG))
            from tg_ascii_mobile.app import TgAsciiMobile
            TgAsciiMobile.install_icon_switcher(self, activity)
            self.install_back(activity)
            from tg_ascii_mobile.wear_sync import PACKAGE, watch_listener
            if activity.getPackageName() == PACKAGE:
                start, stop = watch_listener(self, activity, self.receive_wear_look)
                self.wear_link_available = True
                self.main_window.on_show = start
                self.main_window.on_hide = stop
                self.apply_wear_look()
                start()
        except Exception as exc:
            print('watch chrome:', exc)

    def install_back(self, activity):
        try:
            from java import dynamic_proxy
            from android.window import OnBackInvokedCallback, OnBackInvokedDispatcher
        except ImportError:
            return
        app = self

        class Back(dynamic_proxy(OnBackInvokedCallback)):
            def onBackInvoked(self):
                def go_back():
                    if app.screen == 'secret_info':
                        app.show_chat(scroll_to_latest=False)
                    elif app.screen == 'chat':
                        app.close_chat()
                    elif app.screen == 'logos':
                        app.close_logos()
                    elif app.stage == 'qr':
                        app.stage = 'phone'
                        app.run('login.qr_cancel', done=lambda _: app.route())
                    else:
                        activity.moveTaskToBack(True)
                app.loop.call_soon(go_back)
        self._back = Back()
        activity.getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
            OnBackInvokedDispatcher.PRIORITY_DEFAULT, self._back)


def main():
    return TgAsciiWatch('TeleGraph Watch', 'org.tgas.tg_ascii_watch')

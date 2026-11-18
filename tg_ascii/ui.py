from .i18n import tr
from prompt_toolkit import Application
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea

from . import APP_NAME, __version__
from .auth import error_message
from .backend import display, single_line


class Terminal:
    def __init__(self, backend):
        self.backend = backend
        self.chats = []
        self.selected = 0
        self.active = None
        self.messages = []
        self.drafts = {}
        self.status = tr('Cargando chats...')
        self.busy = False
        self.history = TextArea(read_only=True, focusable=False, wrap_lines=True)
        self.history.buffer.set_document(Document(tr('Elige un chat con las flechas y pulsa Enter.\n\nTab: cambiar de panel\nEsc: volver a los chats\nF5: actualizar lista\nPgUp/PgDn: historial\nCtrl-Q: salir')), bypass_readonly=True)
        self.editor = TextArea(height=1, prompt='> ', multiline=False,
                               read_only=Condition(lambda: self.busy), accept_handler=self.submit)
        self.chat_control = FormattedTextControl(self.sidebar, focusable=True, show_cursor=False,
                                                 get_cursor_position=lambda: Point(x=0, y=self.selected))
        self.chat_window = Window(self.chat_control, width=Dimension(min=20, preferred=30, max=38),
                                  wrap_lines=False, always_hide_cursor=True)
        keys = KeyBindings()
        list_focus = has_focus(self.chat_control)

        @keys.add('c-q')
        @keys.add('c-c')
        def quit(event):
            event.app.exit()

        @keys.add('tab')
        @keys.add('s-tab')
        def switch(event):
            target = self.editor if event.app.layout.has_focus(self.chat_control) else self.chat_control
            event.app.layout.focus(target)

        @keys.add('escape')
        def back(event):
            event.app.layout.focus(self.chat_control)

        @keys.add('up', filter=list_focus)
        def previous(event):
            self.selected = max(0, self.selected - 1)

        @keys.add('down', filter=list_focus)
        def following(event):
            self.selected = min(max(0, len(self.chats) - 1), self.selected + 1)

        @keys.add('home', filter=list_focus)
        def first(event):
            self.selected = 0

        @keys.add('end', filter=list_focus)
        def last(event):
            self.selected = max(0, len(self.chats) - 1)

        @keys.add('enter', filter=list_focus)
        def open_selected(event):
            index = self.selected
            self.start_action(lambda: self.open_chat(index))

        @keys.add('f5')
        def refresh(event):
            self.start_action(self.refresh_chats)

        @keys.add('pageup')
        def history_up(event):
            if event.app.layout.has_focus(self.chat_control):
                self.selected = max(0, self.selected - 10)
            else:
                self.history.buffer.cursor_up(count=10)

        @keys.add('pagedown')
        def history_down(event):
            if event.app.layout.has_focus(self.chat_control):
                self.selected = min(max(0, len(self.chats) - 1), self.selected + 10)
            else:
                self.history.buffer.cursor_down(count=10)

        root = HSplit([
            Window(FormattedTextControl(self.header), height=1, style='class:header'),
            Window(height=1, char='-'),
            VSplit([self.chat_window, Window(width=1, char='|'),
                    HSplit([Window(FormattedTextControl(self.chat_title), height=1, style='class:title'),
                            self.history])]),
            Window(height=1, char='-'),
            Window(FormattedTextControl(lambda: single_line(self.status)), height=1, style='class:status'),
            self.editor,
            Window(FormattedTextControl(tr(' Tab: panel | Esc: chats | Enter: abrir/enviar | F5: actualizar | Ctrl-Q: salir')), height=1, style='class:hint')
        ])
        self.app = Application(layout=Layout(root, focused_element=self.chat_control), key_bindings=keys,
                               style=Style.from_dict({
                                   '': 'bg:#000000 #66ff66',
                                   'text-area': 'bg:#000000 #66ff66',
                                   'header': 'bg:#66ff66 #000000 bold',
                                   'selected': 'bg:#174d24 #aaffaa bold',
                                   'active': 'bold', 'title': 'bold',
                                   'hint': '#58a86b', 'status': '#a0e8a0'
                               }), full_screen=True, mouse_support=False)
        backend.callback = self.incoming

    def header(self):
        mode = tr('DEMO LOCAL') if self.backend.demo else 'TELEGRAM'
        return f' {APP_NAME} {__version__} | {mode} | {len(self.chats)} chats'

    def chat_title(self):
        name = next((c.name for c in self.chats if c.id == self.active), tr('Ningun chat abierto'))
        return ' ' + single_line(name)

    def sidebar(self):
        if not self.chats:
            return [('class:hint', tr(' Sin chats. F5: actualizar'))]
        width = self.chat_window.render_info.window_width if self.chat_window.render_info else 30
        lines = []
        for index, chat in enumerate(self.chats):
            prefix = f'{">" if chat.id == self.active else " "}{index + 1:3} '
            badge = f' [{min(chat.unread, 999)}]' if chat.unread else ''
            available = max(1, width - len(prefix) - len(badge) - 1)
            name = single_line(chat.name)
            if len(name) > available:
                name = name[:max(0, available - 1)] + '~'
            row = (prefix + name.ljust(available) + badge).ljust(max(1, width - 1))
            style = 'class:selected' if index == self.selected else 'class:active' if chat.id == self.active else ''
            lines.append((style, row))
            if index != len(self.chats) - 1:
                lines.append(('', '\n'))
        return lines

    def render(self, follow=True):
        old_position = self.history.buffer.cursor_position
        text = '\n\n'.join(f'[{m.time}] {single_line(m.sender)}: {display(m.text)}' for m in self.messages)
        if not text:
            text = tr('No hay mensajes en este chat.')
        cursor = len(text) if follow else min(old_position, len(text))
        self.history.buffer.set_document(Document(text, cursor), bypass_readonly=True)
        self.app.invalidate()

    def incoming(self, chat_id, message):
        duplicate = chat_id == self.active and any(m.id == message.id for m in self.messages)
        if not message.outgoing and not duplicate:
            for chat in self.chats:
                if chat.id == chat_id:
                    chat.unread += 1
                    break
        if chat_id == self.active:
            self.merge(message)
        self.app.invalidate()

    def merge(self, message):
        if not any(m.id == message.id for m in self.messages):
            follow = self.history.buffer.cursor_position == len(self.history.text)
            self.messages.append(message)
            self.messages = sorted(self.messages, key=lambda m: m.id)[-200:]
            self.render(follow=follow)

    async def refresh_chats(self):
        selected_id = self.chats[self.selected].id if self.chats else None
        chats = await self.backend.chats()
        self.chats = chats
        self.selected = next((i for i, c in enumerate(chats) if c.id == selected_id), 0)
        self.status = tr('Flechas: elegir chat. Enter: abrir. Tab: escribir comandos.')

    async def open_chat(self, index, command=None):
        if not 0 <= index < len(self.chats):
            raise ValueError(tr('Elige un chat de la lista.'))
        chat = self.chats[index]
        if chat.id == self.active:
            self.selected = index
            if command is not None and self.editor.text == command:
                self.editor.text = self.drafts.get(chat.id, '')
            self.app.layout.focus(self.editor)
            return
        old_id, old_messages = self.active, self.messages
        old_draft = '' if command is not None and self.editor.text == command else self.editor.text
        self.status = tr('Cargando ') + single_line(chat.name) + '...'
        self.active, self.messages = chat.id, []
        self.app.invalidate()
        try:
            history = await self.backend.history(chat.id)
        except BaseException:
            self.active, self.messages = old_id, old_messages
            raise
        if old_id is not None:
            self.drafts[old_id] = old_draft
        merged = {m.id: m for m in history + self.messages}
        self.messages = sorted(merged.values(), key=lambda m: m.id)[-200:]
        self.selected = index
        self.editor.text = self.drafts.get(chat.id, '')
        self.render()
        self.status = tr('Chat abierto. Enter envia al chat indicado arriba. Esc: lista.')
        self.app.layout.focus(self.editor)

    def start_action(self, operation):
        if self.busy:
            self.status = tr('Hay una operacion en curso. Espera un momento.')
            return
        self.busy = True
        self.app.create_background_task(self.perform(operation))

    async def perform(self, operation):
        self.busy = True
        try:
            await operation()
        except Exception as exc:
            self.status = error_message(exc)
        finally:
            self.busy = False
            self.app.invalidate()

    def submit(self, buffer):
        text = buffer.text
        if text.strip():
            self.start_action(lambda: self.dispatch(text))
        return True  # Keep the draft until the server confirms success.

    async def dispatch(self, text):
        if text == '/quit':
            self.app.exit()
        elif text == '/chats':
            await self.refresh_chats()
        elif text.startswith('/open '):
            try:
                index = int(text.split(maxsplit=1)[1]) - 1
            except ValueError:
                raise ValueError(tr('Usa /open seguido del numero del chat.')) from None
            await self.open_chat(index, command=text)
            return
        elif text == '/help':
            self.status = tr('/open N | /chats | /quit | //texto para enviar /texto | Tab: panel')
        elif text.startswith('/') and not text.startswith('//'):
            raise ValueError(tr('Comando desconocido. /help para ayuda; // para enviar una barra inicial.'))
        elif self.active is None:
            raise ValueError(tr('Primero elige un chat con las flechas y Enter.'))
        else:
            body = text[1:] if text.startswith('//') else text
            if len(body.encode('utf-16-le')) // 2 > 4096:
                raise ValueError(tr('Mensaje demasiado largo para Telegram (4096 unidades UTF-16).'))
            chat_id = self.active
            self.status = tr('Enviando...')
            self.app.invalidate()
            try:
                sent = await self.backend.send(chat_id, body)
            except Exception as exc:
                self.status = error_message(exc) + tr(' Borrador conservado; revisa el chat antes de reintentar.')
                return
            if self.active == chat_id:
                self.merge(sent)
            self.drafts.pop(chat_id, None)
            self.status = tr('Enviado.')
        if self.editor.text == text:
            self.editor.text = ''

    async def run(self):
        await self.app.run_async(pre_run=lambda: self.start_action(self.refresh_chats))

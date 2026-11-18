import asyncio
import unittest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from tg_ascii.backend import Chat, DemoBackend, Message
from tg_ascii.ui import Terminal


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate(): await asyncio.sleep(0.01)


class UITests(unittest.IsolatedAsyncioTestCase):
    async def test_keyboard_navigation_drafts_and_send(self):
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            backend = DemoBackend()
            ui = Terminal(backend)
            task = asyncio.create_task(ui.run())
            try:
                await until(lambda: len(ui.chats) == 3 and not ui.busy)
                pipe.send_bytes(b'\x1b[B\r')
                await until(lambda: ui.active == 2 and not ui.busy)
                pipe.send_text('Borrador con tilde: qué')
                await until(lambda: ui.editor.text.endswith('qué'))
                pipe.send_bytes(b'\t\x1b[B\r')
                await until(lambda: ui.active == 3 and not ui.busy)
                self.assertEqual(ui.editor.text, '')
                pipe.send_text('Otro borrador')
                await until(lambda: ui.editor.text == 'Otro borrador')
                pipe.send_bytes(b'\t\x1b[A\r')
                await until(lambda: ui.active == 2 and not ui.busy)
                self.assertEqual(ui.editor.text, 'Borrador con tilde: qué')
                pipe.send_text('\r')
                await until(lambda: ui.editor.text == '' and not ui.busy)
                self.assertEqual(backend.messages[2][-1].text, 'Borrador con tilde: qué')
                self.assertEqual(ui.drafts[3], 'Otro borrador')
            finally:
                pipe.send_bytes(b'\x11')
                await asyncio.wait_for(task, 3)

    async def test_failed_send_keeps_draft_and_failed_open_rolls_back(self):
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            backend = DemoBackend()
            ui = Terminal(backend)
            await ui.refresh_chats()
            await ui.open_chat(0)
            ui.editor.text = 'No perder'
            async def fail(*_): raise ConnectionError('offline')
            backend.send = fail
            await ui.perform(lambda: ui.dispatch(ui.editor.text))
            self.assertEqual(ui.editor.text, 'No perder')
            self.assertIn('Borrador conservado', ui.status)
            old = list(ui.messages)
            backend.history = fail
            await ui.perform(lambda: ui.open_chat(1))
            self.assertEqual(ui.active, 1)
            self.assertEqual(ui.messages, old)
            self.assertEqual(ui.editor.text, 'No perder')

    async def test_update_during_history_fetch_is_not_duplicated(self):
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            backend = DemoBackend()
            ui = Terminal(backend)
            await ui.refresh_chats()
            live = Message(9, 'Alex', 'Llegada en vivo', '12:20')
            async def history(_):
                ui.incoming(1, live)
                return [backend.messages[1][0], live]
            backend.history = history
            await ui.open_chat(0)
            ui.incoming(1, live)
            self.assertEqual([m.id for m in ui.messages], [1, 9])

    async def test_long_chat_list_scrolls(self):
        class ManyChats(DemoBackend):
            async def chats(self): return [Chat(i, f'Chat {i}') for i in range(1, 101)]
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            ui = Terminal(ManyChats())
            task = asyncio.create_task(ui.run())
            try:
                await until(lambda: len(ui.chats) == 100 and not ui.busy)
                pipe.send_bytes(b'\x1b[F')
                await until(lambda: ui.selected == 99)
                await until(lambda: ui.chat_window.render_info is not None and ui.chat_window.vertical_scroll > 0)
                self.assertGreater(ui.chat_window.vertical_scroll, 0)
            finally:
                pipe.send_bytes(b'\x11')
                await asyncio.wait_for(task, 3)

    async def test_busy_navigation_does_not_change_send_recipient(self):
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            backend = DemoBackend()
            gate = asyncio.Event()
            original = backend.send
            async def delayed(chat_id, text):
                await gate.wait()
                return await original(chat_id, text)
            backend.send = delayed
            ui = Terminal(backend)
            task = asyncio.create_task(ui.run())
            try:
                await until(lambda: bool(ui.chats) and not ui.busy)
                pipe.send_text('\r')
                await until(lambda: ui.active == 1 and not ui.busy)
                pipe.send_text('Destino uno\r')
                await until(lambda: ui.busy)
                pipe.send_bytes(b'\t\x1b[B\r')
                await until(lambda: ui.selected == 1)
                self.assertEqual(ui.active, 1)
                gate.set()
                await until(lambda: not ui.busy)
                self.assertEqual(backend.messages[1][-1].text, 'Destino uno')
                self.assertNotEqual(backend.messages[2][-1].text, 'Destino uno')
            finally:
                gate.set()
                pipe.send_bytes(b'\x11')
                await asyncio.wait_for(task, 3)

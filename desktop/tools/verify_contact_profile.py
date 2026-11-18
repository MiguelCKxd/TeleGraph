"""Native profile/avatar QA with synthetic data and no Telegram connection.

Run on a graphical desktop:
  python tools/verify_contact_profile.py --output result.json --screenshot card.png
All input images and cache files live in a disposable temporary directory.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
from types import MethodType, SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

from PIL import Image, ImageGrab
from telethon import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tg_ascii.backend import Message
from tg_ascii.contact_profile import ContactProfile
from tg_ascii.desktop import AsyncWorker
from tg_ascii.desktop_features import DesktopFeatures
from tg_ascii.desktop_plus import DesktopPlus
from tg_ascii.desktop_profile import DesktopProfile
from tg_ascii.preferences import DEFAULTS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    result = {'success': False, 'platform': sys.platform, 'synthetic_only': True}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='tg-profile-native-') as directory:
        root = tk.Tk()
        root.geometry('900x650')
        root.title('Synthetic profile verification')
        errors = []
        root.report_callback_exception = lambda kind, error, trace: errors.append(str(error))
        worker = AsyncWorker()
        media_calls, downloads = [], []
        pending, cancelled = threading.Event(), threading.Event()
        stall_original = [False]
        profile = dict(
            id=77, kind='user', is_user=True, name='Synthetic contact — Profile test',
            first_name='Synthetic', last_name='Contact', username='synthetic_contact',
            usernames=['synthetic_contact'], phone='',
            about='Synthetic profile used only to verify the interface.\nNo real account is connected.',
            activity='Synthetic status', premium=True, verified=True, contact=True,
            profile_color=NS(color=1, background_emoji_id=None), common_chats_count=3,
            full_photo_known=True, display_photo=types.Photo(19,0,b'',None,[],1), photo_id=19)
        backend = NS(profile=AsyncMock(side_effect=lambda peer: dict(profile)),
                     profile_palette=AsyncMock(return_value=[0x13596e, 0x263957]),
                     account_profile=NS(user_id=None), local_profile_design={},
                     client=NS(get_profile_photos=AsyncMock(return_value=[types.Photo(19,0,b'',None,[],1)])))

        async def search(peer, query, kind, offset):
            media_calls.append([peer, kind, offset])
            return [] if kind == 'photos' else [Message(
                1, 'Synthetic', 'https://example.org' if kind == 'links' else 'Test file',
                '12:00', filename='Example.txt')]

        async def download(photo, path, thumbnail=False):
            downloads.append({'thumbnail': thumbnail, 'name': path.name})
            if not thumbnail and stall_original[0]:
                pending.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            image = Image.new('RGB', (320, 240) if thumbnail else (1200, 900), '#4d99a5')
            try:
                image.save(path)
            finally:
                image.close()
            return path

        backend.search_messages = search
        backend.download_media = download
        values = {**DEFAULTS, 'theme': 'dark', 'font_size': 12,'advanced_features':{'links':True}}
        app = NS(root=root, worker=worker, demo=False, ui_account='synthetic', active=99,
                 service=NS(backend=backend), preferences=NS(values=values), font_family='Arial',
                 popups=[], busy=False, preview_dir=Path(directory), preview_slots=None,
                 preview_cache={}, preview_pending=set(), preview_failed=set(),
                 profile_notifications=Mock(), profile_people=Mock(), profile_permissions=Mock(),
                 chat_history_action=Mock(), open_link=Mock(), edit_contact=Mock(),
                 add_username_contact=Mock(), full_profile_photo=Mock(), emoji_art=Mock(),
                 show_error=lambda error: errors.append(str(error)), open_image_message=Mock(),
                 view_message_media=Mock(), jump_message=Mock())
        app.dialog = MethodType(DesktopFeatures.dialog, app)
        app.extend_profile = MethodType(DesktopProfile.extend_profile, app)
        app.request_photo = MethodType(DesktopPlus.request_photo, app)
        app.start_photo_requests = MethodType(DesktopPlus.start_photo_requests, app)
        app.text_display = lambda value, one_line=False: str(value).replace('\n', ' ') if one_line else str(value)

        def pump(condition, seconds=10):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                root.update()
                while not worker.events.empty():
                    callback, value = worker.events.get_nowait()
                    callback(value)
                if errors:
                    raise AssertionError(errors)
                if condition():
                    return
                time.sleep(.005)
            raise AssertionError('Native profile check timed out')

        def click_avatar(view):
            a, b, c, d = view.avatar_bounds
            view.banner.event_generate('<ButtonRelease-1>', x=round((a+c)/2), y=round((b+d)/2))

        view = None
        try:
            view = ContactProfile(app, 77)
            pump(lambda: view.profile is not None and view.avatar is not None and hasattr(view, 'avatar_bounds'))
            assert not media_calls and not app.busy
            assert len(downloads) == 1 and downloads[0]['thumbnail']
            assert downloads[0]['name'].endswith('-thumb.jpg')
            app.full_profile_photo.assert_not_called()
            result['initial_thumbnail_only'] = True
            for width in (420, 620, 900):
                view.window.geometry(f'{width}x740')
                pump(lambda: abs(view.window.winfo_width()-width) < 3)
                until = time.monotonic()+.1
                pump(lambda: time.monotonic() >= until)
                assert 'settings' in view.pages and view.banner.winfo_width() <= width
                assert view.banner.bbox('all')[2] <= view.banner.winfo_width()+5
            result['responsive_widths'] = [420, 620, 900]
            click_avatar(view)
            gallery=view.avatar_gallery
            pump(lambda: gallery.path is not None and not gallery.requests.jobs)
            original=gallery.path
            assert len(downloads) == 2 and not downloads[-1]['thumbnail']
            assert original != view.avatar_path
            with Image.open(original) as image:
                assert image.size == (1200, 900)
            click_avatar(view)
            root.update()
            assert view.avatar_gallery is gallery and len(downloads) == 2
            gallery.window.destroy()
            result.update(original_on_click=True, original_cache_reused=True, repeated_click_reuses_gallery=True)
            for kind, expected in (('files', 1), ('links', 2), ('photos', 3)):
                view.select(kind)
                pump(lambda: len(media_calls) == expected)
            view.select('files')
            root.update()
            assert len(media_calls) == 3
            result['lazy_media_calls'] = media_calls
            view.select('info')
            view.window.geometry('620x740')
            pump(lambda: view.window.winfo_width() == 620)
            until = time.monotonic()+.2
            pump(lambda: time.monotonic() >= until)
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                x, y = view.window.winfo_rootx(), view.window.winfo_rooty()
                image = ImageGrab.grab(bbox=(x, y, x+view.window.winfo_width(), y+view.window.winfo_height()))
                try:
                    image.save(args.screenshot)
                finally:
                    image.close()
                result['screenshot'] = str(args.screenshot)
            profile.update(display_photo=types.Photo(20,0,b'',None,[],1), photo_id=20)
            stall_original[0] = True
            view.refresh()
            pump(lambda: view.avatar is not None and view.avatar_path.name.endswith('-20-thumb.jpg'))
            click_avatar(view)
            pump(pending.is_set)
            count = len(downloads)
            click_avatar(view)
            root.update()
            assert len(downloads) == count
            view.avatar_gallery.window.destroy()
            pump(cancelled.is_set)
            view.window.destroy()
            assert view.requests.closed and not view.requests.jobs
            app.full_profile_photo.assert_not_called()
            result.update(pending_click_coalesced=True, close_cancels_original=True,
                          settings_preserved=True, global_busy_unchanged=not app.busy, success=True)
        except Exception as error:  # noqa: BLE001 -- report and close the isolated test application
            result.update(error=type(error).__name__, detail=str(error))
        finally:
            for window in app.popups:
                if window.winfo_exists():
                    window.destroy()
            if hasattr(app, 'animation_player'):
                app.animation_player.stop()
            worker.stop()
            root.destroy()
            worker.thread.join(3)
            result.update(callback_errors=errors, closed_cleanly=not worker.thread.is_alive())
            if errors or worker.thread.is_alive():
                result['success'] = False
    result['wall_seconds'] = round(time.monotonic()-started, 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

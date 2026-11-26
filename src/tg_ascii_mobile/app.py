"""Toga shell: one full-screen WebView showing the TG-ASCII interface.

The interface is served by the core's local server (see server.py); this
module only creates the window, starts the core and adapts the native
chrome (status bar colour, hidden title bar, back button on Android).
"""
import platform
import sys
from functools import partial

import toga
from toga.style import Pack


def system_name():
    if sys.platform == 'ios' or platform.system() == 'iOS':
        return 'iOS'
    if hasattr(sys, 'getandroidapilevel'):
        return 'Android'
    return {'darwin': 'macOS', 'win32': 'Windows'}.get(sys.platform, 'Linux')


def device_locale():
    system = system_name()
    try:
        if system == 'iOS':
            from rubicon.objc import ObjCClass
            return str(ObjCClass('NSLocale').preferredLanguages.firstObject or '')
        if system == 'Android':
            from java.util import Locale
            return str(Locale.getDefault().toLanguageTag())
    except Exception:
        pass
    import locale
    return (locale.getlocale()[0] or '').replace('_', '-')


def data_folder(default, system):
    """Sessions and settings. On iOS, Toga's data folder is Documents (shown
    in the Files app when sharing is on); Application Support is private."""
    if system == 'iOS':
        from pathlib import Path
        return Path.home() / 'Library' / 'Application Support' / 'tg-ascii'
    return default / 'tg-ascii'


class TgAsciiMobile(toga.App):
    def startup(self):
        from .runtime import get_core
        from .launch_appearance import launch_appearance, set_android_typeface, set_apple_typeface, set_launch_wallpaper
        system = system_name()
        self._system = system
        self.core = get_core(data_folder(self.paths.data, system), system, device_locale())
        if system == 'iOS':
            from rubicon.objc import ObjCClass
            try:
                vocabulary = ObjCClass('TGSiriVocabulary')
            except NameError:
                pass
            else:
                self.core.loop.call_soon_threadsafe(self.core.siri_vocabulary.attach, vocabulary, self.core)
            try:
                self.core.tv_link = ObjCClass('TGTVLink')
            except NameError:
                pass  # An older native build can still run the mobile interface.
            else:
                self.core.tv_link.start()
        port = self.core.port
        self.main_window = toga.MainWindow(title=self.formal_name)
        look = launch_appearance(self.core, self.system_dark(system))
        self.launch_background = look['background']
        self.main_window.title = look['title']
        if system == 'iOS':
            from .ios_webview import InlineWebView
            view_type = InlineWebView
        else:
            view_type = toga.WebView
        self.webview = view_type(style=Pack(height=1, background_color=self.launch_background))
        splash = toga.Box(style=Pack(direction='column', flex=1, align_items='center',
                                     justify_content='center', background_color=self.launch_background))
        if look['logo'].is_file():
            try:
                splash.add(toga.ImageView(look['logo'], style=Pack(width=112, height=112)))
            except (OSError, ValueError):
                pass  # A missing or damaged user image must still allow sign-in.
        title_style = Pack(
            color=look['foreground'], margin_top=12, text_align='center',
            font_size=max(14, look['size']),
            font_weight='bold' if look['bold'] else 'normal',
            font_style='italic' if look['italic'] else 'normal',
        )
        title_label = toga.Label(look['title'], style=title_style)
        splash.add(title_label)
        set_launch_wallpaper(splash, look, system, self._impl.native)
        content = toga.Box(children=[splash, self.webview], style=Pack(direction='column'))

        def show_page():
            if splash in content.children:
                content.remove(splash)
                del self.webview.style.height
                self.webview.style.flex = 1

        # Navigation completion doesn't imply that the async first render ran.
        self.core.native_page_ready = lambda: self.on_ui_thread(show_page)
        def update_title(name):
            title = name or 'TeleGraph'
            def apply():
                self.main_window.title = title
                if system == 'Android':
                    from java import jclass
                    self._impl.native.setTitle(title)
                    self._impl.native.setTaskDescription(jclass('android.app.ActivityManager$TaskDescription')(title))
                elif system == 'iOS':
                    scene = self.main_window._impl.native.windowScene
                    if scene is not None:
                        scene.title = title
            if system == 'iOS':
                self.on_main_thread(apply)
            else:
                self.loop.call_soon_threadsafe(apply)
        self.core.native_display_name = update_title
        if system == 'Android':
            self.core.native_home_name = lambda name: self.loop.call_soon_threadsafe(
                self.update_android_home, name or 'TeleGraph', bool(name))
        if self.core.prefs:
            update_title(self.core.prefs.values.get('app_display_name'))
        self.main_window.content = content
        self.main_window.show()
        if system == 'iOS':
            try:
                set_apple_typeface(title_label, look['font'])
            except (AttributeError, NameError, TypeError, ValueError):
                pass  # Keep the system font if the device cannot resolve a typeface.
        elif system == 'Android':
            set_android_typeface(title_label, look['font'])
        self.on_ui_thread(lambda: self.start_web_interface(system, port, show_page))

    def start_web_interface(self, system, port, show_page):
        self.adapt_chrome(system)
        # Background / foreground (Android onStop/onStart, iOS scene): app lock.
        import asyncio as _asyncio
        core = self.core
        self.main_window.on_hide = lambda widget, **kw: _asyncio.run_coroutine_threadsafe(core.api_app_hidden(), core.loop)
        self.main_window.on_show = lambda widget, **kw: self.resumed()
        top, bottom = self.safe_area(system)
        mac = '&mac=1' if self.on_mac(system) else ''
        self._port, self._system = port, system
        self._page_query = f'?t={self.core.token}&platform={system}&top={top}&bottom={bottom}{mac}'
        self.webview.url = f'http://127.0.0.1:{port}/{self._page_query}'
        # Let WebKit/Chromium display its normal error screen if navigation fails.
        self.core.loop.call_soon_threadsafe(self.core.loop.call_later, 5, self.on_ui_thread, show_page)
        if system == 'iOS' and not mac:
            self.install_safe_area_timer(system)
        if system == 'iOS':
            self.install_ios_foreground_observer()

    def system_dark(self, system):
        if system == 'iOS':
            return self.main_window._impl.native.traitCollection.userInterfaceStyle == 2
        if system == 'Android':
            configuration = self._impl.native.getResources().getConfiguration()
            return configuration.uiMode & 0x30 == 0x20
        return True

    def update_android_home(self, title, request_pin=False):
        from java import jclass
        launcher = jclass('org.tgas.launcher.LauncherActivity')
        launcher.updateHomeShortcut(self._impl.native, title, request_pin)

    def resumed(self):
        """Back in the foreground: repair the local server if the system closed
        it (iOS does that to suspended apps) and reconnect to Telegram. If the
        server needed another port, the page is reloaded at the new address."""
        import asyncio
        core = self.core

        def after(future):
            try:
                port = future.result()
            except Exception as exc:
                print('resume:', exc)
                return
            if port != self._port:
                self._port = port
                url = f'http://127.0.0.1:{port}/{self._page_query}'
                def reload_pages():
                    self.webview.url = url
                    reload_chats = getattr(self, 'reload_ios_chat_windows', None)
                    if reload_chats is not None:
                        reload_chats()
                self.on_ui_thread(reload_pages)
            asyncio.run_coroutine_threadsafe(core.api_app_visible(), core.loop)
        asyncio.run_coroutine_threadsafe(core.resume(), core.loop).add_done_callback(after)

    def on_ui_thread(self, work):
        if self._system == 'iOS':
            self.on_main_thread(work)
        else:
            self.loop.call_soon_threadsafe(work)

    def install_ios_foreground_observer(self):
        """iOS: also listen to the system's own 'will enter foreground' notice."""
        from rubicon.objc import Block, ObjCClass, objc_id
        app = self

        def entered(notification):
            app.resumed()
        self._foreground_block = Block(entered, None, objc_id)
        self._foreground_observer = ObjCClass('NSNotificationCenter').defaultCenter.addObserverForName_object_queue_usingBlock_(
            'UIApplicationWillEnterForegroundNotification', None, ObjCClass('NSOperationQueue').mainQueue, self._foreground_block)

    @staticmethod
    def on_mac(system):
        """The iOS app running on an Apple silicon Mac (TestFlight / App Store)."""
        if system != 'iOS':
            return False
        try:
            from rubicon.objc import ObjCClass
            info = ObjCClass('NSProcessInfo').processInfo

            def flag(name):
                # rubicon may hand back the getter itself (always truthy).
                value = getattr(info, name)
                return bool(value() if callable(value) else value)
            result = flag('isiOSAppOnMac') or flag('isMacCatalystApp')
            print('on Mac:', result)
            return result
        except Exception:
            return False

    def install_safe_area_timer(self, system):
        """The window is laid out after start-up and changes when an iPad
        rotates or enters split view: measure every second and tell the page.
        A native timer, because tasks on the app's asyncio loop do not run
        here (the core uses its own loop)."""
        from rubicon.objc import Block, ObjCClass, objc_id
        last = {}

        def tick(timer):
            top, bottom = self.safe_area(system)
            if last.get('value') == (top, bottom) and last.get('applied'):
                return
            last['value'] = (top, bottom)
            script = ("(function(){if(!window.tgBack)return 'wait';var r=document.documentElement.style;"
                      f"r.setProperty('--top','{top}px');r.setProperty('--bottom','{bottom}px');return 'ok';}})()")

            def done(result, error):
                last['applied'] = str(result) == 'ok'
            try:
                self.webview._impl.native.evaluateJavaScript_completionHandler_(script, Block(done, None, objc_id, objc_id))
            except Exception as exc:
                print('safe area script:', type(exc).__name__, exc)

        self._safe_area_block = Block(tick, None, objc_id)
        self._safe_area_timer = ObjCClass('NSTimer').scheduledTimerWithTimeInterval_repeats_block_(
            1.0, True, self._safe_area_block)

    def safe_area(self, system):
        """Space to leave at the top (status bar / notch) and bottom (home bar)
        of the page, in points (= CSS px). Measured against where the WebView
        really is: with the navigation bar hidden, Toga leaves it taller than
        the screen and shifted up."""
        if system != 'iOS':
            return 0, 0
        try:
            web = self.webview._impl.native
            window = self.main_window._impl.native  # the UIWindow
            insets = window.safeAreaInsets
            frame = web.convertRect_toView_(web.bounds, None)
            screen = window.bounds
            top = insets.top - frame.origin.y
            bottom = (frame.origin.y + frame.size.height) - (screen.size.height - insets.bottom)
            return max(0, round(top)), max(0, round(bottom))
        except Exception as exc:
            print('safe area:', exc)
            return 0, 0

    def adapt_chrome(self, system):
        if system == 'iOS':
            # Push must not depend on an optional font, icon, biometric or
            # presentation bridge succeeding earlier in the setup sequence.
            try:
                from . import notify_native
                notify_native.install_ios(self)
            except Exception as exc:
                print('notifications:', type(exc).__name__)
        try:
            if system == 'iOS':
                from rubicon.objc import ObjCClass
                controller = self.main_window._impl.native.rootViewController
                if hasattr(controller, 'setNavigationBarHidden_animated_'):
                    controller.setNavigationBarHidden_animated_(True, False)
                rgb = bytes.fromhex(self.launch_background[1:])
                color = ObjCClass('UIColor').colorWithRed_green_blue_alpha_(*(channel / 255 for channel in rgb), 1.0)
                self.main_window._impl.native.backgroundColor = color
                controller.view.backgroundColor = color
                # Let the page handle the notch and home bar with CSS
                # env(safe-area-inset-*) instead of WebKit shifting the content.
                web = self.webview._impl.native
                web.scrollView.contentInsetAdjustmentBehavior = 2  # Never
                web.scrollView.bounces = False
                pinch = web.scrollView.pinchGestureRecognizer
                if pinch is not None:
                    pinch.enabled = False
                web.setOpaque_(False)
                web.backgroundColor = color
                from . import ios_liquid_glass
                ios_liquid_glass.install(self)
                self.install_ios_opener()
                self.install_ios_icon_switcher()
                self.install_ios_biometric()
                self.install_watch_bridge()
                from . import qr_native
                qr_native.install_ios(self)
                from . import voice_native
                voice_native.install_ios(self)
                from . import ios_calls
                ios_calls.install(self)
                try:
                    from . import ios_windows
                    ios_windows.install(self)
                except Exception as exc:
                    print('windows:', type(exc).__name__, exc)
            elif system == 'Android':
                activity = self._impl.native
                bar = activity.getSupportActionBar()
                if bar is not None:
                    bar.hide()
                from android.graphics import Color
                window = activity.getWindow()
                # Android 15+ draws apps edge to edge: the bars are transparent
                # and show the window background, so paint that too.
                color = Color.parseColor(self.launch_background)
                window.getDecorView().setBackgroundColor(color)
                window.setStatusBarColor(color)
                window.setNavigationBarColor(color)
                self.install_back_button(activity)
                self.install_file_picker(activity)
                self.install_android_opener(activity)
                self.install_icon_switcher(activity)
                self.install_quit(activity)
                self.install_android_biometric(activity)
                from . import qr_native
                qr_native.install_android(self, activity)
                from . import notify_native
                notify_native.install_android(self, activity)
                from . import voice_native
                voice_native.install_android(self, activity)
                from . import android_calls, android_screen_share
                android_screen_share.install(self, activity)
                android_calls.install(self, activity)
                try:
                    # Group voice/video chats and conferences: the desktop's
                    # manager on the same native library (android_group_calls).
                    from . import android_group_calls
                    android_group_calls.install(self.core.native_call_permission)
                    self.core.native_group_call_manager = partial(
                        android_group_calls.AndroidGroupCallManager, core=self.core)
                except Exception as exc:
                    print('group calls:', type(exc).__name__)
                from . import wear_sync
                wear_sync.install_phone(self.core, activity)
                self.install_android_windows(activity)
        except Exception as exc:  # Cosmetic only: never block start-up.
            print('chrome:', exc)


    def install_android_windows(self, activity):
        """A chat in its own system window: a separate task showing the page in
        its window mode (ChatWindowActivity), as split screen or free-form."""
        from java import jclass
        window_class = jclass('org.tgas.windows.ChatWindowActivity')
        core = self.core

        def open_window(peer, name, account, done):
            from urllib.parse import quote
            url = (f'http://127.0.0.1:{core.port}/?t={core.token}&platform=Android&chat={int(peer)}'
                   f'&window=1&account={quote(account, safe="")}&top=0&bottom=0')

            def run():
                try:
                    window_class.open(activity, int(peer), str(name), account, url)
                    done(True)
                except Exception as exc:
                    print('window:', type(exc).__name__)
                    done(False)
            self.loop.call_soon_threadsafe(run)
        core.native_window = open_window

    def install_back_button(self, activity):
        """Android back: one step back in the interface; from the chat list,
        send the app to the background (like Telegram) instead of closing it."""
        try:
            from java import dynamic_proxy
            from android.window import OnBackInvokedCallback, OnBackInvokedDispatcher
        except ImportError:
            return  # Android < 13: the system default applies.

        app = self

        class Back(dynamic_proxy(OnBackInvokedCallback)):
            def onBackInvoked(self):
                async def ask():
                    try:
                        result = await app.webview.evaluate_javascript('window.tgBack ? tgBack() : false')
                    except Exception:
                        result = False
                    if str(result).strip('"').lower() != 'true':
                        activity.moveTaskToBack(True)
                app.loop.create_task(ask())

        self._back = Back()
        activity.getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
            OnBackInvokedDispatcher.PRIORITY_DEFAULT, self._back)


    def install_file_picker(self, activity):
        """Android: attachments come from the system picker (ACTION_OPEN_DOCUMENT);
        each chosen file is copied to the core's private staging folder."""
        from android.content import Intent
        from android.provider import OpenableColumns
        from java import jarray, jclass
        import threading
        app, core = self, self.core

        def copy(uris, done):
            files = []
            resolver = activity.getContentResolver()
            for uri in uris:
                try:
                    name = 'file'
                    cursor = resolver.query(uri, None, None, None, None)
                    if cursor is not None:
                        try:
                            column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                            if column >= 0 and cursor.moveToFirst():
                                name = cursor.getString(column) or name
                        finally:
                            cursor.close()
                    target = core.staging_path(name)
                    stream = resolver.openInputStream(uri)
                    buffer = jarray('B')(1 << 16)  # JNI signature of byte
                    size = 0
                    try:
                        with target.open('wb') as output:
                            while True:
                                count = stream.read(buffer)
                                if count < 0:
                                    break
                                output.write(bytes(buffer)[:count])
                                size += count
                    finally:
                        stream.close()
                    target.chmod(0o600)
                    files.append({'key': target.name, 'name': name, 'size': size})
                except Exception as exc:
                    print('picker copy:', exc)
            done(files)

        def document_intent(kind):
            intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType('audio/*' if kind == 'audio' else '*/*')
            if kind in ('media', 'gallery'):
                types = jarray(jclass('java.lang.String'))(['image/*', 'video/*'])
                intent.putExtra(Intent.EXTRA_MIME_TYPES, types)
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, True)
            return intent

        def gallery_intent():
            """The system photo picker (Android 13+, or its backport through
            Google Play services); the document picker otherwise."""
            from android.provider import MediaStore
            try:
                available = MediaStore.getPickImagesMaxLimit() > 1
            except Exception:
                available = False
            if not available:
                return document_intent('gallery')
            intent = Intent(MediaStore.ACTION_PICK_IMAGES)
            from java import jint
            # A Python int would pick the long overload, which the picker reads as 0.
            intent.putExtra(MediaStore.EXTRA_PICK_IMAGES_MAX, jint(10))
            return intent

        def camera(kind, done):
            """Photo or video from the camera app, saved straight into our cache."""
            from android.provider import MediaStore
            from androidx.core.content import FileProvider
            from java.io import File
            from pathlib import Path
            import time
            shared = Path(str(activity.getCacheDir().getAbsolutePath())) / 'shared'
            shared.mkdir(parents=True, exist_ok=True)
            video = kind == 'video_camera'
            name = time.strftime('%Y%m%d-%H%M%S') + ('.mp4' if video else '.jpg')
            output = shared / name
            uri = FileProvider.getUriForFile(activity, activity.getPackageName() + '.fileprovider', File(str(output)))
            intent = Intent(MediaStore.ACTION_VIDEO_CAPTURE if video else MediaStore.ACTION_IMAGE_CAPTURE)
            intent.putExtra(MediaStore.EXTRA_OUTPUT, uri)
            intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION)

            def complete(code, data):
                def move():
                    files = []
                    try:
                        if code == -1 and output.exists() and output.stat().st_size:
                            target = core.staging_path(name)
                            import shutil
                            shutil.move(str(output), target)
                            target.chmod(0o600)
                            files.append({'key': target.name, 'name': name, 'size': target.stat().st_size})
                    except Exception as exc:
                        print('camera:', exc)
                    finally:
                        output.unlink(missing_ok=True)
                    done(files)
                threading.Thread(target=move, daemon=True).start()
            app._impl.start_activity(intent, on_complete=complete)

        def pick(kind, done):
            def start():
                if kind in ('camera', 'video_camera'):
                    try:
                        camera(kind, done)
                    except Exception as exc:
                        print('camera:', exc)
                        done([])
                    return
                intent = gallery_intent() if kind == 'gallery' else document_intent(kind)

                def complete(code, data):
                    uris = []
                    if code == -1 and data is not None:  # RESULT_OK
                        clip = data.getClipData()
                        if clip is not None:
                            uris = [clip.getItemAt(index).getUri() for index in range(min(clip.getItemCount(), 10))]
                        elif data.getData() is not None:
                            uris = [data.getData()]
                    if not uris:
                        done([])
                        return
                    threading.Thread(target=copy, args=(uris, done), daemon=True).start()
                try:
                    app._impl.start_activity(intent, on_complete=complete)
                except Exception as exc:
                    print('picker:', exc)
                    done([])
            app.loop.call_soon_threadsafe(start)

        core.native_picker = pick


    def install_android_opener(self, activity):
        """Copy files away from the UI thread; launch Android activities on it."""
        from android.content import ClipData, ContentValues, Intent
        from android.net import Uri
        from android.os import Build
        from java.io import File
        from androidx.core.content import FileProvider
        import mimetypes
        import shutil
        import threading
        from pathlib import Path
        shared = Path(str(activity.getCacheDir().getAbsolutePath())) / 'shared'
        shutil.rmtree(shared, ignore_errors=True)  # copies from the last session
        app = self

        def provided(target):
            from tempfile import mkdtemp

            shared.mkdir(parents=True, exist_ok=True)
            directory = Path(mkdtemp(dir=shared))
            copy = directory / Path(target).name
            try:
                shutil.copyfile(target, copy)
                uri = FileProvider.getUriForFile(activity, activity.getPackageName() + '.fileprovider', File(str(copy)))
                return uri, mimetypes.guess_type(copy.name)[0] or 'application/octet-stream', directory
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise

        def save(target, active):
            """MediaStore publishes only a complete copy; failures remove its row."""
            from android.provider import MediaStore
            name, mime = Path(target).name, mimetypes.guess_type(target)[0] or 'application/octet-stream'
            values = ContentValues()
            values.put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            values.put(MediaStore.MediaColumns.MIME_TYPE, mime)
            values.put(MediaStore.MediaColumns.RELATIVE_PATH, 'Download/TG-ASCII')
            values.put(MediaStore.MediaColumns.IS_PENDING, 1)
            resolver = activity.getContentResolver()
            uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            if uri is None:
                raise OSError('Could not create the downloaded file')
            try:
                stream = resolver.openOutputStream(uri)
                if stream is None:
                    raise OSError('Could not open the downloaded file')
                try:
                    with open(target, 'rb') as source:
                        while True:
                            if not active():
                                raise PermissionError('The active account changed.')
                            chunk = source.read(1 << 16)
                            if not chunk:
                                break
                            stream.write(chunk)
                finally:
                    stream.close()
                if not active():
                    raise PermissionError('The active account changed.')
                values = ContentValues()
                values.put(MediaStore.MediaColumns.IS_PENDING, 0)
                resolver.update(uri, values, None, None)
            except Exception:
                resolver.delete(uri, None, None)
                raise

        def opener(kind, target, done):
            owner, backend = app.core.account, app.core.backend

            def active():
                return (not app.core.locked and app.core.account == owner
                        and app.core.backend is backend)

            def present(prepared=None, error=None):
                directory = prepared[2] if prepared else None
                try:
                    if error is not None:
                        raise error
                    if not active():
                        raise PermissionError('The active account changed.')
                    if kind == 'url':
                        intent = Intent(Intent.ACTION_VIEW, Uri.parse(target))
                    elif kind == 'save' and Build.VERSION.SDK_INT >= 29:
                        done(True)
                        return
                    else:
                        uri, mime, directory = prepared
                        if kind == 'file':
                            intent = Intent(Intent.ACTION_VIEW)
                            intent.setDataAndType(uri, mime)
                        else:  # share (also "save" on Android 9 and earlier)
                            intent = Intent(Intent.ACTION_SEND)
                            intent.setType(mime)
                            intent.putExtra(Intent.EXTRA_STREAM, uri)
                        intent.setClipData(ClipData.newRawUri('', uri))
                        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        intent = Intent.createChooser(intent, None)
                        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    activity.startActivity(intent)
                except Exception as exc:
                    if directory is not None:
                        shutil.rmtree(directory, ignore_errors=True)
                    print('open:', exc)
                    done(False)
                else:
                    done(True)

            def prepare():
                prepared, error = None, None
                try:
                    if not active():
                        raise PermissionError('The active account changed.')
                    if kind == 'save' and Build.VERSION.SDK_INT >= 29:
                        save(target, active)
                    else:
                        prepared = provided(target)
                except Exception as exc:
                    error = exc
                app.loop.call_soon_threadsafe(present, prepared, error)

            if kind == 'url':
                app.loop.call_soon_threadsafe(present)
            else:
                threading.Thread(target=prepare, name='tg-file-export', daemon=True).start()
        self.core.native_open = opener

    def install_ios_opener(self):
        """Links with openURL; files: open (Quick Look preview, with its own share
        button), save / share (share sheet: Save to Files, other apps)."""
        import ctypes
        from rubicon.objc import Block, NSObject, ObjCClass, objc_id, objc_method
        app = self
        open_completions = set()

        class Preview(NSObject):
            @objc_method
            def documentInteractionControllerViewControllerForPreview_(self, controller):
                return app.main_window._impl.native.rootViewController

            @objc_method
            def documentInteractionControllerDidEndPreview_(self, controller) -> None:
                release = self.release_file
                self.release_file = None
                if release is not None:
                    release()

        class ShareDismissal(NSObject):
            @objc_method
            def presentationControllerDidDismiss_(self, presentation) -> None:
                if self.finished is not None:
                    self.finished()

        def opener(kind, target, done, *, release=None):
            def run():
                completion = None
                delegate = None
                try:
                    NSURL = ObjCClass('NSURL')
                    root = app.main_window._impl.native.rootViewController
                    if kind == 'url':
                        url = NSURL.URLWithString(target)
                        if url is None:
                            done(False)
                            return
                        def opened(success):
                            open_completions.discard(completion)
                            done(bool(success))

                        completion = Block(opened, None, ctypes.c_bool)
                        open_completions.add(completion)
                        ObjCClass('UIApplication').sharedApplication.openURL_options_completionHandler_(
                            url, ObjCClass('NSDictionary').dictionary(), completion)
                        return
                    url = NSURL.fileURLWithPath(target)
                    if kind == 'file':
                        controller = ObjCClass('UIDocumentInteractionController').interactionControllerWithURL_(url)
                        app._document_delegate = Preview.alloc().init()
                        app._document_delegate.release_file = release
                        app._document_controller = controller
                        controller.delegate = app._document_delegate
                        if controller.presentPreviewAnimated_(True):
                            done(True)
                            return
                    controller = ObjCClass('UIActivityViewController').alloc().initWithActivityItems_applicationActivities_(
                        [url], None)
                    horizontal_size = root.traitCollection.horizontalSizeClass
                    if callable(horizontal_size):
                        horizontal_size = horizontal_size()
                    compact = horizontal_size == 1
                    presented = controller
                    if compact:
                        # UIKit can force a narrow popover when this WebView is
                        # presenting. Give the system activity its own phone sheet.
                        presented = ObjCClass('UINavigationController').alloc().initWithRootViewController_(controller)
                        presented.setNavigationBarHidden_animated_(True, False)
                        presented.setModalPresentationStyle_(1)  # UIModalPresentationPageSheet
                    else:
                        popover = controller.valueForKey_('popoverPresentationController')
                        if popover is not None:  # iPad and Mac: anchor at the centre
                            popover.sourceView = root.view
                            bounds = root.view.bounds
                            from rubicon.objc import CGRect
                            popover.sourceRect = CGRect((bounds.size.width / 2, bounds.size.height / 2), (1, 1))

                    def cleanup():
                        if completion in open_completions:
                            open_completions.discard(completion)
                            open_completions.discard(delegate)
                            if delegate is not None:
                                delegate.finished = None
                            controller.completionWithItemsHandler = None
                            if release is not None:
                                release()

                    def finished(_activity, _completed, _items, _error):
                        if compact and presented.valueForKey_('presentingViewController') is not None:
                            presented.dismissViewControllerAnimated_completion_(True, None)
                        cleanup()

                    completion = Block(finished, None, objc_id, ctypes.c_bool, objc_id, objc_id)
                    open_completions.add(completion)
                    controller.completionWithItemsHandler = completion
                    root.presentViewController_animated_completion_(presented, True, None)
                    if compact:
                        delegate = ShareDismissal.alloc().init()
                        delegate.finished = cleanup
                        open_completions.add(delegate)
                        presented.valueForKey_('presentationController').delegate = delegate
                    done(True)
                except Exception as exc:
                    open_completions.discard(completion)
                    open_completions.discard(delegate)
                    print('open:', exc)
                    done(False)
            self.on_main_thread(run)
        self.core.native_open = opener

    def on_main_thread(self, work):
        """iOS: run UIKit work on the main thread. Callbacks queued on the
        app's asyncio loop do not run there (see install_safe_area_timer)."""
        from rubicon.objc import Block, ObjCClass
        pending = getattr(self, '_main_blocks', None)
        if pending is None:
            pending = self._main_blocks = set()

        def run():
            try:
                work()
            finally:
                pending.discard(block)
        block = Block(run, None)
        pending.add(block)
        ObjCClass('NSOperationQueue').mainQueue.addOperationWithBlock_(block)

    def install_ios_icon_switcher(self):
        """Alternative icons shipped in the asset catalog (tools/patch_ids.py)."""
        from rubicon.objc import Block, ObjCClass, objc_id
        pending = set()

        def switch(name, done):
            target = None if name == 'default' else f'AppIcon-{name}'

            def run():
                try:
                    application = ObjCClass('UIApplication').sharedApplication
                    supports = application.supportsAlternateIcons
                    if not (supports() if callable(supports) else supports):
                        done(False)
                        return

                    def selected():
                        value = application.alternateIconName
                        return (str(value) if value is not None else None) == target

                    if selected():
                        done(True)
                        return

                    def finished(error):
                        pending.discard(block)
                        done(not bool(getattr(error, 'value', error)))

                    block = Block(finished, None, objc_id)
                    pending.add(block)
                    application.setAlternateIconName_completionHandler_(target, block)
                except Exception as exc:
                    print('icon:', exc)
                    done(False)
            self.on_main_thread(run)
        self.core.native_icon = switch

    def install_icon_switcher(self, activity):
        """Android: one launcher <activity-alias> per icon (tools/patch_ids.py);
        enable the chosen one, disable the rest."""
        from android.content import ComponentName, Intent
        from android.content.pm import PackageManager
        from .native_logos import NATIVE_LOGOS

        package = str(activity.getPackageName())
        aliases = {name: f'{package}.Icon{name.capitalize()}' for name in NATIVE_LOGOS}
        known = set(aliases.values())
        launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setPackage(package)
        app = self

        def switch(name, done):
            def run():
                try:
                    manager = activity.getPackageManager()
                    matches = manager.queryIntentActivities(launcher, 0)
                    active = {str(matches.get(i).activityInfo.name) for i in range(matches.size())} & known
                    target = aliases[name]
                    if target not in active:
                        manager.setComponentEnabledSetting(ComponentName(package, target),
                                                           PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
                                                           PackageManager.DONT_KILL_APP)
                    for previous in active - {target}:
                        manager.setComponentEnabledSetting(ComponentName(package, previous),
                                                           PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                                                           PackageManager.DONT_KILL_APP)
                    if app.core.prefs:
                        app.update_android_home(app.core.prefs.values.get('app_display_name') or 'TeleGraph')
                    done(True)
                except Exception as exc:
                    print('icon:', exc)
                    done(False)
            app.loop.call_soon_threadsafe(run)
        self.core.native_icon = switch

    def install_ios_biometric(self):
        """Face ID / Touch ID, or the device passcode, through LocalAuthentication."""
        import ctypes
        from rubicon.objc import Block, ObjCClass, objc_id
        from rubicon.objc.runtime import load_library
        load_library('LocalAuthentication')
        POLICY = 2  # LAPolicyDeviceOwnerAuthentication: biometrics, then the passcode
        app = self

        def available():
            try:
                return bool(ObjCClass('LAContext').alloc().init().canEvaluatePolicy_error_(POLICY, None))
            except Exception as exc:
                print('biometric:', exc)
                return False

        def authenticate(reason, done):
            def run():
                try:
                    context = ObjCClass('LAContext').alloc().init()
                    app._la_context = context

                    def reply(success, error):
                        app._la_block = None
                        done(bool(success))
                    app._la_block = Block(reply, None, ctypes.c_bool, objc_id)
                    context.evaluatePolicy_localizedReason_reply_(POLICY, reason, app._la_block)
                except Exception as exc:
                    print('biometric:', exc)
                    done(False)
            app.on_main_thread(run)
        self.core.native_biometric_available = available
        self.core.native_biometric = authenticate

    def install_watch_bridge(self):
        """Apple Watch companion: answers its WatchConnectivity requests with the
        core ({"json": request} -> {"json": answer}); Telegram stays on the phone."""
        import asyncio
        import json
        from rubicon.objc import NSObject, ObjCBlock, ObjCClass, objc_id, objc_method
        from rubicon.objc.runtime import load_library
        try:
            load_library('WatchConnectivity')
            WCSession = ObjCClass('WCSession')
            supported = WCSession.isSupported
            if not (supported() if callable(supported) else supported):
                return
        except Exception as exc:
            print('watch:', exc)
            return
        core = self.core

        def answer(message):
            try:
                request = json.loads(str(message.objectForKey_('json')))
                future = asyncio.run_coroutine_threadsafe(core.watch_request(request), core.loop)
                result = future.result(timeout=28)
            except Exception as exc:
                from tg_ascii.auth import error_message
                result = {'error': error_message(exc)}
            return json.dumps(result, ensure_ascii=False, default=str)

        class WatchBridge(NSObject):
            @objc_method
            def session_activationDidCompleteWithState_error_(self, session, state: int, error) -> None:
                print('watch session state:', state)

            @objc_method
            def sessionDidBecomeInactive_(self, session) -> None:
                pass

            @objc_method
            def sessionDidDeactivate_(self, session) -> None:
                session.activateSession()  # Another watch was paired.

            @objc_method
            def session_didReceiveMessage_replyHandler_(self, session, message, reply) -> None:
                text = answer(message)
                answer_dict = ObjCClass('NSDictionary').dictionaryWithObject_forKey_(text, 'json')
                ObjCBlock(reply, None, objc_id)(answer_dict.ptr)

        self._watch_bridge = WatchBridge.alloc().init()
        session = WCSession.defaultSession
        session.delegate = self._watch_bridge
        session.activateSession()

    def install_android_biometric(self, activity):
        """The system's confirm-credential screen: fingerprint, face, PIN or pattern,
        whichever the device uses (KeyguardManager)."""
        from android.content import Context
        app = self

        def keyguard():
            return activity.getSystemService(Context.KEYGUARD_SERVICE)

        def available():
            try:
                return bool(keyguard().isDeviceSecure())
            except Exception as exc:
                print('biometric:', exc)
                return False

        def authenticate(reason, done):
            def run():
                try:
                    intent = keyguard().createConfirmDeviceCredentialIntent('TeleGraph', reason)
                    if intent is None:
                        done(False)
                        return
                    app._impl.start_activity(intent, on_complete=lambda code, data: done(code == -1))
                except Exception as exc:
                    print('biometric:', exc)
                    done(False)
            app.loop.call_soon_threadsafe(run)
        self.core.native_biometric_available = available
        self.core.native_biometric = authenticate

    def install_quit(self, activity):
        """Android: close the task and end the process (the core has already
        saved its local copy and closed the sessions)."""
        app = self

        def quit_now():
            def run():
                try:
                    activity.finishAndRemoveTask()
                finally:
                    from java.lang import System
                    app.loop.call_later(0.4, lambda: System.exit(0))
            app.loop.call_soon_threadsafe(run)
        self.core.native_quit = quit_now


def main():
    app = TgAsciiMobile('TeleGraph', 'org.tgas.tg_ascii_mobile')
    if system_name() == 'iOS':
        from .notify_native import install_apns_delegate
        install_apns_delegate(app)
        from . import siri
        siri.install(app)
    return app

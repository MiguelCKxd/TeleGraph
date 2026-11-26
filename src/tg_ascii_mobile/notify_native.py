"""System notifications for new messages (Android, iOS / Mac).

The core decides what to show (notification settings, muted chats, app lock,
the chat open on screen); these adapters only post or remove notifications.
Android can also keep the connection alive in the background with a
foreground service (org.tgas.keepalive.KeepAliveService, tools/android/).
"""
def notification_id(account, peer):
    import zlib
    return zlib.crc32(f'{account}:{peer}'.encode()) & 0x7FFFFFFF


def android_launch_intent(activity, conversation=None, request_code=0):
    from android.app import PendingIntent
    from android.content import Intent
    from org.tgas.launcher import LauncherActivity
    intent = LauncherActivity.conversationIntent(activity, conversation) if conversation else LauncherActivity.mainIntent(activity)
    intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP)
    return PendingIntent.getActivity(activity, request_code, intent, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT)


def android_sender_bitmap(activity, picture):
    """Crop the sender thumbnail to a circle and overlay the current launcher badge."""
    from android.graphics import Bitmap, BitmapFactory, BitmapShader, Canvas, Paint
    from android.content import Intent
    from java import jclass

    source = BitmapFactory.decodeByteArray(picture, 0, len(picture))
    if source is None:
        return None
    size = min(source.getWidth(), source.getHeight(), 256)
    result = Bitmap.createBitmap(size, size, jclass('android.graphics.Bitmap$Config').ARGB_8888)
    canvas = Canvas(result)
    paint = Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG)
    clamp = jclass('android.graphics.Shader$TileMode').CLAMP
    shader = BitmapShader(source, clamp, clamp)
    from android.graphics import Matrix
    scale = size / min(source.getWidth(), source.getHeight())
    matrix = Matrix()
    matrix.setScale(scale, scale)
    matrix.postTranslate((size - source.getWidth() * scale) / 2, (size - source.getHeight() * scale) / 2)
    shader.setLocalMatrix(matrix)
    paint.setShader(shader)
    canvas.drawCircle(size / 2, size / 2, size / 2, paint)
    manager = activity.getPackageManager()
    home = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setPackage(activity.getPackageName())
    match = manager.resolveActivity(home, 0)
    badge = match.loadIcon(manager) if match is not None else manager.getApplicationIcon(activity.getPackageName())
    edge = max(1, round(size * .34))
    badge.setBounds(size - edge, size - edge, size, size)
    badge.draw(canvas)
    return result


def android_message_poster(activity):
    from android.app import NotificationManager
    from android.content import Context
    from android.os import Build
    from java import jclass
    from tg_ascii.i18n import tr

    Builder = jclass('android.app.Notification$Builder')
    BigText = jclass('android.app.Notification$BigTextStyle')
    manager = activity.getSystemService(Context.NOTIFICATION_SERVICE)
    channel_id = 'messages'

    def ensure_channel(audible):
        if Build.VERSION.SDK_INT >= 26:
            from android.app import NotificationChannel
            ident = channel_id if audible else channel_id + '-silent'
            channel = NotificationChannel(ident, tr('Messages') if audible else tr('Silenciar'),
                                          NotificationManager.IMPORTANCE_HIGH if audible else NotificationManager.IMPORTANCE_LOW)
            if not audible:
                channel.setSound(None, None)
            manager.createNotificationChannel(channel)
            return ident
        return channel_id

    def post(account, peer, title, body, count, sound, *, sender=None, picture=None, conversation=''):
        ident = ensure_channel(sound)
        builder = Builder(activity, ident) if Build.VERSION.SDK_INT >= 26 else Builder(activity)
        if Build.VERSION.SDK_INT < 26 and sound:
            builder.setDefaults(1)  # Notification.DEFAULT_SOUND
        builder.setSmallIcon(jclass('org.tgas.tg_ascii_mobile.R$drawable').ic_telegraph_notification)
        builder.setContentTitle(title).setContentText(body).setAutoCancel(True)
        builder.setStyle(BigText().bigText(body)).setContentIntent(android_launch_intent(activity))
        if not sender and Build.VERSION.SDK_INT >= 30:
            from org.tgas.launcher import LauncherActivity
            try:
                LauncherActivity.forgetConversations(activity, str(account), str(peer))
            except Exception as error:
                print('remove conversation shortcut:', type(error).__name__)
        bitmap = None
        if picture:
            try:
                bitmap = android_sender_bitmap(activity, picture)
            except Exception as error:
                print('notification thumbnail:', type(error).__name__)
            if bitmap is not None:
                builder.setLargeIcon(bitmap)
        if sender and Build.VERSION.SDK_INT >= 28:
            from java.lang import System
            person = jclass('android.app.Person$Builder')
            contact = person().setName(title).setKey(f'{account}:{sender}')
            if bitmap is not None:
                contact.setIcon(jclass('android.graphics.drawable.Icon').createWithBitmap(bitmap))
            contact = contact.build()
            if Build.VERSION.SDK_INT >= 30:
                from org.tgas.launcher import LauncherActivity
                try:
                    shortcut = LauncherActivity.publishConversation(
                        activity, str(account), int(peer), conversation if peer < 0 and conversation else title,
                        contact, contact.getIcon())
                    if shortcut:
                        builder.setShortcutId(shortcut)
                        builder.setContentIntent(android_launch_intent(activity, shortcut, notification_id(account, peer)))
                except Exception as error:
                    print('conversation shortcut:', type(error).__name__)
            style = jclass('android.app.Notification$MessagingStyle')(person().setName('TeleGraph').build())
            if conversation:
                style.setConversationTitle(conversation).setGroupConversation(peer < 0)
            style.addMessage(body, System.currentTimeMillis(), contact)
            builder.setStyle(style)
        builder.setCategory('msg').setGroup(f'tgas-{account}')
        if count > 1:
            builder.setNumber(count)
        manager.notify(notification_id(account, peer), builder.build())
    return post


def install_android(app, activity):
    from android.app import NotificationManager, PendingIntent
    from android.content import Context, Intent
    from android.os import Build
    from java import dynamic_proxy, jclass
    from tg_ascii.i18n import tr

    Builder = jclass('android.app.Notification$Builder')
    manager = activity.getSystemService(Context.NOTIFICATION_SERVICE)
    package = activity.getPackageName()
    state = {'asked': False}

    def ask_permission():
        """Android 13+: notifications need the person's permission."""
        if Build.VERSION.SDK_INT < 33 or state['asked']:
            return
        state['asked'] = True
        name = 'android.permission.POST_NOTIFICATIONS'
        if activity.checkSelfPermission(name) != 0:
            activity.requestPermissions([name], 7301)

    def clear(account, peer):
        app.loop.call_soon_threadsafe(lambda: manager.cancel(notification_id(account, peer)))

    state.update(telecom_token=None, telecom_ready=False, call_notice=None)

    class Action(dynamic_proxy(jclass('java.lang.Runnable'))):
        def __init__(self, callback):
            super().__init__()
            self.callback = callback

        def run(self):
            self.callback()

    async def authorize_outgoing(token, disconnect):
        if Build.VERSION.SDK_INT < 26:
            return
        import asyncio
        loop = asyncio.get_running_loop()
        response = loop.create_future()

        def resolve(future=None, error=None):
            if response.done():
                return
            if error is not None:
                response.set_exception(error)
            else:
                response.set_result(future)

        def place():
            if response.done():
                return
            try:
                service = jclass('org.tgas.calls.TelegraphConnectionService')
                future = service.place(activity, token, Action(lambda: loop.call_soon_threadsafe(disconnect)))
                loop.call_soon_threadsafe(resolve, future)
            except Exception as error:
                loop.call_soon_threadsafe(resolve, None, error)

        app.loop.call_soon_threadsafe(place)
        future = await asyncio.wait_for(response, 5)
        unit = jclass('java.util.concurrent.TimeUnit')
        allowed = await asyncio.to_thread(future.get, 10, unit.SECONDS)
        if not allowed:
            raise ValueError(tr('Calls are unavailable on this device.'))

    def telecom_state(snapshot, answer, disconnect):
        if Build.VERSION.SDK_INT < 26:
            return

        def sync():
            try:
                service = jclass('org.tgas.calls.TelegraphConnectionService')
                token = snapshot.get('token')
                phase = snapshot.get('state')
                if not token:
                    service.clear()
                    state.update(telecom_token=None, telecom_ready=False)
                    return
                if phase != 'incoming':
                    service.update(token, phase)
                    if phase == 'ended' and state['telecom_token'] == token:
                        state.update(telecom_token=None, telecom_ready=False)
                    return
                if state['telecom_token'] == token:
                    return
                state.update(telecom_token=token, telecom_ready=False)

                def show():
                    if state['telecom_token'] == token and not state['telecom_ready']:
                        state['telecom_ready'] = True
                        if state['call_notice'] is not None:
                            state['call_notice']()

                def accept():
                    if app.core.in_background or app.core.locked:
                        try:
                            android_launch_intent(activity).send()
                        except Exception:
                            pass
                    else:
                        answer()

                if not service.report(activity, token, Action(show), Action(accept), Action(disconnect)):
                    show()
            except Exception as error:
                state.update(telecom_token=None, telecom_ready=False)
                print('Telecom:', type(error).__name__)

        app.loop.call_soon_threadsafe(sync)

    def incoming_call(token, decline):
        def run():
            from android.net import Uri
            action = jclass('org.tgas.calls.IncomingCallAction')
            tag, ident = 'incoming-call', 1
            if not token:
                state['call_notice'] = None
                action.setDecline(None, None)
                manager.cancel(tag, ident)
                return
            state['call_notice'] = safe_run
            if state['telecom_token'] == token and not state['telecom_ready']:
                return
            if Build.VERSION.SDK_INT >= 33 and activity.checkSelfPermission(
                    'android.permission.POST_NOTIFICATIONS') != 0:
                return

            class Decline(dynamic_proxy(jclass('java.lang.Runnable'))):
                def run(self):
                    decline()

            uri = Uri.parse('telegraph-call://decline/' + token)
            intent = Intent(activity, action).setData(uri)
            pending = PendingIntent.getBroadcast(activity, 0, intent, PendingIntent.FLAG_IMMUTABLE)
            channel = 'incoming-calls'
            label = tr('Incoming call')
            if Build.VERSION.SDK_INT >= 26:
                from android.media import AudioAttributes, RingtoneManager
                ringtone = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
                attributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE).build()
                from android.app import NotificationChannel
                entry = NotificationChannel(channel, label, NotificationManager.IMPORTANCE_HIGH)
                entry.setSound(ringtone, attributes)
                manager.createNotificationChannel(entry)
            builder = Builder(activity, channel) if Build.VERSION.SDK_INT >= 26 else Builder(activity)
            if Build.VERSION.SDK_INT < 26:
                builder.setDefaults(1)
            builder.setSmallIcon(jclass('org.tgas.tg_ascii_mobile.R$drawable').ic_telegraph_notification).setContentTitle(label)
            builder.setCategory('call').setContentIntent(android_launch_intent(activity)).setVisibility(0)
            builder.setOnlyAlertOnce(True).setOngoing(True)
            if Build.VERSION.SDK_INT >= 26:
                builder.setTimeoutAfter(45_000)
            builder.addAction(0, tr('Decline'), pending)
            action.setDecline(uri, Decline())
            manager.notify(tag, ident, builder.build())

        def safe_run():
            try:
                run()
            except Exception as error:
                print('call notification:', type(error).__name__)

        app.loop.call_soon_threadsafe(safe_run)

    def keep_alive(on, title='', text=''):
        """Foreground service: Android keeps the process (and its connection) running."""
        def run():
            try:
                Service = jclass('org.tgas.keepalive.KeepAliveService')
                intent = Intent(activity, Service)
                if on:
                    intent.putExtra('title', title).putExtra('text', text).putExtra('channel', tr('Connected'))
                    if Build.VERSION.SDK_INT >= 26:
                        activity.startForegroundService(intent)
                    else:
                        activity.startService(intent)
                else:
                    activity.stopService(intent)
            except Exception as exc:
                print('keep alive:', exc)
        app.loop.call_soon_threadsafe(run)

    def battery_exemption():
        """Ask Android not to pause the app's network while the screen is off."""
        def run():
            try:
                from android.net import Uri
                from android.provider import Settings
                power = activity.getSystemService(Context.POWER_SERVICE)
                if power.isIgnoringBatteryOptimizations(package):
                    return
                intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse('package:' + package))
                activity.startActivity(intent)
            except Exception as exc:
                print('battery:', exc)
        app.loop.call_soon_threadsafe(run)

    core = app.core
    core.native_notify = android_message_poster(activity)
    core.native_notify_clear = clear
    from org.tgas.launcher import LauncherActivity
    LauncherActivity.setConversationListener(Action(lambda: core.loop.call_soon_threadsafe(
        core.emit, 'notification_route', {})))
    core.native_take_notification_chat = lambda: LauncherActivity.takeConversation(activity)
    core.native_forget_notification_chats = lambda account, peer: LauncherActivity.forgetConversations(
        activity, None if account is None else str(account), None if peer is None else str(peer))
    core.native_incoming_call = incoming_call
    core.native_telecom = telecom_state
    core.native_telecom_outgoing = authorize_outgoing
    core.loop.call_soon_threadsafe(core.install_notification_permission,
                                   lambda: app.loop.call_soon_threadsafe(ask_permission))
    core.native_keep_alive = keep_alive
    core.native_battery_exemption = battery_exemption

    def try_fcm_registration():
        try:
            FirebaseMessaging = jclass('com.google.firebase.messaging.FirebaseMessaging')
            OnCompleteListener = jclass('com.google.android.gms.tasks.OnCompleteListener')
            class TokenListener(dynamic_proxy(OnCompleteListener)):
                def onComplete(self, task):
                    try:
                        if task.isSuccessful():
                            token = str(task.getResult() or '').strip()
                            if token:
                                core.register_push_token(2, token, sandbox=False)
                    except Exception:
                        pass

            app._fcm_listener = TokenListener()
            FirebaseMessaging.getInstance().getToken().addOnCompleteListener(app._fcm_listener)
        except Exception:
            pass  # FCM not bundled; KeepAliveService remains active.

    app.loop.call_soon_threadsafe(try_fcm_registration)


def apns_uses_sandbox(profile, simulator):
    import re
    if simulator:
        return True  # Simulator registers with sandbox APNs and has no provisioning profile.
    return profile.is_file() and bool(re.search(
        rb'<key>aps-environment</key>\s*<string>development</string>', profile.read_bytes()))


def ios_push_payload(user_info):
    import ctypes
    from rubicon.objc import ObjCClass
    data = ObjCClass('NSJSONSerialization').dataWithJSONObject_options_error_(user_info, 0, None)
    if data is None or not data.length:
        return None
    return ctypes.string_at(data.bytes, data.length).decode('utf-8')


def install_apns_delegate(app):
    """Register the UIKit selectors once, before UIApplicationMain inspects its delegate."""
    import ctypes
    from pathlib import Path
    import os
    from rubicon.objc import ObjCBlock, ObjCClass, ObjCInstance, objc_id
    from rubicon.objc.runtime import SEL, add_method, objc_block
    from toga_iOS.app import PythonAppDelegate

    blocks = ctypes.CDLL(None)
    blocks._Block_copy.argtypes = [objc_id]
    blocks._Block_copy.restype = objc_id
    blocks._Block_release.argtypes = [objc_id]
    blocks._Block_release.restype = None

    def token_received(_self, _cmd, _application, token_data):
        token = ObjCInstance(token_data)
        raw = ctypes.string_at(token.bytes, token.length)
        if raw:
            bundle = Path(str(ObjCClass('NSBundle').mainBundle.bundlePath))
            profile = bundle / 'embedded.mobileprovision'
            sandbox = apns_uses_sandbox(profile, os.environ.get('SIMULATOR_UDID'))
            app.core.register_push_token(1, raw.hex(), sandbox=sandbox)

    def registration_failed(_self, _cmd, _application, error):
        # NSError descriptions can contain device-specific information. Keep
        # only Apple's numeric code and retry transient transport failures.
        code = int(ObjCInstance(error).code)
        app.core.loop.call_soon_threadsafe(app.core.native_push_failed, 'APNs', f'APNs_{code}', code != 3000, True)

    def remote_received(_self, _cmd, _application, user_info, completion):
        # UIKit owns the incoming block only for the duration of this method.
        owned = blocks._Block_copy(completion)
        def finish(result):
            try:
                ObjCBlock(owned, None, ctypes.c_ulong)(result)
            finally:
                blocks._Block_release(owned)
        try:
            payload = ios_push_payload(ObjCInstance(user_info))
            if not payload:
                finish(1)
                return
            if ObjCClass('UIApplication').sharedApplication.applicationState == 2:
                app.core.loop.call_soon_threadsafe(setattr, app.core, 'in_background', True)
            future = app.core.receive_push_payload(payload)
        except Exception:
            finish(2)
            return

        def completed(future):
            try:
                result = future.result()
            except Exception:
                result = 2
            app.on_main_thread(lambda: finish(result))
        future.add_done_callback(completed)

    add_method(PythonAppDelegate, 'application:didRegisterForRemoteNotificationsWithDeviceToken:',
               token_received, [None, objc_id, SEL, objc_id, objc_id])
    add_method(PythonAppDelegate, 'application:didFailToRegisterForRemoteNotificationsWithError:',
               registration_failed, [None, objc_id, SEL, objc_id, objc_id])
    add_method(PythonAppDelegate, 'application:didReceiveRemoteNotification:fetchCompletionHandler:',
               remote_received, [None, objc_id, SEL, objc_id, objc_id, objc_block])


def install_ios(app):
    import ctypes
    from rubicon.objc import NSObject, ObjCBlock, ObjCClass, ObjCInstance, objc_id, objc_method, Block
    from rubicon.objc.runtime import load_library

    load_library('UserNotifications')
    center = ObjCClass('UNUserNotificationCenter').currentNotificationCenter()
    carplay = bool(ObjCClass('NSBundle').mainBundle.objectForInfoDictionaryKey_('TeleGraphCarPlayEnabled'))
    if carplay:
        category = ObjCClass('UNNotificationCategory').categoryWithIdentifier_actions_intentIdentifiers_options_(
            'TeleGraphMessage', [], ['INSearchForMessagesIntent'], 1 << 1)  # allowInCarPlay
        center.setNotificationCategories_(ObjCClass('NSSet').setWithObject_(category))
    keep = set()

    class Presenter(NSObject):
        # The account worker applies mute, open-chat and privacy settings to local notices.
        @objc_method
        def userNotificationCenter_willPresentNotification_withCompletionHandler_(self, center, notification, handler) -> None:
            options = 0
            try:
                request = notification.request
                trigger = request.trigger
                if trigger is not None and trigger.isKindOfClass_(ObjCClass('UNPushNotificationTrigger')):
                    payload = ios_push_payload(request.content.userInfo)
                    if payload:
                        app.core.receive_push_payload(payload)
                else:
                    options = (1 << 1) | (1 << 3) | (1 << 4)  # sound, list, banner
            finally:
                ObjCBlock(handler, None, ctypes.c_ulong)(options)

    presenter = Presenter.alloc().init()
    app._notification_presenter = presenter
    center.delegate = presenter
    core = app.core
    core.native_push_retry = lambda: app.on_main_thread(
        lambda: ObjCClass('UIApplication').sharedApplication.registerForRemoteNotifications())
    # A push can cold-start UIApplication directly in the background; there
    # need not have been a window hide or JavaScript visibility event yet.
    background = ObjCClass('UIApplication').sharedApplication.applicationState == 2
    core.loop.call_soon_threadsafe(setattr, core, 'in_background', bool(background))
    checking_permission = False

    def refresh_permission():
        """Returning from Settings rechecks permission, without showing a prompt."""
        def run():
            nonlocal checking_permission
            if checking_permission:
                return
            checking_permission = True
            def checked(settings):
                nonlocal checking_permission
                checking_permission = False
                keep.discard(block)
                status = int(ObjCInstance(settings).authorizationStatus)
                def apply():
                    if core._push_stopped or not core.prefs or not core.prefs.values.get('notifications', True):
                        return
                    if status in (2, 3, 4):  # authorized, provisional, ephemeral
                        core._push_permission = 'granted'
                        core.native_push_retry()
                    else:
                        core.native_push_failed('APNs', 'permission_denied' if status == 1 else 'permission_not_requested', False, True)
                core.loop.call_soon_threadsafe(apply)
            block = Block(checked, None, objc_id)
            keep.add(block)
            try:
                center.getNotificationSettingsWithCompletionHandler_(block)
            except Exception:
                checking_permission = False
                keep.discard(block)
                core.loop.call_soon_threadsafe(core.native_push_failed, 'APNs', 'permission_query_failed', False, True)
        app.on_main_thread(run)
    core.native_notify_refresh = refresh_permission

    def ask_permission():
        def run():
            try:
                def answered(granted, error):
                    keep.discard(block)
                    if granted:
                        def apply():
                            if core._push_stopped:
                                return
                            core._push_permission = 'granted'
                            if core.prefs and core.prefs.values.get('notifications', True):
                                core.native_push_retry()
                        core.loop.call_soon_threadsafe(apply)
                    else:
                        core.loop.call_soon_threadsafe(core.native_push_failed, 'APNs', 'permission_denied', False, True)
                block = Block(answered, None, ctypes.c_bool, objc_id)
                keep.add(block)
                center.requestAuthorizationWithOptions_completionHandler_(7 | ((1 << 3) if carplay else 0), block)
            except Exception as exc:
                print('notify:', exc)
        app.on_main_thread(run)

    async def post(account, peer, title, body, count, sound, *, sender=None, picture=None, conversation='', message_id=None):
        import asyncio
        loop = asyncio.get_running_loop()
        accepted = loop.create_future()

        def submitted(error):
            def complete():
                if not accepted.done():
                    if error:
                        accepted.set_exception(RuntimeError('iOS could not schedule the notification'))
                    else:
                        accepted.set_result(None)
            loop.call_soon_threadsafe(complete)

        content = ObjCClass('UNMutableNotificationContent').alloc().init()
        content.title = title
        content.body = body
        content.threadIdentifier = f'{account}:{peer}'
        if carplay and sender and message_id and (recipient := core.accounts.identities.get(account)):
            content.categoryIdentifier = 'TeleGraphMessage'
            content.userInfo = {'TeleGraphMessageRoute': [recipient, peer, message_id]}
        if sound:
            content.sound = ObjCClass('UNNotificationSound').defaultSound
        if sender:
            try:
                load_library('Intents')
                identity = f'{account}:{sender}'
                handle = ObjCClass('INPersonHandle').alloc().initWithValue_type_(identity, 0)
                image = ObjCClass('INImage').imageWithImageData_(picture) if picture else None
                person = ObjCClass('INPerson').alloc().initWithPersonHandle_nameComponents_displayName_image_contactIdentifier_customIdentifier_(
                    handle, None, title, image, None, identity)
                group = ObjCClass('INSpeakableString').alloc().initWithSpokenPhrase_(conversation) if conversation else None
                intent = ObjCClass('INSendMessageIntent').alloc().initWithRecipients_outgoingMessageType_content_speakableGroupName_conversationIdentifier_serviceName_sender_attachments_(
                    None, 1, None, group, f'{account}:{peer}', 'TeleGraph', person, None)
                interaction = ObjCClass('INInteraction').alloc().initWithIntent_response_(intent, None)
                interaction.direction = 2  # INInteractionDirectionIncoming
                interaction.donateInteractionWithCompletion_(None)
                updated = content.contentByUpdatingWithProvider_error_(intent, None)
                if updated is not None:
                    content = updated
            except Exception as error:
                print('communication notification:', type(error).__name__)
        request = ObjCClass('UNNotificationRequest').requestWithIdentifier_content_trigger_(
            f'tgas-{notification_id(account, peer)}', content, None)
        block = Block(submitted, None, objc_id)
        center.addNotificationRequest_withCompletionHandler_(request, block)
        await asyncio.wait_for(accepted, 8)

    def clear(account, peer):
        def run():
            identifier = f'tgas-{notification_id(account, peer)}'
            center.removeDeliveredNotificationsWithIdentifiers_([identifier])
        app.on_main_thread(run)

    def keep_alive(on, title='', text=''):
        """iOS: a short extra time to finish the current work when the app goes to
        the background (the system decides how long, usually ~30 s)."""
        def run():
            application = ObjCClass('UIApplication').sharedApplication
            task = getattr(app, '_background_task', None)
            if on and task is None:
                def expired():
                    current = getattr(app, '_background_task', None)
                    app._background_task = None
                    if current is not None:
                        application.endBackgroundTask_(current)
                app._background_expired = Block(expired, None)
                app._background_task = application.beginBackgroundTaskWithExpirationHandler_(app._background_expired)
            elif not on and task is not None:
                app._background_task = None
                application.endBackgroundTask_(task)
        app.on_main_thread(run)

    core = app.core
    core.native_notify = post
    from .ios_notice_cache import NoticeCache
    bundle = str(ObjCClass('NSBundle').mainBundle.bundleIdentifier)
    container = ObjCClass('NSFileManager').defaultManager.containerURLForSecurityApplicationGroupIdentifier_(
        f'group.{bundle}')
    if container is not None:
        try:
            core.ios_notice_cache = NoticeCache(str(container.path))
        except OSError as error:
            print('notification group:', type(error).__name__)
        else:
            core.loop.call_soon_threadsafe(core.ios_notice_cache.sync, core)
    core.native_notify_clear = clear
    def disable_remote():
        def run():
            application = ObjCClass('UIApplication').sharedApplication
            application.unregisterForRemoteNotifications()
        app.on_main_thread(run)

    core.loop.call_soon_threadsafe(core.install_notification_permission, ask_permission, disable_remote)
    core.native_keep_alive = keep_alive

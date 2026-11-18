"""Appearance exchange between the Android app and its Wear OS companion."""
import json
import re
import time

PATH = '/telegraph/appearance/v1'
PACKAGE = 'org.tgas.android'
PALETTE_FIELDS = ('bg', 'panel', 'text', 'muted', 'strong')


def decode_appearance(data):
    from .core import Core

    try:
        packet = json.loads(data)
        revision, values = packet['revision'], packet['appearance']
        if type(revision) is not int or revision <= 0:
            return None
        palette = {key: values[key] for key in PALETTE_FIELDS}
        if not all(re.fullmatch(r'#[0-9a-fA-F]{6}', value) for value in palette.values()):
            return None
        palette.update(
            scale=max(.8, min(1.6, float(values.get('scale', 1)))),
            bold=values.get('bold') is True,
            italic=values.get('italic') is True,
            bubbles=values.get('bubbles') is True,
            font=values['font'] if values.get('font') in Core.FONTS else '',
            icon=values['icon'] if values.get('icon') in Core.ICONS else 'default',
            brand_logo=Core.brand_logo(values.get('brand_logo')),
        )
    except (AttributeError, KeyError, ValueError, TypeError):
        return None
    return revision, palette


def appearance_publisher(loop, send):
    """Serialize Data Layer writes and supersede retries with newer choices."""
    desired = sent = pending = retry = None
    revision = failures = 0

    def flush():
        nonlocal pending, revision, retry
        retry = None
        if pending is not None or desired is None or desired == sent:
            return
        payload = desired
        revision = max(time.time_ns(), revision + 1)
        packet = pending = {'revision': revision, 'appearance': payload}

        def complete(success):
            nonlocal pending, sent, retry, failures
            if pending is not packet:
                return
            pending = None
            if success:
                sent = payload
                failures = 0
            if desired != payload:
                failures = 0
                flush()
            elif not success and failures < 3:
                retry = loop.call_later(2 ** failures, flush)
                failures += 1

        try:
            send(packet, complete)
        except Exception:
            complete(False)

    def publish(values):
        nonlocal desired, failures, retry
        if values != desired or (pending is None and retry is None and desired != sent):
            desired = values.copy()
            failures = 0
            if retry is not None:
                retry.cancel()
                retry = None
            flush()
    return publish


def install_phone(core, activity):
    from com.google.android.gms.wearable import PutDataRequest, Wearable
    from java import dynamic_proxy
    from com.google.android.gms.tasks import OnCompleteListener

    client = Wearable.getDataClient(activity.getApplicationContext())

    class Published(dynamic_proxy(OnCompleteListener)):
        def __init__(self, complete):
            super().__init__()
            self.complete = complete

        def onComplete(self, task):
            core.loop.call_soon_threadsafe(self.complete, task.isSuccessful())

    def send(packet, complete):
        data = json.dumps(packet, separators=(',', ':')).encode()
        request = PutDataRequest.create(PATH).setData(data).setUrgent()
        client.putDataItem(request).addOnCompleteListener(Published(complete))

    core.native_wear_appearance = appearance_publisher(core.loop, send)
    core.loop.call_soon_threadsafe(core.publish_wear_appearance)


def watch_listener(app, activity, did_read):
    from android.net import Uri
    from com.google.android.gms.tasks import OnCompleteListener
    from com.google.android.gms.wearable import DataClient, Wearable
    from java import dynamic_proxy, jclass

    class Registered(dynamic_proxy(OnCompleteListener)):
        def __init__(self, session):
            super().__init__()
            self.session = session

        def onComplete(self, task):
            app.loop.call_soon_threadsafe(on_registered, self.session, task.isSuccessful())

    class Read(dynamic_proxy(OnCompleteListener)):
        def __init__(self, request):
            super().__init__()
            self.request = request

        def onComplete(self, task):
            newest = None
            success = task.isSuccessful()
            if success:
                data = task.getResult()
                try:
                    for i in range(data.getCount()):
                        payload = data.get(i).getData()
                        decoded = decode_appearance(bytes(payload)) if payload is not None else None
                        if decoded and (newest is None or decoded[0] > newest[0]):
                            newest = decoded
                except Exception as error:
                    print('wear appearance:', type(error).__name__)
                    success = False
                finally:
                    data.release()
            app.loop.call_soon_threadsafe(on_read, self.request, success, newest)

    uri = Uri.parse('wear://*' + PATH)
    client = Wearable.getDataClient(activity.getApplicationContext())
    listener_type = jclass('com.google.android.gms.wearable.DataClient$OnDataChangedListener')

    class Changed(dynamic_proxy(listener_type)):
        def onDataChanged(self, events):
            app.loop.call_soon_threadsafe(read)

    listener = Changed()
    active = registered = False
    session = request = failures = 0
    retry = None

    def clear_retry():
        nonlocal retry
        if retry is not None:
            retry.cancel()
            retry = None

    def try_later(operation):
        nonlocal failures, retry
        clear_retry()
        if failures < 4:
            retry = app.loop.call_later(2 ** failures, operation)
            failures += 1

    def on_read(sequence, success, result):
        nonlocal failures
        if not active or sequence != request:
            return
        if success:
            failures = 0
            did_read(result)
        else:
            try_later(read)

    def read():
        nonlocal request
        if active and registered:
            clear_retry()
            request += 1
            try:
                client.getDataItems(uri, DataClient.FILTER_LITERAL).addOnCompleteListener(Read(request))
            except Exception:
                try_later(read)

    def on_registered(epoch, success):
        nonlocal registered, failures
        if not active or epoch != session:
            return
        registered = success
        if success:
            failures = 0
            read()
        else:
            try_later(register)

    def register():
        clear_retry()
        try:
            client.addListener(listener, uri, DataClient.FILTER_LITERAL).addOnCompleteListener(Registered(session))
        except Exception:
            try_later(register)

    def start(*args, **kwargs):
        nonlocal active, session, failures
        if not active:
            active = True
            session += 1
            failures = 0
            register()
        elif registered:
            read()

    def stop(*args, **kwargs):
        nonlocal active, registered, request
        if active:
            active = registered = False
            request += 1
            clear_retry()
            client.removeListener(listener)

    return start, stop

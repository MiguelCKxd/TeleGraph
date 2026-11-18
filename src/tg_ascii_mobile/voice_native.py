"""Microphone recording for voice messages (Android, iOS).

Each platform gives the core a recorder with:
  start(path_without_extension, done(result))  result: {'path'} or {'error'}
  stop() -> path or None       level() -> 0..1       cancel()
Android 10+ records Ogg/Opus directly (what Telegram uses); older Android
records AAC (.m4a, sent as an audio file). iOS records Opus into a CAF file,
which the core turns into Ogg (opus_mux) without re-encoding.
"""
from pathlib import Path
import threading
import time


def install_android(app, activity):
    from android.os import Build
    from java import jclass

    MediaRecorder = jclass('android.media.MediaRecorder')
    permission = 'android.permission.RECORD_AUDIO'
    state = {}
    gate = threading.Lock()

    def granted():
        return activity.checkSelfPermission(permission) == 0

    def ask(done):
        """Ask for the microphone and wait for the answer. Android drops a request
        made while another permission dialog is open (notifications on first
        start), so a request that never showed a dialog is made once more."""
        if granted():
            done(True)
            return

        def wait():
            for attempt in range(2):
                app.loop.call_soon_threadsafe(lambda: activity.requestPermissions([permission], 7302))
                began, shown = time.monotonic(), False
                while time.monotonic() - began < 90:
                    time.sleep(0.25)
                    if granted():
                        done(True)
                        return
                    if not activity.hasWindowFocus():
                        shown = True  # a dialog covers the app
                        continue
                    if shown or time.monotonic() - began > 3:
                        break  # a dialog closed without a yes, or none appeared
                time.sleep(0.4)
                if granted():
                    done(True)
                    return
                if attempt == 0 and not activity.shouldShowRequestPermissionRationale(permission) and not shown:
                    continue  # the request was dropped: ask again
                if attempt == 0 and shown and not activity.shouldShowRequestPermissionRationale(permission):
                    continue  # the dialog was another app permission's: ask again
                break
            done(granted())
        threading.Thread(target=wait, daemon=True).start()

    def start(base, done):
        token = state['wanted'] = object()  # stop/cancel before it starts drops it

        def allowed(ok):
            if not ok:
                done({'error': 'permission'})
                return
            with gate:
                if state.get('wanted') is not token:
                    done({'error': 'cancelled'})
                    return
                try:
                    ogg = Build.VERSION.SDK_INT >= 29
                    path = base + ('.ogg' if ogg else '.m4a')
                    recorder = MediaRecorder(activity) if Build.VERSION.SDK_INT >= 31 else MediaRecorder()
                    state.update(recorder=recorder, path=path)
                    recorder.setAudioSource(1)  # MIC
                    if ogg:
                        recorder.setOutputFormat(11)  # OGG
                        recorder.setAudioEncoder(7)   # OPUS
                    else:
                        recorder.setOutputFormat(2)   # MPEG_4
                        recorder.setAudioEncoder(3)   # AAC
                    recorder.setAudioChannels(1)
                    recorder.setAudioSamplingRate(48000)
                    recorder.setAudioEncodingBitRate(32000)
                    recorder.setOutputFile(path)
                    recorder.prepare()
                    recorder.start()
                    done({'path': path})
                except Exception as exc:
                    print('voice:', exc)
                    release()
                    failed_path = state.pop('path', None)
                    if failed_path:
                        Path(failed_path).unlink(missing_ok=True)
                    done({'error': str(exc)})
        ask(allowed)

    def release():
        recorder = state.pop('recorder', None)
        if recorder is not None:
            try:
                recorder.release()
            except Exception:
                pass

    def stop():
        with gate:
            state['wanted'] = None
            recorder = state.get('recorder')
            path = state.pop('path', None)
            if recorder is None:
                return None
            try:
                recorder.stop()
            except Exception as exc:  # stopped right after starting: nothing recorded
                print('voice stop:', exc)
                if path:
                    Path(path).unlink(missing_ok=True)
                path = None
            release()
            return path

    def level():
        recorder = state.get('recorder')
        try:
            return min(1.0, recorder.getMaxAmplitude() / 20000) if recorder is not None else 0.0
        except Exception:
            return 0.0

    app.core.native_voice = {'start': start, 'stop': stop, 'level': level, 'cancel': stop}


def install_ios(app):
    import ctypes
    from rubicon.objc import Block, ObjCClass
    from rubicon.objc.runtime import load_library

    load_library('AVFoundation')
    AVAudioSession = ObjCClass('AVAudioSession')
    state = {}
    gate = threading.Lock()
    keep = set()

    def session_on():
        session = AVAudioSession.sharedInstance()
        # PlayAndRecord, loudspeaker by default, Bluetooth headsets allowed.
        session.setCategory_mode_options_error_('AVAudioSessionCategoryPlayAndRecord', 'AVAudioSessionModeDefault',
                                                 0x8 | 0x4, None)
        session.setActive_error_(True, None)

    def session_off():
        try:
            session = AVAudioSession.sharedInstance()
            session.setActive_withOptions_error_(False, 1, None)  # let other audio resume
            session.setCategory_error_('AVAudioSessionCategoryPlayback', None)
        except Exception as exc:
            print('voice session:', exc)

    def ask(done):
        session = AVAudioSession.sharedInstance()
        current = int(session.recordPermission)
        if current == 0x67726E74:  # 'grnt'
            done(True)
            return
        if current == 0x64656E79:  # 'deny'
            done(False)
            return

        def answered(ok):
            keep.discard(block)
            done(bool(ok))
        block = Block(answered, None, ctypes.c_bool)
        keep.add(block)
        session.requestRecordPermission_(block)

    def start(base, done):
        token = state['wanted'] = object()  # stop/cancel before it starts drops it

        def allowed(ok):
            if not ok:
                done({'error': 'permission'})
                return

            def run():
                # Not on the main thread: activating the audio session and
                # starting the recorder can wait on the audio hardware.
                with gate:
                    if state.get('wanted') is not token:
                        done({'error': 'cancelled'})
                        return
                    try:
                        session_on()
                        path = base + '.caf'
                        url = ObjCClass('NSURL').fileURLWithPath_(path)
                        settings = {'AVFormatIDKey': 0x6F707573,  # kAudioFormatOpus
                                    'AVSampleRateKey': 48000.0, 'AVNumberOfChannelsKey': 1,
                                    'AVEncoderBitRateKey': 32000}
                        recorder = ObjCClass('AVAudioRecorder').alloc().initWithURL_settings_error_(url, settings, None)
                        if recorder is None:
                            raise RuntimeError('recorder')
                        recorder.meteringEnabled = True
                        if not recorder.record():
                            raise RuntimeError('record')
                        state.update(recorder=recorder, path=path)
                        done({'path': path})
                    except Exception as exc:
                        print('voice:', exc)
                        session_off()
                        done({'error': str(exc)})
            threading.Thread(target=run, daemon=True).start()
        ask(allowed)

    def stop():
        with gate:
            state['wanted'] = None
            recorder = state.pop('recorder', None)
            path = state.pop('path', None)
            if recorder is None:
                return None
            try:
                recorder.stop()  # the core calls this in a worker thread
            finally:
                session_off()
            return path

    def level():
        recorder = state.get('recorder')
        if recorder is None:
            return 0.0
        try:
            recorder.updateMeters()
            power = float(recorder.averagePowerForChannel_(0))  # -160..0 dB
            return max(0.0, min(1.0, (power + 50) / 50))
        except Exception:
            return 0.0

    app.core.native_voice = {'start': start, 'stop': stop, 'level': level, 'cancel': stop}

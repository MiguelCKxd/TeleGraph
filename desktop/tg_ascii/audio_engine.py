"""Private bounded audio capture/playback. No networking; no Tk from audio threads."""
from pathlib import Path
import threading
from .i18n import tr


def libraries():
    try:
        import sounddevice as sd
        import soundfile as sf
        return sd, sf
    except (ImportError, OSError) as exc:
        raise RuntimeError(tr('Audio components are unavailable in this build.')) from exc


class AudioJob:
    def __init__(self):
        self.stop_event = threading.Event()
        self.done = threading.Event()
        self.error = None
        self.seconds = 0
        self.thread = None

    def start(self, action):
        def run():
            try: action()
            except Exception as exc: self.error = exc
            finally: self.done.set()
        self.thread = threading.Thread(target=run, daemon=True, name='tg-as-audio')
        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()

    def record(self, path, max_seconds=600):
        path = Path(path)
        def capture():
            sd, sf = libraries()
            if not sf.check_format('OGG', 'OPUS'):
                raise RuntimeError(tr('This build cannot encode Opus voice messages.'))
            # Fixed 48 kHz mono matches Opus. Blocking reads avoid disk I/O in
            # a realtime callback. At most 100 ms elapses before observing Stop.
            with sf.SoundFile(str(path), mode='x', samplerate=48000, channels=1, format='OGG', subtype='OPUS') as output:
                path.chmod(0o600)
                with sd.RawInputStream(samplerate=48000, channels=1, dtype='int16') as microphone:
                    while not self.stop_event.is_set() and self.seconds < max_seconds:
                        block, overflow = microphone.read(4800)
                        if overflow: raise RuntimeError(tr('Microphone overflow. Record the message again.'))
                        output.buffer_write(block, dtype='int16')
                        self.seconds += len(block) / 96000
            if self.seconds < .2: raise ValueError(tr('The recording is empty.'))
            with sf.SoundFile(str(path)) as check:
                if check.frames <= 0: raise ValueError(tr('The recording is empty.'))
        return self.start(capture)

    def play(self, path):
        def playback():
            sd, sf = libraries()
            with sf.SoundFile(str(path)) as source:
                if source.channels > 2 or source.samplerate > 192000:
                    raise ValueError(tr('Unsupported audio format. Save the file to open it externally.'))
                with sd.RawOutputStream(samplerate=source.samplerate, channels=source.channels, dtype='int16') as speaker:
                    while not self.stop_event.is_set():
                        block = source.buffer_read(max(1, source.samplerate // 10), dtype='int16')
                        if not block: break
                        speaker.write(block)
                        self.seconds += len(block) / (2 * source.channels * source.samplerate)
        return self.start(playback)

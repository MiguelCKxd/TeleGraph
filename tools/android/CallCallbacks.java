package org.tgas.calls;

import android.util.Log;
import com.chaquo.python.PyObject;
import io.github.pytgcalls.ConnectionChangeCallback;
import io.github.pytgcalls.ConnectionInfo;
import io.github.pytgcalls.FramesCallback;
import io.github.pytgcalls.RemoteSource;
import io.github.pytgcalls.RemoteSourceChangeCallback;
import io.github.pytgcalls.SignalingDataCallback;
import io.github.pytgcalls.UpdateEmojisCallback;
import io.github.pytgcalls.media.StreamDevice;
import io.github.pytgcalls.media.StreamMode;
import io.github.pytgcalls.models.Frame;
import java.util.List;

/** Concrete callback methods for NTgCalls JNI and the shared Python call manager. */
public final class CallCallbacks implements ConnectionChangeCallback, FramesCallback,
        RemoteSourceChangeCallback, SignalingDataCallback, UpdateEmojisCallback {

    private volatile PyObject handler;

    public CallCallbacks(PyObject handler) {
        this.handler = handler;
    }

    public void close() {
        handler = null;
    }

    private void dispatch(String name, Object... arguments) {
        PyObject target = handler;
        if (target != null) {
            try {
                target.callAttr(name, arguments);
            } catch (RuntimeException error) {
                Log.w("TeleGraphCall", name + ": " + error.getClass().getSimpleName());
            }
        }
    }

    @Override
    public void onConnectionChange(long peer, ConnectionInfo info) {
        dispatch("connection_changed", peer, info);
    }

    @Override
    public void onFrames(long peer, StreamMode mode, StreamDevice device, List<Frame> frames) {
        dispatch("frames_received", peer, mode, device, frames);
    }

    @Override
    public void onRemoteSourceChange(long peer, RemoteSource source) {
        dispatch("remote_source_changed", peer, source);
    }

    @Override
    public void onSignalingData(long peer, byte[] data) {
        dispatch("signaling_received", peer, data);
    }

    @Override
    public void onUpdateEmojis(long peer, String emojis) {
        dispatch("emojis_received", peer, emojis);
    }
}

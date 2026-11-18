package org.tgas.calls;

import android.util.Log;
import com.chaquo.python.PyObject;
import io.github.pytgcalls.ConnectionChangeCallback;
import io.github.pytgcalls.ConnectionInfo;
import io.github.pytgcalls.FramesCallback;
import io.github.pytgcalls.OutboundBlockCallback;
import io.github.pytgcalls.RemoteSource;
import io.github.pytgcalls.RemoteSourceChangeCallback;
import io.github.pytgcalls.RequestBroadcastPartCallback;
import io.github.pytgcalls.RequestBroadcastTimestampCallback;
import io.github.pytgcalls.RequestParticipantsCallback;
import io.github.pytgcalls.SignalingDataCallback;
import io.github.pytgcalls.StreamEndCallback;
import io.github.pytgcalls.SubchainRequestCallback;
import io.github.pytgcalls.UpdateEmojisCallback;
import io.github.pytgcalls.UpgradeCallback;
import io.github.pytgcalls.e2e.SubchainRequest;
import io.github.pytgcalls.media.MediaState;
import io.github.pytgcalls.media.StreamDevice;
import io.github.pytgcalls.media.StreamMode;
import io.github.pytgcalls.media.StreamType;
import io.github.pytgcalls.models.Frame;
import io.github.pytgcalls.models.ParticipantsRequest;
import io.github.pytgcalls.models.SegmentPartRequest;
import java.util.List;

/**
 * Every NTgCalls event of a group call or conference, forwarded to the
 * Python binding as native_event(name, chat_id, values...). Concrete methods
 * (no Chaquopy dynamic proxies) keep JNI callbacks on the native threads safe.
 */
public final class GroupCallCallbacks implements ConnectionChangeCallback, FramesCallback,
        OutboundBlockCallback, RemoteSourceChangeCallback, RequestBroadcastPartCallback,
        RequestBroadcastTimestampCallback, RequestParticipantsCallback, SignalingDataCallback,
        StreamEndCallback, SubchainRequestCallback, UpdateEmojisCallback, UpgradeCallback {

    private volatile PyObject handler;

    public GroupCallCallbacks(PyObject handler) {
        this.handler = handler;
    }

    public void close() {
        handler = null;
    }

    private void dispatch(Object... arguments) {
        PyObject target = handler;
        if (target != null) {
            try {
                target.callAttr("native_event", arguments);
            } catch (RuntimeException error) {
                Log.w("TeleGraphGroupCall", arguments[0] + ": " + error.getClass().getSimpleName());
            }
        }
    }

    @Override
    public void onConnectionChange(long chat, ConnectionInfo info) {
        dispatch("on_connection_change", chat, info);
    }

    @Override
    public void onFrames(long chat, StreamMode mode, StreamDevice device, List<Frame> frames) {
        dispatch("on_frames", chat, mode, device, frames);
    }

    @Override
    public void onOutboundBlock(long chat, byte[] block) {
        dispatch("on_outbound_block", chat, block);
    }

    @Override
    public void onRemoteSourceChange(long chat, RemoteSource source) {
        dispatch("on_remote_source_change", chat, source);
    }

    @Override
    public void onRequestBroadcastPart(long chat, SegmentPartRequest request) {
        dispatch("on_request_broadcast_part", chat, request);
    }

    @Override
    public void onRequestBroadcastTimestamp(long chat) {
        dispatch("on_request_broadcast_timestamp", chat);
    }

    @Override
    public void onRequestParticipants(long chat, ParticipantsRequest request) {
        dispatch("on_request_participants", chat, request);
    }

    @Override
    public void onSignalingData(long chat, byte[] data) {
        dispatch("on_signaling_data", chat, data);
    }

    @Override
    public void onStreamEnd(long chat, StreamType type, StreamDevice device) {
        dispatch("on_stream_end", chat, type, device);
    }

    @Override
    public void onSubchainRequest(long chat, SubchainRequest request) {
        dispatch("on_subchain_request", chat, request);
    }

    @Override
    public void onUpdateEmojis(long chat, String emojis) {
        dispatch("on_update_emojis", chat, emojis);
    }

    @Override
    public void onUpgrade(long chat, MediaState state) {
        dispatch("on_upgrade", chat, state);
    }
}

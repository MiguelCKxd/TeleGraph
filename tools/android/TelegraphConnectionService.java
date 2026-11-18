package org.tgas.calls;

import android.content.ComponentName;
import android.content.Context;
import android.net.Uri;
import android.os.Bundle;
import android.telecom.Connection;
import android.telecom.ConnectionRequest;
import android.telecom.ConnectionService;
import android.telecom.DisconnectCause;
import android.telecom.PhoneAccount;
import android.telecom.PhoneAccountHandle;
import android.telecom.TelecomManager;
import java.util.concurrent.CompletableFuture;

/** Represents live Telegram calls without exposing contact identities to Telecom. */
public final class TelegraphConnectionService extends ConnectionService {
    private static final String TOKEN = "org.tgas.calls.TOKEN";
    private static Call current;

    // All entry points are called on Android's main thread.
    public static boolean report(Context context, String token, Runnable show,
                                 Runnable answer, Runnable disconnect) {
        if (current != null) {
            if (!current.token.equals(token)) disconnect.run();
            return true;
        }
        TelecomManager telecom = context.getSystemService(TelecomManager.class);
        if (telecom == null) return false;
        try {
            PhoneAccountHandle handle = register(context, telecom);
            if (!telecom.isIncomingCallPermitted(handle)) {
                disconnect.run();
                return true;
            }
            current = new Call(token, show, answer, disconnect);
            Bundle extras = new Bundle();
            extras.putString(TOKEN, token);
            telecom.addNewIncomingCall(handle, extras);
            return true;
        } catch (RuntimeException error) {
            finish(current);
            return false;
        }
    }

    public static CompletableFuture<Boolean> place(Context context, String token, Runnable disconnect) {
        CompletableFuture<Boolean> result = new CompletableFuture<>();
        TelecomManager telecom = context.getSystemService(TelecomManager.class);
        if (telecom == null) {
            result.complete(true);
            return result;
        }
        if (current != null) {
            result.complete(false);
            return result;
        }
        try {
            PhoneAccountHandle handle = register(context, telecom);
            if (!telecom.isOutgoingCallPermitted(handle)) {
                result.complete(false);
                return result;
            }
            Uri address = Uri.parse("sip:" + token + "@telegraph.invalid");
            Call call = new Call(token, null, null, disconnect);
            call.address = address;
            call.admission = result;
            current = call;
            Bundle extras = new Bundle();
            extras.putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE, handle);
            telecom.placeCall(address, extras);
        } catch (RuntimeException error) {
            finish(current);
            result.completeExceptionally(error);
        }
        return result;
    }

    private static PhoneAccountHandle register(Context context, TelecomManager telecom) {
        PhoneAccountHandle handle = new PhoneAccountHandle(
                new ComponentName(context, TelegraphConnectionService.class), "telegraph");
        telecom.registerPhoneAccount(PhoneAccount.builder(handle, "TeleGraph")
                .setCapabilities(PhoneAccount.CAPABILITY_SELF_MANAGED)
                .addSupportedUriScheme(PhoneAccount.SCHEME_SIP).build());
        return handle;
    }

    public static void update(String token, String state) {
        if (current == null || !current.token.equals(token)) return;
        if ("ended".equals(state) || "idle".equals(state)) finish(current);
        else if ("active".equals(state)) {
            current.active = true;
            if (current.connection != null) current.connection.setActive();
        }
    }

    public static void clear() {
        finish(current);
    }

    private static void finish(Call call) {
        if (call == null) return;
        if (current == call) current = null;
        if (call.admission != null) call.admission.complete(false);
        if (call.connection != null) {
            call.connection.setDisconnected(new DisconnectCause(DisconnectCause.LOCAL));
            call.connection.destroy();
        }
    }

    @Override
    public Connection onCreateIncomingConnection(PhoneAccountHandle handle, ConnectionRequest request) {
        Call call = forRequest(request);
        if (call == null || call.connection != null) {
            return Connection.createFailedConnection(new DisconnectCause(DisconnectCause.CANCELED));
        }
        return createConnection(call);
    }

    @Override
    public Connection onCreateOutgoingConnection(PhoneAccountHandle handle, ConnectionRequest request) {
        Call call = outgoingFor(request);
        if (call == null || call.connection != null) {
            return Connection.createFailedConnection(new DisconnectCause(DisconnectCause.CANCELED));
        }
        Connection connection = createConnection(call);
        call.admission.complete(true);
        return connection;
    }

    @Override
    public void onCreateOutgoingConnectionFailed(PhoneAccountHandle handle, ConnectionRequest request) {
        finish(outgoingFor(request));
    }

    private static Call outgoingFor(ConnectionRequest request) {
        return current != null && current.address != null && current.address.equals(request.getAddress())
                ? current : null;
    }

    private Connection createConnection(Call call) {
        Connection connection = new Connection() {
            @Override public void onShowIncomingCallUi() { if (current == call && !call.active && call.show != null) call.show.run(); }
            @Override public void onAnswer(int videoState) { if (current == call && !call.active && call.answer != null) call.answer.run(); }
            @Override public void onAnswer() { onAnswer(0); }
            @Override public void onReject() { if (current == call) call.disconnect.run(); }
            @Override public void onDisconnect() { if (current == call) call.disconnect.run(); }
            @Override public void onAbort() { if (current == call) call.disconnect.run(); }
        };
        call.connection = connection;
        connection.setConnectionProperties(Connection.PROPERTY_SELF_MANAGED);
        connection.setAudioModeIsVoip(true);
        if (call.active) connection.setActive();
        else if (call.admission != null) connection.setDialing();
        else connection.setRinging();
        return connection;
    }

    @Override
    public void onCreateIncomingConnectionFailed(PhoneAccountHandle handle, ConnectionRequest request) {
        Call call = forRequest(request);
        if (call != null) {
            finish(call);
            call.disconnect.run();
        }
    }

    private static Call forRequest(ConnectionRequest request) {
        Bundle extras = request.getExtras();
        return current != null && current.admission == null && extras != null && current.token.equals(extras.getString(TOKEN))
                ? current : null;
    }

    private static final class Call {
        final String token;
        final Runnable show;
        final Runnable answer;
        final Runnable disconnect;
        boolean active;
        Uri address;
        CompletableFuture<Boolean> admission;
        Connection connection;

        Call(String token, Runnable show, Runnable answer, Runnable disconnect) {
            this.token = token;
            this.show = show;
            this.answer = answer;
            this.disconnect = disconnect;
        }
    }
}

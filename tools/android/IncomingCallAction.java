package org.tgas.calls;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import java.util.Objects;

/** The notification may decline only the exact call that produced its action. */
public final class IncomingCallAction extends BroadcastReceiver {
    private static Uri current;
    private static Runnable decline;

    public static void setDecline(Uri uri, Runnable action) {
        current = uri;
        decline = action;
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        if (decline == null || !Objects.equals(current, intent.getData())) return;
        Runnable action = decline;
        setDecline(null, null);
        action.run();
    }
}

package org.tgas.calls;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import java.util.concurrent.CompletableFuture;

/** Owns the foreground media entitlements for one live Telegram call. */
public final class CallMediaService extends Service {
    private static final String CHANNEL = "active-calls";
    private static String owner;
    private static CompletableFuture<Boolean> ready;
    private static CallMediaService running;
    private String serviceToken;
    private Notification notification;
    private int audioTypes;

    public static synchronized CompletableFuture<Boolean> begin(Context context, String token, String label,
                                                                boolean microphone, boolean phoneCall, boolean camera) {
        if (token.equals(owner)) return ready;
        CompletableFuture<Boolean> result = new CompletableFuture<>();
        if (owner != null) {
            result.complete(false);
            return result;
        }
        owner = token;
        ready = result;
        Intent intent = new Intent(context, CallMediaService.class).putExtra("token", token)
                .putExtra("label", label).putExtra("microphone", microphone)
                .putExtra("phoneCall", phoneCall).putExtra("camera", camera);
        try {
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent);
            else context.startService(intent);
        } catch (RuntimeException error) {
            owner = null;
            ready = null;
            result.completeExceptionally(error);
        }
        return result;
    }

    public static synchronized boolean setCamera(String token, boolean enabled) {
        if (!token.equals(owner) || running == null || !token.equals(running.serviceToken)) {
            return false;
        }
        running.promote(enabled);
        return true;
    }

    private void promote(boolean camera) {
        if (Build.VERSION.SDK_INT >= 29) {
            int type = audioTypes;
            if (Build.VERSION.SDK_INT >= 30 && camera) type |= ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA;
            startForeground(3, notification, type);
        } else {
            startForeground(3, notification);
        }
    }

    public static synchronized void end(Context context, String token) {
        if (!token.equals(owner)) return;
        ready.complete(false);
        owner = null;
        ready = null;
        context.stopService(new Intent(context, CallMediaService.class));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        synchronized (CallMediaService.class) {
            if (owner == null || intent == null || !owner.equals(intent.getStringExtra("token"))) {
                stopSelf(startId);
                return START_NOT_STICKY;
            }
            try {
                String label = intent.getStringExtra("label");
                Notification.Builder builder;
                if (Build.VERSION.SDK_INT >= 26) {
                    getSystemService(NotificationManager.class).createNotificationChannel(
                            new NotificationChannel(CHANNEL, label, NotificationManager.IMPORTANCE_LOW));
                    builder = new Notification.Builder(this, CHANNEL);
                } else {
                    builder = new Notification.Builder(this);
                }
                Intent open = org.tgas.launcher.LauncherActivity.mainIntent(this);
                builder.setContentIntent(PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE));
                notification = builder.setSmallIcon(org.tgas.tg_ascii_mobile.R.drawable.ic_telegraph_notification)
                        .setContentTitle(label).setCategory(Notification.CATEGORY_CALL).setOngoing(true).build();
                audioTypes = intent.getBooleanExtra("phoneCall", false)
                        ? ServiceInfo.FOREGROUND_SERVICE_TYPE_PHONE_CALL
                        : ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK;
                if (Build.VERSION.SDK_INT >= 30 && intent.getBooleanExtra("microphone", false)) {
                    audioTypes |= ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE;
                }
                promote(intent.getBooleanExtra("camera", false));
                serviceToken = owner;
                running = this;
                ready.complete(true);
            } catch (RuntimeException error) {
                ready.completeExceptionally(error);
                owner = null;
                ready = null;
                stopSelf(startId);
            }
        }
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        synchronized (CallMediaService.class) {
            if (running == this) running = null;
            if (serviceToken != null && serviceToken.equals(owner)) {
                ready.complete(false);
                owner = null;
                ready = null;
            }
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}

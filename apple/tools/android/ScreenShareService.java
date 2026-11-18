package org.tgas.calls;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.media.projection.MediaProjection;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.concurrent.CompletableFuture;
import io.github.pytgcalls.devices.JavaVideoCapturerModule;

public final class ScreenShareService extends Service {
    private static final String CHANNEL = "screen-sharing";
    private static CompletableFuture<Boolean> pending;
    private static int generation;
    private static Runnable stopped;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private int requestId;
    private MediaProjection projection;
    private MediaProjection.Callback projectionCallback;

    // NTgCalls 3.0.5 owns the projection and offers no Android stop hook.
    // Observe its WebRTC projection directly without consuming the consent twice.
    private static MediaProjection currentProjection(Field sources, Field capturer, Method projectionGetter)
            throws ReflectiveOperationException {
        for (Object source : (Object[]) sources.get(null)) {
            if (source == null) continue;
            Object video = capturer.get(source);
            if (projectionGetter.getDeclaringClass().isInstance(video)) {
                MediaProjection current = (MediaProjection) projectionGetter.invoke(video);
                if (current != null) return current;
            }
        }
        return null;
    }

    private static void watchProjection(ScreenShareService service, int request, Field sources,
                                        Field capturer, Method projectionGetter, MediaProjection previous, long deadline) {
        synchronized (ScreenShareService.class) {
            if (request != generation || stopped == null) return;
            try {
                MediaProjection current = currentProjection(sources, capturer, projectionGetter);
                if (current != null && current != previous) {
                    MediaProjection.Callback callback = new MediaProjection.Callback() {
                        @Override public void onStop() { notifyStopped(request); }
                    };
                    current.registerCallback(callback, MAIN);
                    service.projection = current;
                    service.projectionCallback = callback;
                    return;
                }
            } catch (ReflectiveOperationException | RuntimeException error) {
                notifyStopped(request);
                return;
            }
            if (SystemClock.uptimeMillis() >= deadline) {
                notifyStopped(request);
            } else {
                MAIN.postDelayed(() -> watchProjection(service, request, sources, capturer, projectionGetter, previous, deadline), 50);
            }
        }
    }

    private static synchronized void notifyStopped(int request) {
        if (request != generation || stopped == null) return;
        Runnable callback = stopped;
        stopped = null;
        callback.run();
    }

    public static synchronized CompletableFuture<Boolean> begin(Context context, Intent consent, String label, Runnable onStopped) {
        if (pending != null) throw new IllegalStateException("Screen sharing is already starting");
        CompletableFuture<Boolean> result = new CompletableFuture<>();
        pending = result;
        stopped = onStopped;
        Intent service = new Intent(context, ScreenShareService.class)
                .putExtra("consent", consent).putExtra("label", label).putExtra("request", ++generation);
        try {
            context.startForegroundService(service);
        } catch (RuntimeException error) {
            pending = null;
            stopped = null;
            result.completeExceptionally(error);
        }
        return result;
    }

    public static synchronized void end(Context context) {
        stopped = null;
        generation++;
        if (pending != null) {
            pending.complete(false);
            pending = null;
        }
        JavaVideoCapturerModule.setMediaProjectionPermissionResult(null);
        context.stopService(new Intent(context, ScreenShareService.class));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        synchronized (ScreenShareService.class) {
            Intent consent = intent == null ? null : intent.getParcelableExtra("consent");
            if (pending == null || consent == null || intent.getIntExtra("request", -1) != generation) {
                stopSelf(startId);
                return START_NOT_STICKY;
            }
            try {
                String label = intent.getStringExtra("label");
                getSystemService(NotificationManager.class).createNotificationChannel(
                        new NotificationChannel(CHANNEL, label, NotificationManager.IMPORTANCE_LOW));
                Notification notification = new Notification.Builder(this, CHANNEL)
                        .setSmallIcon(org.tgas.tg_ascii_mobile.R.drawable.ic_telegraph_notification).setContentTitle(label).setOngoing(true).build();
                if (Build.VERSION.SDK_INT >= 29) {
                    startForeground(2, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
                } else {
                    startForeground(2, notification);
                }
                Class<?> mediaSource = Class.forName("io.github.pytgcalls.devices.SmartVideoSource");
                Field sources = mediaSource.getDeclaredField("instance");
                Field capturer = mediaSource.getDeclaredField("videoCapturer");
                sources.setAccessible(true);
                capturer.setAccessible(true);
                Method projectionGetter = Class.forName("org.webrtc.ScreenCapturerAndroid")
                        .getMethod("getMediaProjection");
                MediaProjection previous = currentProjection(sources, capturer, projectionGetter);
                JavaVideoCapturerModule.setMediaProjectionPermissionResult(consent);
                int request = requestId = generation;
                MAIN.post(() -> watchProjection(this, request, sources, capturer, projectionGetter, previous,
                        SystemClock.uptimeMillis() + 25_000));
                pending.complete(true);
            } catch (ReflectiveOperationException | RuntimeException error) {
                stopped = null;
                pending.completeExceptionally(error);
                stopSelf(startId);
            } finally {
                pending = null;
            }
        }
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        if (projection != null) projection.unregisterCallback(projectionCallback);
        notifyStopped(requestId);
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}

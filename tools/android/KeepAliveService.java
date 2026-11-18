package org.tgas.keepalive;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

/**
 * Keeps TeleGraph's process (and its Telegram connection, run by the app's
 * Python core) alive in the background while "Keep connected in the
 * background" is on. Shows the permanent notification Android requires.
 * It holds no data and does no work of its own.
 */
public class KeepAliveService extends Service {
    private static final String CHANNEL = "connection";

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String title = intent != null && intent.getStringExtra("title") != null ? intent.getStringExtra("title") : "TeleGraph";
        String text = intent != null && intent.getStringExtra("text") != null ? intent.getStringExtra("text") : "";
        String channelName = intent != null && intent.getStringExtra("channel") != null ? intent.getStringExtra("channel") : "TeleGraph";
        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager manager = getSystemService(NotificationManager.class);
            manager.createNotificationChannel(new NotificationChannel(CHANNEL, channelName, NotificationManager.IMPORTANCE_MIN));
            builder = new Notification.Builder(this, CHANNEL);
        } else {
            builder = new Notification.Builder(this);
        }
        Intent open = org.tgas.launcher.LauncherActivity.mainIntent(this);
        PendingIntent pending = PendingIntent.getActivity(this, 1, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification notification = builder.setSmallIcon(org.tgas.tg_ascii_mobile.R.drawable.ic_telegraph_notification).setContentTitle(title)
                .setContentText(text).setOngoing(true).setContentIntent(pending).build();
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING);
        } else {
            startForeground(1, notification);
        }
        // Not sticky: without the app's process there is no connection to keep.
        return START_NOT_STICKY;
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        // Swiping the app away from recents keeps the service (and the connection).
        super.onTaskRemoved(rootIntent);
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}

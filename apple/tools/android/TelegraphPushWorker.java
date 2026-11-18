package org.tgas.push;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import androidx.work.Worker;
import androidx.work.WorkerParameters;

import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import com.google.android.gms.tasks.Tasks;
import com.google.firebase.messaging.FirebaseMessaging;
import com.chaquo.python.android.AndroidPlatform;

import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;

/** Verify a wake-up hint against the authorized Telegram session, even before a window opens. */
public final class TelegraphPushWorker extends Worker {
    public TelegraphPushWorker(Context context, WorkerParameters parameters) {
        super(context, parameters);
    }

    @Override
    public Result doWork() {
        String hint = getInputData().getString("hint");
        boolean refresh = getInputData().getBoolean("refreshToken", false);
        if ((!refresh && hint == null) || System.currentTimeMillis() > getInputData().getLong("expires", Long.MAX_VALUE)) {
            return Result.success();
        }
        Context context = getApplicationContext();
        try {
            // MainActivity starts Chaquopy on this same looper. Serialize only its initialization.
            if (!Python.isStarted()) {
                FutureTask<Void> start = new FutureTask<>(() -> {
                    if (!Python.isStarted()) {
                        AndroidPlatform platform = new AndroidPlatform(context);
                        platform.redirectStdioToLogcat();
                        Python.start(platform);
                    }
                    return null;
                });
                new Handler(Looper.getMainLooper()).post(start);
                start.get(25, TimeUnit.SECONDS);
            }
            PyObject runtime = Python.getInstance().getModule("tg_ascii_mobile.runtime");
            int status;
            if (refresh) {
                String token = Tasks.await(FirebaseMessaging.getInstance().getToken(), 20, TimeUnit.SECONDS);
                status = runtime.callAttr("android_refresh_token", context, token).toInt();
            } else {
                status = runtime.callAttr("android_push", context, hint).toInt();
            }
            if (status != 2) {
                return Result.success();
            }
        } catch (InterruptedException stopped) {
            Thread.currentThread().interrupt();
        } catch (Exception unavailable) {
            // Session data, provider tokens and notification payloads must stay out of system logs.
        }
        return getRunAttemptCount() < 4 ? Result.retry() : Result.failure();
    }
}

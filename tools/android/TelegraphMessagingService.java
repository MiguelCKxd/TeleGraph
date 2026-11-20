package org.tgas.push;

import android.os.Build;

import androidx.work.Constraints;
import androidx.work.Data;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.OutOfQuotaPolicy;
import androidx.work.WorkManager;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

import org.json.JSONException;
import org.json.JSONObject;

/** Forwards provider hints to the Telegram core through a system-managed background job. */
public final class TelegraphMessagingService extends FirebaseMessagingService {
    @Override
    public void onMessageReceived(RemoteMessage message) {
        if (message.getData().isEmpty()) {
            return;
        }
        try {
            JSONObject payload = new JSONObject(message.getData());
            if (payload.has("data")) {
                payload = new JSONObject(payload.getString("data"));
            }
            JSONObject hint = notificationHint(payload, message.getSentTime());
            if (hint == null) {
                return;
            }
            Data.Builder input = new Data.Builder().putString("hint", hint.toString());
            if (message.getTtl() > 0 && message.getSentTime() > 0) {
                input.putLong("expires", message.getSentTime() + message.getTtl() * 1000L);
            }
            OneTimeWorkRequest.Builder job = new OneTimeWorkRequest.Builder(TelegraphPushWorker.class)
                    .setInputData(input.build()).setConstraints(new Constraints.Builder()
                            .setRequiredNetworkType(NetworkType.CONNECTED).build());
            if (Build.VERSION.SDK_INT >= 31 && message.getPriority() == RemoteMessage.PRIORITY_HIGH) {
                job.setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST);
            }
            WorkManager.getInstance(this).enqueue(job.build());
        } catch (JSONException malformed) {
            // Drop the malformed hint without logging message data.
        }
    }

    static JSONObject notificationHint(JSONObject payload, long sentAtMillis) throws JSONException {
        long account = payload.optLong("user_id");
        if (payload.has("user_id") && account <= 0) {
            return null;
        }
        String kind = payload.optString("loc_key");
        if (kind.equals("SESSION_REVOKE") || kind.equals("MESSAGE_MUTED") || kind.equals("DC_UPDATE")
                || kind.startsWith("READ_") || kind.startsWith("DELETE_") || kind.startsWith("PHONE_CALL")) {
            return null;
        }
        JSONObject hint = new JSONObject();
        if (account > 0) {
            hint.put("user_id", account);
        }
        JSONObject custom = payload.optJSONObject("custom");
        if (payload.opt("custom") instanceof String) {
            custom = new JSONObject(payload.getString("custom"));
        }
        // Only routing IDs are allowed in WorkManager's persistent database.
        if (account > 0 && custom != null && custom.optLong("msg_id") > 0) {
            JSONObject route = new JSONObject();
            for (String field : new String[]{"channel_id", "chat_id", "from_id"}) {
                long id = custom.optLong(field);
                if (id > 0) {
                    route.put(field, id);
                }
            }
            if (route.length() > 0) {
                route.put("msg_id", custom.optLong("msg_id"));
                hint.put("custom", route);
                if (kind.matches("[A-Z0-9_]{1,80}")) {
                    hint.put("loc_key", kind);
                }
                return hint;
            }
        }
        // Telegram can provide just the recipient in multi-account mode, or just a badge.
        if (!kind.isEmpty() || sentAtMillis < 1000L || (account <= 0 && payload.optLong("badge", -1) < 0)) {
            return null;
        }
        return hint.put("badge_sent_at", sentAtMillis / 1000L);
    }

    @Override
    public void onNewToken(String token) {
        // Resolve the current token at execution time instead of storing a credential in the job.
        OneTimeWorkRequest job = new OneTimeWorkRequest.Builder(TelegraphPushWorker.class)
                .setInputData(new Data.Builder().putBoolean("refreshToken", true).build())
                .setConstraints(new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build();
        WorkManager.getInstance(this).enqueueUniqueWork("telegraph-fcm-token", ExistingWorkPolicy.REPLACE, job);
    }
}

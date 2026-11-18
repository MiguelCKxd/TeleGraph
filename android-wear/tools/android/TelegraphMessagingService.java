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
            if (payload.opt("custom") instanceof String) {
                payload.put("custom", new JSONObject(payload.getString("custom")));
            }
            long account = payload.optLong("user_id");
            // Some Telegram apps receive only a badge: there is no account or peer in that delivery.
            JSONObject hint = new JSONObject();
            if (account > 0) {
                hint.put("user_id", account);
            } else if (payload.has("badge") && payload.optLong("badge", -1) >= 0 && message.getSentTime() > 0) {
                hint.put("badge_sent_at", message.getSentTime() / 1000L);
            } else {
                return;
            }
            // WorkManager persists its inputs. Keep routing IDs only, never contact names or text.
            String kind = payload.optString("loc_key");
            if (kind.matches("[A-Z0-9_]{1,80}")) {
                hint.put("loc_key", kind);
            }
            JSONObject custom = payload.optJSONObject("custom");
            if (custom != null) {
                JSONObject route = new JSONObject();
                for (String field : new String[]{"from_id", "channel_id", "chat_id", "msg_id"}) {
                    long value = custom.optLong(field);
                    if (value > 0) {
                        route.put(field, value);
                    }
                }
                hint.put("custom", route);
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

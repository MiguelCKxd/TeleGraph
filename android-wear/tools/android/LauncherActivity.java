package org.tgas.launcher;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.os.Build;
import android.app.Person;
import android.content.SharedPreferences;
import android.content.pm.ShortcutInfo;
import android.content.pm.ShortcutManager;
import android.graphics.drawable.Icon;
import java.util.ArrayList;
import java.util.List;

import org.beeware.android.MainActivity;

/** Keep the running app and its notifications independent of the active icon alias. */
public final class LauncherActivity extends Activity {
    public static Intent mainIntent(Context context) {
        return Intent.makeMainActivity(new ComponentName(context, MainActivity.class))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    }

    private static final String PREFIX = "telegraph-chat:";
    private static final String HOME_SHORTCUT = "telegraph-home";
    private static final String OPEN = "org.tgas.launcher.OPEN_CONVERSATION";
    private static final String PENDING = "pending";
    private static volatile Runnable onConversation;

    public static void setConversationListener(Runnable listener) {
        onConversation = listener;
    }

    /** Update our single named Home shortcut, or ask the launcher to pin it on user request. */
    public static void updateHomeShortcut(Activity activity, String title, boolean requestPin) {
        if (Build.VERSION.SDK_INT < 26) return;
        ShortcutManager manager = activity.getSystemService(ShortcutManager.class);
        if (manager == null) return;
        try {
            ShortcutInfo pinned = null;
            for (ShortcutInfo item : manager.getPinnedShortcuts()) {
                if (HOME_SHORTCUT.equals(item.getId())) {
                    pinned = item;
                    break;
                }
            }
            if (pinned == null && (!requestPin || !manager.isRequestPinShortcutSupported())) return;
            Intent launcher = activity.getPackageManager().getLaunchIntentForPackage(activity.getPackageName());
            if (launcher == null || launcher.getComponent() == null) return;
            ComponentName alias = launcher.getComponent();
            if (pinned != null && title.contentEquals(pinned.getShortLabel()) && alias.equals(pinned.getActivity())) return;
            int icon = activity.getPackageManager().getActivityInfo(alias, 0).getIconResource();
            ShortcutInfo.Builder builder = new ShortcutInfo.Builder(activity, HOME_SHORTCUT)
                    .setShortLabel(title).setLongLabel(title).setActivity(alias)
                    .setIntent(mainIntent(activity));
            if (icon != 0) builder.setIcon(Icon.createWithResource(activity, icon));
            ShortcutInfo shortcut = builder.build();
            if (pinned != null) manager.updateShortcuts(java.util.Collections.singletonList(shortcut));
            else manager.requestPinShortcut(shortcut, null);
        } catch (android.content.pm.PackageManager.NameNotFoundException | IllegalStateException | SecurityException ignored) {
            // The home app can change, or shortcuts can be unavailable while the user is locked.
        }
    }

    private static SharedPreferences routes(Context context) {
        return context.getSharedPreferences("notification-conversations", Context.MODE_PRIVATE);
    }

    public static Intent conversationIntent(Context context, String id) {
        return new Intent(context, LauncherActivity.class).setAction(OPEN).putExtra("conversation", id);
    }

    public static String publishConversation(Context context, String account, long peer, String label,
                                             Person person, Icon icon) {
        if (Build.VERSION.SDK_INT < 30) return null;
        String id = PREFIX + account + ":" + peer;
        ShortcutManager manager = context.getSystemService(ShortcutManager.class);
        if (manager == null) return null;
        ShortcutInfo.Builder shortcut = new ShortcutInfo.Builder(context, id).setShortLabel(label)
                .setIntent(conversationIntent(context, id)).setPerson(person).setLongLived(true);
        if (icon != null) shortcut.setIcon(icon);
        manager.enableShortcuts(java.util.Collections.singletonList(id));
        manager.pushDynamicShortcut(shortcut.build());
        SharedPreferences prefs = routes(context);
        if (!prefs.getBoolean(id, false) && !prefs.edit().putBoolean(id, true).commit()) return null;
        return id;
    }

    public static void forgetConversations(Context context, String account, String peer) {
        if (Build.VERSION.SDK_INT < 30) return;
        String prefix = account == null ? PREFIX : PREFIX + account + ":";
        SharedPreferences prefs = routes(context);
        List<String> removed = new ArrayList<>();
        SharedPreferences.Editor edit = prefs.edit();
        for (String id : prefs.getAll().keySet()) {
            if (id.startsWith(prefix) && (peer == null || id.equals(prefix + peer))) {
                removed.add(id);
                edit.remove(id);
            }
        }
        if (removed.isEmpty()) return;
        if (removed.contains(prefs.getString(PENDING, null))) edit.remove(PENDING);
        edit.apply();
        ShortcutManager manager = context.getSystemService(ShortcutManager.class);
        manager.disableShortcuts(removed);
        manager.removeLongLivedShortcuts(removed);
    }

    public static synchronized String takeConversation(Context context) {
        SharedPreferences prefs = routes(context);
        String id = prefs.getString(PENDING, null);
        if (id == null) return null;
        prefs.edit().remove(PENDING).apply();
        return prefs.getBoolean(id, false) ? id.substring(PREFIX.length()) : null;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent launch = getIntent();
        boolean opened = false;
        if (OPEN.equals(launch.getAction()) && new ComponentName(this, LauncherActivity.class).equals(launch.getComponent())) {
            String id = launch.getStringExtra("conversation");
            if (id != null && id.startsWith(PREFIX) && routes(this).getBoolean(id, false)) {
                opened = routes(this).edit().putString(PENDING, id).commit();
            }
        }
        startActivity(mainIntent(this));
        Runnable listener = onConversation;
        if (opened && listener != null) new android.os.Handler(getMainLooper()).post(listener);
        finish();
    }
}

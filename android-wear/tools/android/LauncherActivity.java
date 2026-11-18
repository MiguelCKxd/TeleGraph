package org.tgas.launcher;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;

import org.beeware.android.MainActivity;

/** Keep the running app and its notifications independent of the active icon alias. */
public final class LauncherActivity extends Activity {
    public static Intent mainIntent(Context context) {
        return Intent.makeMainActivity(new ComponentName(context, MainActivity.class))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        startActivity(mainIntent(this));
        finish();
    }
}

package org.tgas.calls;

import android.app.Activity;
import android.app.PictureInPictureParams;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.util.Rational;
import android.view.WindowManager;
import android.widget.ImageView;

import org.tgas.launcher.LauncherActivity;

/** A separate task ensures that only the current call's video can appear in system PiP. */
public final class CallPipActivity extends Activity {
    private static String owner;
    private static CallPipActivity window;
    private static int state;
    private ImageView picture;
    private String token;
    private boolean entered;

    public static boolean supported(Activity activity) {
        return Build.VERSION.SDK_INT >= 26 && activity.getPackageManager()
                .hasSystemFeature(PackageManager.FEATURE_PICTURE_IN_PICTURE);
    }

    // open, frame, close, and lifecycle callbacks all run on the UI thread.
    public static boolean open(Activity activity, String token) {
        if (!supported(activity) || activity.isFinishing() || owner != null) return false;
        owner = token;
        state = 1;
        try {
            activity.startActivity(new Intent(activity, CallPipActivity.class)
                    .putExtra("owner", token).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            return true;
        } catch (RuntimeException error) {
            close(token);
            return false;
        }
    }

    public static int status(String token) {
        return token.equals(owner) ? state : 0;
    }

    public static void frame(String token, byte[] jpeg) {
        if (!token.equals(owner) || window == null || window.picture == null) return;
        Bitmap image = jpeg == null ? null : BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length);
        window.picture.setImageBitmap(image);
    }

    public static void close(String token) {
        if (!token.equals(owner)) return;
        CallPipActivity previous = window;
        window = null;
        owner = null;
        state = 0;
        if (previous != null) {
            previous.picture.setImageDrawable(null);
            previous.finishAndRemoveTask();
        }
    }

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        token = getIntent().getStringExtra("owner");
        if (token == null || !token.equals(owner)) {
            finishAndRemoveTask();
            return;
        }
        window = this;
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        picture = new ImageView(this);
        picture.setScaleType(ImageView.ScaleType.FIT_CENTER);
        picture.setBackgroundColor(Color.BLACK);
        setContentView(picture);
    }

    @Override protected void onPostResume() {
        super.onPostResume();
        if (window != this || entered) return;
        picture.post(() -> {
            if (window != this || entered || isFinishing()) return;
            try {
                if (!enterPictureInPictureMode(new PictureInPictureParams.Builder()
                        .setAspectRatio(new Rational(16, 9)).build())) close(token);
            } catch (IllegalStateException | IllegalArgumentException error) {
                close(token);
            }
        });
    }

    @Override public void onPictureInPictureModeChanged(boolean inPip, Configuration configuration) {
        super.onPictureInPictureModeChanged(inPip, configuration);
        if (window != this) return;
        if (inPip) {
            entered = true;
            state = 2;
        } else if (entered && !isFinishing()) {
            // Tapping expand returns to the same Telegram call in the main task.
            if (!isDestroyed() && !isChangingConfigurations() && !isStoppedForDismissal) {
                startActivity(LauncherActivity.mainIntent(this));
            }
            close(token);
        }
    }

    private boolean isStoppedForDismissal;
    @Override protected void onStop() {
        super.onStop();
        isStoppedForDismissal = true;
        if (entered && window == this) close(token);
    }

    @Override protected void onDestroy() {
        if (window == this) {
            owner = null;
            state = 0;
            window = null;
        }
        super.onDestroy();
    }
}

package org.tgas.windows;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.ViewGroup;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * One chat in its own system window: a separate Android task (split screen,
 * free-form windows, the recents list), showing the app's local page in its
 * "window" mode. The page talks to the running core like the main window.
 */
public final class ChatWindowActivity extends Activity {
    private static final String EXTRA_URL = "org.tgas.windows.URL";
    private static final String EXTRA_TITLE = "org.tgas.windows.TITLE";
    private WebView web;

    /** Opens (or brings back) the window of one chat. */
    public static void open(Context context, long peer, String title, String account, String url) {
        Intent intent = new Intent(context, ChatWindowActivity.class);
        // One task per chat: opening it again returns to the same window.
        intent.setData(new Uri.Builder().scheme("tgas-window").authority("chat")
                .appendPath(account).appendPath(Long.toString(peer)).build());
        intent.putExtra(EXTRA_URL, url);
        intent.putExtra(EXTRA_TITLE, title);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NEW_DOCUMENT
                | Intent.FLAG_ACTIVITY_LAUNCH_ADJACENT);
        context.startActivity(intent);
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        String url = getIntent().getStringExtra(EXTRA_URL);
        String title = getIntent().getStringExtra(EXTRA_TITLE);
        if (url == null || !url.startsWith("http://127.0.0.1:")) {
            finish();
            return;
        }
        if (title != null) {
            setTitle(title);
            setTaskDescription(new android.app.ActivityManager.TaskDescription(title));
        }
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#08100c"));
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                // Only the app's own local page; anything else opens outside.
                Uri target = request.getUrl();
                if ("127.0.0.1".equals(target.getHost())) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, target));
                } catch (RuntimeException ignored) {
                }
                return true;
            }
        });
        // Match the main window: one native inset reservation, also on API 35+.
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        setContentView(web);
        ViewCompat.setOnApplyWindowInsetsListener(web, (view, insets) -> {
            Insets occupied = insets.getInsets(WindowInsetsCompat.Type.systemBars()
                    | WindowInsetsCompat.Type.displayCutout() | WindowInsetsCompat.Type.ime());
            ViewGroup.MarginLayoutParams lp = (ViewGroup.MarginLayoutParams) view.getLayoutParams();
            if (lp.leftMargin != occupied.left || lp.topMargin != occupied.top
                    || lp.rightMargin != occupied.right || lp.bottomMargin != occupied.bottom) {
                lp.setMargins(occupied.left, occupied.top, occupied.right, occupied.bottom);
                view.setLayoutParams(lp);
            }
            return insets;
        });
        ViewCompat.requestApplyInsets(web);
        if (state != null) {
            web.restoreState(state);
        } else {
            web.loadUrl(url);
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle state) {
        super.onSaveInstanceState(state);
        if (web != null) {
            web.saveState(state);
        }
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.loadUrl("about:blank");  // fires the page's pagehide: the core forgets this window
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}

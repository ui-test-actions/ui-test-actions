package dev.uitest.sessionime;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.inputmethodservice.InputMethodService;
import android.os.Build;
import android.util.Base64;
import android.view.inputmethod.InputConnection;
import java.nio.charset.StandardCharsets;

public final class SessionIme extends InputMethodService {
    private static final String ACTION = "dev.uitest.sessionime.OPERATION";
    private static final int OK = 42;
    private static final int NO_FOCUS = 43;
    private static final int REJECTED = 44;
    private static final int MAX_ENCODED_TEXT = 21848;

    private final BroadcastReceiver commands = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            try {
                setResultCode(dispatch(intent, this));
            } catch (IllegalArgumentException | IllegalStateException | SecurityException ex) {
                setResultCode(REJECTED);
            }
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        IntentFilter filter = new IntentFilter(ACTION);
        // The adb shell holds DUMP. Ordinary installed apps cannot submit commands.
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(commands, filter, Manifest.permission.DUMP, null, Context.RECEIVER_EXPORTED);
        } else {
            registerReceiver(commands, filter, Manifest.permission.DUMP, null);
        }
    }

    @Override
    public void onDestroy() {
        unregisterReceiver(commands);
        super.onDestroy();
    }

    @Override
    public boolean onEvaluateInputViewShown() {
        return false;
    }

    private int dispatch(Intent intent, BroadcastReceiver reply) {
        String operation = intent.getStringExtra("operation");
        if ("ping".equals(operation)) {
            return OK;
        }
        if ("clipboard.get".equals(operation)) {
            ClipboardManager clipboard = getSystemService(ClipboardManager.class);
            ClipData clip = clipboard.getPrimaryClip();
            CharSequence text = clip == null ? "" : clip.getItemAt(0).getText();
            if (text == null) {
                return REJECTED;
            }
            byte[] bytes = text.toString().getBytes(StandardCharsets.UTF_8);
            if (bytes.length > 16384) {
                return REJECTED;
            }
            reply.setResultData(Base64.encodeToString(bytes, Base64.NO_WRAP));
            return OK;
        }
        String encoded = intent.getStringExtra("payload");
        if (encoded == null || encoded.length() > MAX_ENCODED_TEXT) {
            return REJECTED;
        }
        String text = new String(Base64.decode(encoded, Base64.NO_WRAP), StandardCharsets.UTF_8);
        if ("clipboard.set".equals(operation)) {
            getSystemService(ClipboardManager.class).setPrimaryClip(ClipData.newPlainText("UI test", text));
            return OK;
        }
        if ("text.insert".equals(operation) || "text.replace".equals(operation)) {
            InputConnection connection = getCurrentInputConnection();
            if (connection == null) {
                return NO_FOCUS;
            }
            if ("text.replace".equals(operation) && !connection.performContextMenuAction(android.R.id.selectAll)) {
                return REJECTED;
            }
            return connection.commitText(text, 1) ? OK : REJECTED;
        }
        return REJECTED;
    }
}

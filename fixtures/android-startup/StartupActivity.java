package dev.uitest.startup;

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;
import android.widget.TextView;

public final class StartupActivity extends Activity {
    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        String mode = getIntent().getStringExtra("mode");
        Log.i("StartupFixture", "mode=" + mode);
        switch (mode == null ? "normal" : mode) {
            case "finish":
                finishAndRemoveTask();
                return;
            case "java":
                throw new IllegalStateException("StartupFixture synthetic Java failure");
            case "native":
                System.loadLibrary("startupfixture");
                abortForTest();
                return;
            case "exit":
                System.exit(23);
                return;
            default:
                TextView view = new TextView(this);
                view.setText("Startup fixture ready");
                setContentView(view);
        }
    }

    private static native void abortForTest();
}

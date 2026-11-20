package dev.uitest.fixture;

import android.app.Activity;
import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public class MainActivity extends Activity {
    private ScaleGestureDetector pinch;
    private TextView status;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(32, 68, 32, 28);
        root.setBackgroundColor(Color.rgb(25, 43, 66));
        root.setFocusableInTouchMode(true);

        TextView label = new TextView(this);
        status = label;
        pinch = new ScaleGestureDetector(this, new ScaleGestureDetector.SimpleOnScaleGestureListener() {
            private float scale;

            @Override public boolean onScaleBegin(ScaleGestureDetector detector) {
                scale = 1;
                return true;
            }

            @Override public boolean onScale(ScaleGestureDetector detector) {
                scale *= detector.getScaleFactor();
                if (scale > 1.15f) status.setText("Pinch expanded");
                if (scale < .85f) status.setText("Pinch contracted");
                return true;
            }
        });
        label.setText("BEFORE · Ready for input");
        label.setTextColor(Color.WHITE);
        label.setTextSize(21);
        root.addView(label);

        EditText entry = new EditText(this);
        entry.setSingleLine();
        entry.setHint("Enter test text");
        entry.setTextColor(Color.WHITE);
        entry.setHintTextColor(Color.LTGRAY);
        root.addView(entry, new LinearLayout.LayoutParams(-1, -2));

        Button apply = new Button(this);
        apply.setText("Apply change");
        apply.setOnClickListener(view -> {
            label.setText("AFTER · " + (entry.length() == 0 ? "Button tapped" : entry.getText()));
            root.setBackgroundColor(Color.rgb(23, 99, 59));
            getSystemService(InputMethodManager.class).hideSoftInputFromWindow(entry.getWindowToken(), 0);
        });
        root.addView(apply);

        ScrollView scroll = new ScrollView(this);
        LinearLayout rows = new LinearLayout(this);
        rows.setOrientation(LinearLayout.VERTICAL);
        for (int number = 1; number <= 30; number++) {
            TextView row = new TextView(this);
            row.setText("Swipe row " + number);
            row.setTextColor(Color.WHITE);
            row.setTextSize(18);
            row.setPadding(0, 24, 0, 24);
            rows.addView(row);
        }
        scroll.addView(rows, new ViewGroup.LayoutParams(-1, -2));
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
        root.requestFocus();
        handleLink(getIntent());
    }

    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        if (pinch != null) pinch.onTouchEvent(event);
        return super.dispatchTouchEvent(event);
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleLink(intent);
    }

    private void handleLink(Intent intent) {
        if (intent.getData() != null && "ui-test-fixture".equals(intent.getData().getScheme())
                && "verify".equals(intent.getData().getHost())) {
            status.setText("Deep link opened");
        }
        if (intent.getData() != null && "ui-test-fixture".equals(intent.getData().getScheme())
                && "environment".equals(intent.getData().getHost())) {
            Configuration config = getResources().getConfiguration();
            String language = config.getLocales().get(0).toLanguageTag();
            String direction = config.getLayoutDirection() == View.LAYOUT_DIRECTION_RTL ? "RTL" : "LTR";
            String camera = checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
                    ? "granted" : "denied";
            String orientation = config.orientation == Configuration.ORIENTATION_LANDSCAPE ? "LANDSCAPE" : "PORTRAIT";
            status.setText(String.join("\n", language, direction, "Camera " + camera, orientation));
        }
    }
}

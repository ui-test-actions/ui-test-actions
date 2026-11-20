package dev.uitest.fixture;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.ViewGroup;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public class MainActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(32, 68, 32, 28);
        root.setBackgroundColor(Color.rgb(25, 43, 66));
        root.setFocusableInTouchMode(true);

        TextView label = new TextView(this);
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
    }
}

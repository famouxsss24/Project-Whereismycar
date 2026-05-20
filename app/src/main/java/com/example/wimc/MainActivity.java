package com.example.wimc;

import android.app.Activity;
import android.content.Context;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;

import com.bumptech.glide.Glide;
import com.google.firebase.database.DataSnapshot;
import com.google.firebase.database.DatabaseError;
import com.google.firebase.database.DatabaseReference;
import com.google.firebase.database.FirebaseDatabase;
import com.google.firebase.database.Query;
import com.google.firebase.database.ValueEventListener;
import com.robotemi.sdk.BatteryData;
import com.robotemi.sdk.Robot;
import com.robotemi.sdk.TtsRequest;
import com.robotemi.sdk.listeners.OnGoToLocationStatusChangedListener;
import com.robotemi.sdk.listeners.OnRobotReadyListener;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

public class MainActivity extends Activity
        implements OnRobotReadyListener,
                   OnGoToLocationStatusChangedListener,
                   Robot.TtsListener {

    private static final String DB_URL  = "https://wimc-51ff9-default-rtdb.asia-southeast1.firebasedatabase.app";
    private static final String DB_PATH = "parking_lot";
    private static final Pattern LAST4_PATTERN = Pattern.compile("^\\d{4}$");
    private static final long NAV_DELAY_MS = 2500;
    private static final long AUTO_RETURN_DELAY_MS = 15000;   // 안내 도착 후 15초 뒤 자동 복귀
    private static final int  LOW_BATTERY_THRESHOLD = 30;     // 30% 미만이면 충전 우선
    private static final String HOME_BASE = "home base";       // Temi 기본 충전소 waypoint

    private EditText etPlateNumber;
    private TextView tvStatus, tvZone, tvSelectLabel;
    private HorizontalScrollView scrollPlates;
    private LinearLayout llPlateImages;

    private Robot robot;
    private DatabaseReference dbRef;
    private boolean isRobotReady = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        etPlateNumber = findViewById(R.id.etPlateNumber);
        tvStatus      = findViewById(R.id.tvStatus);
        tvZone        = findViewById(R.id.tvZone);
        tvSelectLabel = findViewById(R.id.tvSelectLabel);
        scrollPlates  = findViewById(R.id.scrollPlates);
        llPlateImages = findViewById(R.id.llPlateImages);

        try {
            dbRef = FirebaseDatabase.getInstance(DB_URL).getReference(DB_PATH);
        } catch (Exception e) {
            updateStatus("Firebase 연결 실패");
        }

        robot = Robot.getInstance();

        Button btnSearch = findViewById(R.id.btnSearch);
        btnSearch.setOnClickListener(v -> {
            hideKeyboard();
            String last4 = etPlateNumber.getText().toString().trim();
            if (!LAST4_PATTERN.matcher(last4).matches()) {
                Toast.makeText(this, "숫자 4자리를 입력하세요", Toast.LENGTH_SHORT).show();
                return;
            }
            searchByLast4(last4);
        });
    }

    @Override
    protected void onStart() {
        super.onStart();
        robot.addOnRobotReadyListener(this);
        robot.addOnGoToLocationStatusChangedListener(this);
        robot.addTtsListener(this);
    }

    @Override
    protected void onStop() {
        super.onStop();
        robot.removeOnRobotReadyListener(this);
        robot.removeOnGoToLocationStatusChangedListener(this);
        robot.removeTtsListener(this);
    }

    @Override
    public void onRobotReady(boolean isReady) {
        isRobotReady = isReady;
        updateStatus(isReady ? "Temi 준비 완료" : "Temi 연결 대기 중...");
    }

    // ─── Firebase 검색 ─────────────────────────────────────────
    private void searchByLast4(String last4) {
        if (dbRef == null) { updateStatus("Firebase 미연결"); return; }

        resetResultUI();
        updateStatus("'" + last4 + "' 검색 중...");

        Query query = dbRef.orderByChild("last4").equalTo(last4);
        query.addListenerForSingleValueEvent(new ValueEventListener() {
            @Override
            public void onDataChange(@NonNull DataSnapshot snapshot) {
                if (!snapshot.exists()) {
                    updateStatus("해당 번호로 등록된 차량이 없습니다.");
                    speak("등록된 차량을 찾을 수 없습니다.");
                    return;
                }

                List<DataSnapshot> results = new ArrayList<>();
                for (DataSnapshot child : snapshot.getChildren()) results.add(child);

                if (results.size() == 1) {
                    navigateToZone(results.get(0));
                } else {
                    updateStatus("차량이 " + results.size() + "대 검색됐습니다. 본인 차량을 선택하세요.");
                    showPlateSelection(results);
                }
            }

            @Override
            public void onCancelled(@NonNull DatabaseError error) {
                updateStatus("Firebase 오류: " + error.getMessage());
            }
        });
    }

    // ─── 단일 결과 → 구역 표시 + 이동 ─────────────────────────────
    private void navigateToZone(DataSnapshot snapshot) {
        String zone  = snapshot.child("zone").getValue(String.class);
        String plate = snapshot.getKey();

        if (zone == null || zone.trim().isEmpty()) {
            updateStatus("구역 정보 없음 — 이동을 중단합니다.");
            speak("구역 정보를 찾을 수 없습니다.");
            return;
        }

        tvZone.setText(zone + " 구역");
        updateStatus(plate + " → " + zone + " 구역으로 이동합니다");
        speak(zone + " 구역으로 안내해 드리겠습니다.");

        startNavigationAfterDelay(zone);
    }

    // ─── 공통 이동 메서드 ─────────────────────────────────────────
    private void startNavigationAfterDelay(String zone) {
        if (zone == null || zone.trim().isEmpty()) {
            updateStatus("이동할 구역 정보가 없습니다.");
            return;
        }
        if (!isRobotReady) {
            updateStatus("Temi가 아직 준비되지 않았습니다.");
            return;
        }
        // Temi waypoint 이름은 내부적으로 소문자로 저장됨
        final String target = zone.trim().toLowerCase();
        new Handler(Looper.getMainLooper()).postDelayed(
                () -> robot.goTo(target), NAV_DELAY_MS);
    }

    // ─── 중복 결과 → 번호판 이미지 카드 표시 ───────────────────────
    private void showPlateSelection(List<DataSnapshot> results) {
        runOnUiThread(() -> {
            tvZone.setVisibility(View.GONE);
            tvSelectLabel.setVisibility(View.VISIBLE);
            scrollPlates.setVisibility(View.VISIBLE);
            llPlateImages.removeAllViews();

            for (DataSnapshot snap : results) {
                llPlateImages.addView(buildPlateCard(snap));
            }
        });
    }

    private LinearLayout buildPlateCard(DataSnapshot snap) {
        String imageUrl = snap.child("image_url").getValue(String.class);
        String plate    = snap.getKey();

        // 카드 컨테이너
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setGravity(Gravity.CENTER);
        card.setBackgroundColor(Color.parseColor("#2A2A3E"));
        card.setPadding(28, 28, 28, 28);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(560, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(28, 0, 28, 0);
        card.setLayoutParams(lp);

        // 번호판 이미지 (번호판 실제 비율 4:1 근사)
        ImageView iv = new ImageView(this);
        iv.setLayoutParams(new LinearLayout.LayoutParams(500, 160));
        iv.setBackgroundColor(Color.WHITE);
        iv.setScaleType(ImageView.ScaleType.FIT_CENTER);
        if (imageUrl != null && !imageUrl.isEmpty()) {
            Glide.with(this).load(imageUrl).into(iv);
        }
        card.addView(iv);

        // 번호판 텍스트
        TextView tv = new TextView(this);
        tv.setText(plate);
        tv.setTextColor(Color.WHITE);
        tv.setTextSize(28);
        tv.setPadding(0, 20, 0, 0);
        tv.setGravity(Gravity.CENTER);
        card.addView(tv);

        // 클릭 시 해당 차량 구역으로 이동
        card.setOnClickListener(v -> {
            resetResultUI();
            navigateToZone(snap);
        });
        return card;
    }

    // ─── UI 초기화 ─────────────────────────────────────────────
    private void resetResultUI() {
        runOnUiThread(() -> {
            tvZone.setText("");
            tvZone.setVisibility(View.VISIBLE);
            tvSelectLabel.setVisibility(View.GONE);
            scrollPlates.setVisibility(View.GONE);
            llPlateImages.removeAllViews();
        });
    }

    // ─── Temi 이동 상태 콜백 ───────────────────────────────────
    @Override
    public void onGoToLocationStatusChanged(@NonNull String location, @NonNull String status,
                                             int descriptionId, @NonNull String description) {
        switch (status) {
            case OnGoToLocationStatusChangedListener.START:
                updateStatus(location + " 구역으로 이동 중...");
                break;
            case OnGoToLocationStatusChangedListener.COMPLETE:
                updateStatus(location + " 구역 도착!");
                speak(location + " 구역에 도착했습니다. 안전 운전 하세요.");
                // 사용자 차량 도달 후 일정 시간 뒤 자동 복귀
                if (!HOME_BASE.equalsIgnoreCase(location)) {
                    scheduleAutoReturn();
                }
                break;
            case OnGoToLocationStatusChangedListener.ABORT:
                updateStatus("이동 중단: " + description);
                speak("이동이 중단되었습니다.");
                break;
        }
    }

    // ─── 안내 종료 후 자동 복귀 (배터리 기반 분기) ─────────────
    private void scheduleAutoReturn() {
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            int battery = readBatteryLevel();
            if (battery >= 0 && battery < LOW_BATTERY_THRESHOLD) {
                updateStatus("배터리 " + battery + "% — 충전소로 복귀합니다.");
                speak("배터리가 부족합니다. 충전소로 복귀하겠습니다.");
            } else {
                updateStatus("대기 위치로 복귀합니다.");
                speak("대기 위치로 복귀하겠습니다.");
            }
            if (isRobotReady) robot.goTo(HOME_BASE);
        }, AUTO_RETURN_DELAY_MS);
    }

    private int readBatteryLevel() {
        try {
            BatteryData bd = robot.getBatteryData();
            return bd != null ? bd.getBatteryPercentage() : -1;
        } catch (Exception e) {
            return -1;
        }
    }

    @Override
    public void onTtsStatusChanged(@NonNull TtsRequest ttsRequest) {}

    private void speak(String text) {
        robot.speak(TtsRequest.create(text, false));
    }

    private void updateStatus(String msg) {
        runOnUiThread(() -> tvStatus.setText(msg));
    }

    private void hideKeyboard() {
        InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        View focused = getCurrentFocus();
        if (imm != null && focused != null) {
            imm.hideSoftInputFromWindow(focused.getWindowToken(), 0);
        }
        if (etPlateNumber != null) etPlateNumber.clearFocus();
    }
}

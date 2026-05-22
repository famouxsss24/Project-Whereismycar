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
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
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

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.Scanner;
import java.util.regex.Pattern;

public class MainActivity extends Activity
        implements OnRobotReadyListener,
                   OnGoToLocationStatusChangedListener,
                   Robot.TtsListener {

    // ───── Firebase ─────
    private static final String DB_URL  = "https://wimc-51ff9-default-rtdb.asia-southeast1.firebasedatabase.app";
    private static final String DB_PATH = "parking_lot";

    // ───── 검증 / 타이밍 ─────
    private static final Pattern LAST4_PATTERN = Pattern.compile("^\\d{4}$");
    private static final long NAV_DELAY_MS = 2500;
    private static final long AUTO_RETURN_DELAY_MS = 15000;
    private static final int  LOW_BATTERY_THRESHOLD = 30;
    private static final String HOME_BASE = "home base";

    // ───── 결제 ─────
    private static final int    FEE_PER_10_MIN = 500;
    private static final String KAKAO_CID = "TC0ONETIME";
    private static final String KAKAO_SECRET_KEY = "DEV82A2E59C77561B30D980F16DBBF4390B2252A";
    private static final String KAKAO_READY_URL  = "https://open-api.kakaopay.com/v1/payment/ready";

    // ───── UI ─────
    private EditText etPlateNumber;
    private TextView tvStatus, tvZone, tvSelectLabel;
    private HorizontalScrollView scrollPlates;
    private LinearLayout llPlateImages;
    private FrameLayout layoutWebViewContainer;
    private WebView paymentWebView;

    // ───── 상태 ─────
    private Robot robot;
    private DatabaseReference dbRef;
    private boolean isRobotReady = false;
    private DataSnapshot currentSnapshot = null;
    private String currentZone = null;

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
        layoutWebViewContainer = findViewById(R.id.layoutWebViewContainer);
        paymentWebView = findViewById(R.id.paymentWebView);
        initWebView();

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

    // ─── WebView 초기화 (카카오페이 결제용) ─────────────────────────
    private void initWebView() {
        WebSettings webSettings = paymentWebView.getSettings();
        webSettings.setJavaScriptEnabled(true);
        webSettings.setDomStorageEnabled(true);
        paymentWebView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                if (url.contains("payment/success")) {
                    handlePaymentSuccess();
                    return true;
                } else if (url.contains("payment/fail") || url.contains("payment/cancel")) {
                    handlePaymentFailure();
                    return true;
                }
                return super.shouldOverrideUrlLoading(view, url);
            }
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

    // ─── Firebase 검색 (last4 기준) ─────────────────────────────────
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
                    processVehicleSelection(results.get(0));
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

    // ─── 차량 선택 후 처리 (결제 분기 포함) ───────────────────────
    private void processVehicleSelection(DataSnapshot snapshot) {
        currentSnapshot = snapshot;
        String plate = snapshot.getKey();
        String zone  = snapshot.child("zone").getValue(String.class);

        if (zone == null || zone.trim().isEmpty()) {
            updateStatus("구역 정보 없음 — 이동을 중단합니다.");
            speak("구역 정보를 찾을 수 없습니다.");
            return;
        }
        currentZone = zone;

        boolean isPaid = readPaidStatus(snapshot);
        if (isPaid) {
            // 이미 결제 완료 → 바로 안내
            tvZone.setText(zone + " 구역");
            updateStatus(plate + " → 이미 결제된 차량입니다. 이동합니다.");
            speak(zone + " 구역으로 안내해 드리겠습니다.");
            startNavigationAfterDelay(zone);
            return;
        }

        // 결제 필요 — 요금 계산
        String entryTimeStr = snapshot.child("entry_time").getValue(String.class);
        int fee = calculateParkingFee(entryTimeStr);

        if (fee == 0) {
            // 무료 시간 또는 entry_time 없음 → 자동 결제 처리 후 안내
            snapshot.getRef().child("is_paid").setValue(true);
            tvZone.setText(zone + " 구역");
            updateStatus(plate + " → 무료 시간입니다. 이동합니다.");
            speak("무료 주차 시간입니다. " + zone + " 구역으로 안내해 드리겠습니다.");
            startNavigationAfterDelay(zone);
        } else {
            // 결제 필요 → 카카오페이 호출
            updateStatus("정산 요금: " + String.format("%,d원", fee) + ". 결제를 진행해 주세요.");
            speak("주차 요금 " + fee + "원 결제가 필요합니다. 화면의 큐알 코드를 스캔해 주세요.");
            requestKakaoPay(fee, zone);
        }
    }

    private boolean readPaidStatus(DataSnapshot snapshot) {
        if (!snapshot.hasChild("is_paid")) return false;
        Boolean paid = snapshot.child("is_paid").getValue(Boolean.class);
        return paid != null && paid;
    }

    // ─── 주차 요금 계산 (10분당 500원, 0분 이하 = 무료) ─────────────
    private int calculateParkingFee(String entryTimeStr) {
        if (entryTimeStr == null || entryTimeStr.isEmpty()) return 0;
        SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.KOREA);
        try {
            Date entryTime = fmt.parse(entryTimeStr);
            if (entryTime == null) return 0;
            long diffMin = (new Date().getTime() - entryTime.getTime()) / (1000 * 60);
            if (diffMin <= 0) return 0;
            int intervals = (int) Math.ceil((double) diffMin / 10);
            return intervals * FEE_PER_10_MIN;
        } catch (Exception e) {
            e.printStackTrace();
            return 0;
        }
    }

    // ─── 카카오페이 결제 준비 요청 ─────────────────────────────────
    private void requestKakaoPay(int amount, String zone) {
        new Thread(() -> {
            try {
                URL url = new URL(KAKAO_READY_URL);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Authorization", "SECRET_KEY " + KAKAO_SECRET_KEY);
                conn.setRequestProperty("Content-Type", "application/json");
                conn.setDoOutput(true);

                JSONObject params = new JSONObject();
                params.put("cid", KAKAO_CID);
                params.put("partner_order_id", "WIMC_" + System.currentTimeMillis());
                params.put("partner_user_id", "WIMC_CUSTOMER");
                params.put("item_name", "내차로 주차 정산 (" + zone + " 구역)");
                params.put("quantity", 1);
                params.put("total_amount", amount);
                params.put("tax_free_amount", 0);
                params.put("approval_url", "https://localhost/payment/success");
                params.put("cancel_url",   "https://localhost/payment/cancel");
                params.put("fail_url",     "https://localhost/payment/fail");

                OutputStream os = conn.getOutputStream();
                os.write(params.toString().getBytes("UTF-8"));
                os.flush();
                os.close();

                if (conn.getResponseCode() == 200) {
                    Scanner s = new Scanner(conn.getInputStream()).useDelimiter("\\A");
                    String response = s.hasNext() ? s.next() : "";
                    JSONObject json = new JSONObject(response);
                    String redirectUrl = json.getString("next_redirect_mobile_url");

                    runOnUiThread(() -> {
                        layoutWebViewContainer.setVisibility(View.VISIBLE);
                        paymentWebView.loadUrl(redirectUrl);
                    });
                } else {
                    runOnUiThread(() -> updateStatus("결제 API 응답 오류 (" + conn.getResponseCode() + ")"));
                }
            } catch (Exception e) {
                e.printStackTrace();
                runOnUiThread(() -> updateStatus("결제 연동 예외: " + e.getMessage()));
            }
        }).start();
    }

    // ─── 결제 성공 ─────────────────────────────────────────────
    private void handlePaymentSuccess() {
        runOnUiThread(() -> {
            layoutWebViewContainer.setVisibility(View.GONE);
            paymentWebView.loadUrl("about:blank");
            updateStatus("결제가 정상 승인되었습니다.");

            if (currentSnapshot != null && currentZone != null) {
                currentSnapshot.getRef().child("is_paid").setValue(true);
                tvZone.setText(currentZone + " 구역");
                speak("결제가 완료되었습니다. " + currentZone + " 구역으로 안내해 드리겠습니다.");
                startNavigationAfterDelay(currentZone);
            }
        });
    }

    // ─── 결제 실패/취소 ──────────────────────────────────────────
    private void handlePaymentFailure() {
        runOnUiThread(() -> {
            layoutWebViewContainer.setVisibility(View.GONE);
            paymentWebView.loadUrl("about:blank");
            updateStatus("결제가 취소되었거나 실패했습니다.");
            speak("결제가 정상 처리되지 않았습니다. 다시 시도해 주세요.");
        });
    }

    // ─── 공통 이동 (waypoint 소문자 정규화) ─────────────────────────
    private void startNavigationAfterDelay(String zone) {
        if (zone == null || zone.trim().isEmpty()) {
            updateStatus("이동할 구역 정보가 없습니다.");
            return;
        }
        if (!isRobotReady) {
            updateStatus("Temi가 아직 준비되지 않았습니다.");
            return;
        }
        // Temi 내부 waypoint는 소문자로 저장됨 — 매칭을 위해 정규화
        final String target = zone.trim().toLowerCase();
        new Handler(Looper.getMainLooper()).postDelayed(
                () -> robot.goTo(target), NAV_DELAY_MS);
    }

    // ─── 중복 차량 카드 표시 ──────────────────────────────────────
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

        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setGravity(Gravity.CENTER);
        card.setBackgroundColor(Color.parseColor("#2A2A3E"));
        card.setPadding(28, 28, 28, 28);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(560, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(28, 0, 28, 0);
        card.setLayoutParams(lp);

        ImageView iv = new ImageView(this);
        iv.setLayoutParams(new LinearLayout.LayoutParams(500, 160));
        iv.setBackgroundColor(Color.WHITE);
        iv.setScaleType(ImageView.ScaleType.FIT_CENTER);
        if (imageUrl != null && !imageUrl.isEmpty()) {
            Glide.with(this).load(imageUrl).into(iv);
        }
        card.addView(iv);

        TextView tv = new TextView(this);
        tv.setText(plate);
        tv.setTextColor(Color.WHITE);
        tv.setTextSize(28);
        tv.setPadding(0, 20, 0, 0);
        tv.setGravity(Gravity.CENTER);
        card.addView(tv);

        card.setOnClickListener(v -> {
            resetResultUI();
            processVehicleSelection(snap);
        });
        return card;
    }

    private void resetResultUI() {
        runOnUiThread(() -> {
            tvZone.setText("");
            tvZone.setVisibility(View.VISIBLE);
            tvSelectLabel.setVisibility(View.GONE);
            scrollPlates.setVisibility(View.GONE);
            llPlateImages.removeAllViews();
        });
    }

    // ─── Temi 이동 상태 콜백 ──────────────────────────────────────
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

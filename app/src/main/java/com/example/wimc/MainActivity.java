package com.example.wimc;

import android.app.Activity;
import android.content.Context;
import android.graphics.Color;
import android.net.Uri;
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
import android.widget.VideoView;

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
    private static final double AD_DISCOUNT_RATE = 0.3;   // 광고 시청 시 30% 할인
    private static final int    QUIZ_REWARD_POINTS = 100;
    private static final String CORRECT_ANSWER = "진라면";
    private static final String KAKAO_CID = "TC0ONETIME";
    private static final String KAKAO_SECRET_KEY = "DEV82A2E59C77561B30D980F16DBBF4390B2252A";
    private static final String KAKAO_READY_URL  = "https://open-api.kakaopay.com/v1/payment/ready";

    // ───── UI: 메인 ─────
    private LinearLayout mainLayout;
    private EditText etPlateNumber;
    private TextView tvStatus, tvZone, tvSelectLabel;
    private HorizontalScrollView scrollPlates;
    private LinearLayout llPlateImages;

    // ───── UI: 결제 옵션 ─────
    private LinearLayout paymentOptionLayout;
    private TextView tvPaymentPlate, tvParkingTime, tvOriginalFee;
    private Button btnPayDirect, btnPayWithAd;

    // ───── UI: 광고 ─────
    private FrameLayout adLayout;
    private VideoView videoView;

    // ───── UI: 퀴즈 ─────
    private LinearLayout quizLayout;
    private TextView quizQuestion;
    private Button btnAnswer1, btnAnswer2;

    // ───── UI: 네비게이션 ─────
    private FrameLayout navLayout;
    private TextView tvNavZone, tvNavStatus, navInfo;

    // ───── UI: 카카오페이 WebView ─────
    private FrameLayout layoutWebViewContainer;
    private WebView paymentWebView;

    // ───── 상태 ─────
    private Robot robot;
    private DatabaseReference dbRef;
    private boolean isRobotReady = false;
    private DataSnapshot currentSnapshot = null;
    private String currentPlate = null;
    private String currentZone = null;
    private int originalFee = 0;
    private int finalFee = 0;
    private boolean adWatched = false;
    private boolean quizCorrect = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        bindViews();
        initWebView();
        initAdVideo();
        setupListeners();

        try {
            dbRef = FirebaseDatabase.getInstance(DB_URL).getReference(DB_PATH);
        } catch (Exception e) {
            updateStatus("Firebase 연결 실패");
        }

        robot = Robot.getInstance();
    }

    private void bindViews() {
        // 메인
        mainLayout    = findViewById(R.id.mainLayout);
        etPlateNumber = findViewById(R.id.etPlateNumber);
        tvStatus      = findViewById(R.id.tvStatus);
        tvZone        = findViewById(R.id.tvZone);
        tvSelectLabel = findViewById(R.id.tvSelectLabel);
        scrollPlates  = findViewById(R.id.scrollPlates);
        llPlateImages = findViewById(R.id.llPlateImages);

        // 결제 옵션
        paymentOptionLayout = findViewById(R.id.paymentOptionLayout);
        tvPaymentPlate = findViewById(R.id.tvPaymentPlate);
        tvParkingTime  = findViewById(R.id.tvParkingTime);
        tvOriginalFee  = findViewById(R.id.tvOriginalFee);
        btnPayDirect   = findViewById(R.id.btnPayDirect);
        btnPayWithAd   = findViewById(R.id.btnPayWithAd);

        // 광고
        adLayout  = findViewById(R.id.adLayout);
        videoView = findViewById(R.id.videoView);

        // 퀴즈
        quizLayout    = findViewById(R.id.quizLayout);
        quizQuestion  = findViewById(R.id.quizQuestion);
        btnAnswer1    = findViewById(R.id.btnAnswer1);
        btnAnswer2    = findViewById(R.id.btnAnswer2);

        // 네비게이션
        navLayout    = findViewById(R.id.navLayout);
        tvNavZone    = findViewById(R.id.tvNavZone);
        tvNavStatus  = findViewById(R.id.tvNavStatus);
        navInfo      = findViewById(R.id.navInfo);

        // 카카오페이
        layoutWebViewContainer = findViewById(R.id.layoutWebViewContainer);
        paymentWebView         = findViewById(R.id.paymentWebView);
    }

    private void setupListeners() {
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

        // 결제 옵션 버튼
        btnPayDirect.setOnClickListener(v -> {
            // 광고 안 보고 전액 결제
            adWatched = false;
            quizCorrect = false;
            finalFee = originalFee;
            requestKakaoPay(finalFee, currentZone);
        });

        btnPayWithAd.setOnClickListener(v -> {
            // 광고 시청으로 이동
            showAdScreen();
        });

        // 퀴즈 답변 버튼
        btnAnswer1.setOnClickListener(v -> handleQuizAnswer(btnAnswer1.getText().toString()));
        btnAnswer2.setOnClickListener(v -> handleQuizAnswer(btnAnswer2.getText().toString()));
    }

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

    private void initAdVideo() {
        String videoPath = "android.resource://" + getPackageName() + "/" + R.raw.jinramen_ad;
        videoView.setVideoURI(Uri.parse(videoPath));
        videoView.setOnPreparedListener(mp -> mp.setLooping(false));
        videoView.setOnCompletionListener(mp -> onAdComplete());
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
        if (videoView != null) videoView.stopPlayback();
    }

    @Override
    public void onRobotReady(boolean isReady) {
        isRobotReady = isReady;
        updateStatus(isReady ? "Temi 준비 완료" : "Temi 연결 대기 중...");
    }

    // ─── Firebase 검색 ─────────────────────────────────────────────
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

    // ─── 차량 선택 후 처리 (바로 이동 시작) ───────────────────────
    private void processVehicleSelection(DataSnapshot snapshot) {
        currentSnapshot = snapshot;
        currentPlate = snapshot.getKey();
        currentZone = snapshot.child("zone").getValue(String.class);

        if (currentZone == null || currentZone.trim().isEmpty()) {
            updateStatus("구역 정보 없음 — 이동을 중단합니다.");
            speak("구역 정보를 찾을 수 없습니다.");
            return;
        }

        // entry_time이 없으면 자동 채움 (1시간 전 기준 — 상지님 코드 호환 백업)
        String entryTimeStr = snapshot.child("entry_time").getValue(String.class);
        if (entryTimeStr == null || entryTimeStr.isEmpty()) {
            long oneHourAgo = System.currentTimeMillis() - 3600_000L;
            SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.KOREA);
            entryTimeStr = fmt.format(new Date(oneHourAgo));
            snapshot.getRef().child("entry_time").setValue(entryTimeStr);
        }
        // 요금 계산
        originalFee = calculateParkingFee(entryTimeStr);

        // 결제 없이 바로 이동 시작
        tvZone.setText(currentZone + " 구역");
        updateStatus(currentPlate + " → " + currentZone + " 구역으로 이동합니다");
        speak(currentZone + " 구역으로 안내해 드리겠습니다.");
        showNavScreen();
        startNavigationAfterDelay(currentZone);
    }

    private boolean readPaidStatus(DataSnapshot snapshot) {
        if (!snapshot.hasChild("is_paid")) return false;
        Boolean paid = snapshot.child("is_paid").getValue(Boolean.class);
        return paid != null && paid;
    }

    // ─── 주차 요금 계산 ─────────────────────────────────────────
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

    private String calculateParkingDuration(String entryTimeStr) {
        if (entryTimeStr == null || entryTimeStr.isEmpty()) return "-";
        SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.KOREA);
        try {
            Date entryTime = fmt.parse(entryTimeStr);
            if (entryTime == null) return "-";
            long diffMin = (new Date().getTime() - entryTime.getTime()) / (1000 * 60);
            if (diffMin <= 0) return "0분";
            long hours = diffMin / 60;
            long minutes = diffMin % 60;
            return (hours > 0 ? hours + "시간 " : "") + minutes + "분";
        } catch (Exception e) {
            return "-";
        }
    }

    // ─── 결제 옵션 화면 표시 ──────────────────────────────────────
    private void showPaymentOptionScreen(String entryTimeStr) {
        runOnUiThread(() -> {
            mainLayout.setVisibility(View.GONE);
            paymentOptionLayout.setVisibility(View.VISIBLE);

            tvPaymentPlate.setText(currentPlate);
            tvParkingTime.setText(calculateParkingDuration(entryTimeStr));
            tvOriginalFee.setText(String.format(Locale.KOREA, "%,d원", originalFee));

            int discountedFee = (int) Math.round(originalFee * (1 - AD_DISCOUNT_RATE));
            btnPayDirect.setText("지금 결제 — " + String.format(Locale.KOREA, "%,d원", originalFee));
            btnPayWithAd.setText("광고 보고 30% 할인 — " + String.format(Locale.KOREA, "%,d원", discountedFee));

            speak("주차 요금 " + originalFee + "원입니다. 광고 시청 시 30퍼센트 할인됩니다.");
        });
    }

    // ─── 광고 영상 재생 화면 ─────────────────────────────────────
    private void showAdScreen() {
        runOnUiThread(() -> {
            mainLayout.setVisibility(View.GONE);
            paymentOptionLayout.setVisibility(View.GONE);
            navLayout.setVisibility(View.GONE);
            adLayout.setVisibility(View.VISIBLE);
            adWatched = true;   // 도착 후 강제 광고이므로 시청 = 30% 할인 자동 적용
            videoView.start();
            speak("정산 광고를 시청해 주세요.");
        });
    }

    private void onAdComplete() {
        adWatched = true;
        runOnUiThread(this::showQuizScreen);
    }

    // ─── 퀴즈 화면 ────────────────────────────────────────────────
    private void showQuizScreen() {
        adLayout.setVisibility(View.GONE);
        quizLayout.setVisibility(View.VISIBLE);
        speak("광고 시청이 완료되었습니다. 30퍼센트 할인이 적용됩니다. 광고 퀴즈에 답해주세요.");
    }

    private void handleQuizAnswer(String selected) {
        if (CORRECT_ANSWER.equals(selected)) {
            quizCorrect = true;
            Toast.makeText(this, "🎉 정답! +" + QUIZ_REWARD_POINTS + " 포인트 적립", Toast.LENGTH_LONG).show();
            speak("정답입니다. " + QUIZ_REWARD_POINTS + " 포인트가 적립되었습니다.");
            addPointsToUser(currentPlate, QUIZ_REWARD_POINTS);
        } else {
            quizCorrect = false;
            Toast.makeText(this, "오답이지만 광고 시청 30% 할인은 그대로 적용됩니다.", Toast.LENGTH_LONG).show();
            speak("오답입니다. 하지만 광고 시청 할인은 적용됩니다.");
        }

        // 결제 진행 (할인된 금액)
        finalFee = (int) Math.round(originalFee * (1 - AD_DISCOUNT_RATE));
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            quizLayout.setVisibility(View.GONE);
            requestKakaoPay(finalFee, currentZone);
        }, 1500);
    }

    private void addPointsToUser(String plate, int points) {
        if (plate == null || dbRef == null) return;
        DatabaseReference userRef = FirebaseDatabase.getInstance(DB_URL)
                .getReference("users").child(plate).child("total_points");
        userRef.addListenerForSingleValueEvent(new ValueEventListener() {
            @Override
            public void onDataChange(@NonNull DataSnapshot snapshot) {
                Integer current = snapshot.getValue(Integer.class);
                int updated = (current == null ? 0 : current) + points;
                userRef.setValue(updated);
            }
            @Override
            public void onCancelled(@NonNull DatabaseError error) {}
        });
    }

    // ─── 카카오페이 결제 준비 요청 ─────────────────────────────────
    private void requestKakaoPay(int amount, String zone) {
        runOnUiThread(() -> updateStatus("카카오페이 결제 진행 중..."));
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

    // ─── 결제 성공 (도착 후 결제 → 자동 복귀) ───────────────────
    private void handlePaymentSuccess() {
        runOnUiThread(() -> {
            layoutWebViewContainer.setVisibility(View.GONE);
            paymentWebView.loadUrl("about:blank");

            if (currentSnapshot != null && currentZone != null) {
                DatabaseReference ref = currentSnapshot.getRef();
                ref.child("is_paid").setValue(true);
                ref.child("original_fee").setValue(originalFee);
                ref.child("paid_amount").setValue(finalFee);
                ref.child("discount_applied").setValue(adWatched);
                ref.child("quiz_correct").setValue(quizCorrect);
                ref.child("paid_at").setValue(currentTimestamp());

                // 이미 차량 위치에 도착해있음 → 결제 완료 후 안내 + 자동 복귀
                showNavScreen();
                updateNav(currentZone, "결제 완료 — 안전 운전 하세요");
                speak("결제가 완료되었습니다. 안전 운전 하세요.");
                scheduleAutoReturn();
            }
        });
    }

    // ─── 결제 실패/취소 ──────────────────────────────────────────
    private void handlePaymentFailure() {
        runOnUiThread(() -> {
            layoutWebViewContainer.setVisibility(View.GONE);
            paymentWebView.loadUrl("about:blank");
            updateStatus("결제가 취소되었거나 실패했습니다.");
            speak("결제가 정상 처리되지 않았습니다.");
            // 메인 화면으로 복귀
            new Handler(Looper.getMainLooper()).postDelayed(this::backToMainScreen, 2000);
        });
    }

    // ─── 네비게이션 화면 표시 ────────────────────────────────────
    private void showNavScreen() {
        runOnUiThread(() -> {
            mainLayout.setVisibility(View.GONE);
            paymentOptionLayout.setVisibility(View.GONE);
            adLayout.setVisibility(View.GONE);
            quizLayout.setVisibility(View.GONE);
            navLayout.setVisibility(View.VISIBLE);

            tvNavZone.setText(currentZone + " 구역");
            tvNavStatus.setText("안내 중...");
            navInfo.setText("목적지: " + currentZone + " 구역\n상태: 안내 중\n방향: 직진");
        });
    }

    private void backToMainScreen() {
        runOnUiThread(() -> {
            mainLayout.setVisibility(View.VISIBLE);
            paymentOptionLayout.setVisibility(View.GONE);
            adLayout.setVisibility(View.GONE);
            quizLayout.setVisibility(View.GONE);
            navLayout.setVisibility(View.GONE);
            layoutWebViewContainer.setVisibility(View.GONE);
            etPlateNumber.setText("");
            resetResultUI();
            updateStatus("Temi 준비 완료");
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
        final String target = zone.trim().toLowerCase();
        new Handler(Looper.getMainLooper()).postDelayed(
                () -> robot.goTo(target), NAV_DELAY_MS);
    }

    // ─── 중복 차량 카드 ──────────────────────────────────────────
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
                updateNav(location, "이동 중...");
                break;
            case OnGoToLocationStatusChangedListener.COMPLETE:
                updateNav(location, "도착 완료!");
                if (HOME_BASE.equalsIgnoreCase(location)) {
                    // 홈베이스 복귀 완료 → 메인 화면
                    backToMainScreen();
                } else {
                    // 차량 위치 도착 → 광고 영상 자동 재생
                    speak(location + " 구역에 도착했습니다. 광고 시청 후 정산이 진행됩니다.");
                    new Handler(Looper.getMainLooper()).postDelayed(this::showAdScreen, 2500);
                }
                break;
            case OnGoToLocationStatusChangedListener.ABORT:
                updateNav(location, "이동 중단");
                speak("이동이 중단되었습니다.");
                break;
        }
    }

    private void updateNav(String location, String status) {
        runOnUiThread(() -> {
            tvNavStatus.setText(status);
            navInfo.setText("목적지: " + location + "\n상태: " + status + "\n방향: 직진");
        });
    }

    // ─── 자동 복귀 (배터리 기반) ──────────────────────────────────
    private void scheduleAutoReturn() {
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            int battery = readBatteryLevel();
            if (battery >= 0 && battery < LOW_BATTERY_THRESHOLD) {
                speak("배터리가 부족합니다. 충전소로 복귀하겠습니다.");
            } else {
                speak("대기 위치로 복귀하겠습니다.");
            }
            updateNav(HOME_BASE, "복귀 중...");
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

    private String currentTimestamp() {
        SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.KOREA);
        return fmt.format(new Date());
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

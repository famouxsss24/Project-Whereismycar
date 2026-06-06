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
    private static final String KAKAO_READY_URL  = "https://open-api.kakaopay.com/online/v1/payment/ready";

    // ───── UI: 메인 ─────
    private LinearLayout mainLayout;
    private EditText etPlateNumber;
    private TextView tvStatus, tvZone, tvSelectLabel;
    private HorizontalScrollView scrollPlates;
    private LinearLayout llPlateImages;

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

    // ───── 다국어 ─────
    private String lang = "ko";   // ko, en, ja, zh
    private static final java.util.Map<String, java.util.Map<String, String>> STR = new java.util.HashMap<>();
    static {
        java.util.Map<String, String> ko = new java.util.HashMap<>();
        ko.put("subtitle", "차량 번호판 뒷 4자리를 입력해 주세요");
        ko.put("search", "차량 찾기");
        ko.put("ready", "Temi 준비 완료");
        ko.put("waiting", "Temi 연결 대기 중...");
        ko.put("input4", "숫자 4자리를 입력하세요");
        ko.put("notfound", "해당 번호로 등록된 차량이 없습니다.");
        ko.put("tts_notfound", "등록된 차량을 찾을 수 없습니다.");
        ko.put("select", "본인 차량을 선택해 주세요 🚙");
        ko.put("tts_guide", "구역으로 안내해 드리겠습니다.");
        ko.put("zone_suffix", " 구역");
        ko.put("navi", "안내 중...");
        ko.put("arrived_ad", "구역에 도착했습니다. 광고 시청 후 정산이 진행됩니다.");
        ko.put("arrived_paid", "구역에 도착했습니다. 이미 정산이 완료된 차량입니다. 안전 운전 하세요.");
        ko.put("ad_watch", "정산 광고를 시청해 주세요.");
        ko.put("quiz_title", "🎯 광고 퀴즈");
        ko.put("quiz_reward", "정답 시 +100 포인트 🎁");
        ko.put("quiz_q", "류현진이 먹은 라면은?");
        ko.put("quiz_a1", "신라면");
        ko.put("quiz_a2", "진라면");
        ko.put("tts_quiz", "광고 시청이 완료되었습니다. 30퍼센트 할인이 적용됩니다. 광고 퀴즈에 답해주세요.");
        ko.put("correct", "🎉 정답! +100 포인트 적립");
        ko.put("tts_correct", "정답입니다. 100 포인트가 적립되었습니다.");
        ko.put("wrong", "오답이지만 광고 시청 30% 할인은 그대로 적용됩니다.");
        ko.put("tts_wrong", "오답입니다. 하지만 광고 시청 할인은 적용됩니다.");
        ko.put("pay_ing", "카카오페이 결제 진행 중...");
        ko.put("tts_paid", "결제가 완료되었습니다. 안전 운전 하세요.");
        ko.put("paid_done", "결제 완료 — 안전 운전 하세요");
        ko.put("tts_return", "대기 위치로 복귀하겠습니다.");
        ko.put("tts_return_low", "배터리가 부족합니다. 충전소로 복귀하겠습니다.");
        STR.put("ko", ko);

        java.util.Map<String, String> en = new java.util.HashMap<>();
        en.put("subtitle", "Enter the last 4 digits of your plate");
        en.put("search", "Find My Car");
        en.put("ready", "Temi Ready");
        en.put("waiting", "Connecting to Temi...");
        en.put("input4", "Please enter 4 digits");
        en.put("notfound", "No vehicle found for this number.");
        en.put("tts_notfound", "No registered vehicle found.");
        en.put("select", "Please select your vehicle 🚙");
        en.put("tts_guide", "I will guide you to the zone.");
        en.put("zone_suffix", " Zone");
        en.put("navi", "Guiding...");
        en.put("arrived_ad", "zone. Settlement will proceed after the ad.");
        en.put("arrived_paid", "zone. Already paid. Drive safely.");
        en.put("ad_watch", "Please watch the advertisement.");
        en.put("quiz_title", "🎯 Ad Quiz");
        en.put("quiz_reward", "+100 points if correct 🎁");
        en.put("quiz_q", "Which ramen did Ryu Hyun-jin eat?");
        en.put("quiz_a1", "Shin Ramyun");
        en.put("quiz_a2", "Jin Ramen");
        en.put("tts_quiz", "Ad finished. 30 percent discount applied. Please answer the quiz.");
        en.put("correct", "🎉 Correct! +100 points");
        en.put("tts_correct", "Correct. 100 points have been earned.");
        en.put("wrong", "Wrong, but the 30% ad discount still applies.");
        en.put("tts_wrong", "Wrong answer. But the ad discount still applies.");
        en.put("pay_ing", "Processing KakaoPay payment...");
        en.put("tts_paid", "Payment complete. Drive safely.");
        en.put("paid_done", "Payment complete — Drive safely");
        en.put("tts_return", "Returning to standby position.");
        en.put("tts_return_low", "Low battery. Returning to charging station.");
        STR.put("en", en);

        java.util.Map<String, String> ja = new java.util.HashMap<>();
        ja.put("subtitle", "ナンバープレート末尾4桁を入力してください");
        ja.put("search", "車を探す");
        ja.put("ready", "Temi 準備完了");
        ja.put("waiting", "Temi 接続待機中...");
        ja.put("input4", "数字4桁を入力してください");
        ja.put("notfound", "該当する車両が見つかりません。");
        ja.put("tts_notfound", "登録された車両が見つかりません。");
        ja.put("select", "ご自分の車両を選択してください 🚙");
        ja.put("tts_guide", "エリアへご案内します。");
        ja.put("zone_suffix", " エリア");
        ja.put("navi", "案内中...");
        ja.put("arrived_ad", "エリアに到着しました。広告視聴後に精算します。");
        ja.put("arrived_paid", "エリアに到着しました。精算済みです。安全運転を。");
        ja.put("ad_watch", "広告をご視聴ください。");
        ja.put("quiz_title", "🎯 広告クイズ");
        ja.put("quiz_reward", "正解で +100 ポイント 🎁");
        ja.put("quiz_q", "リュ・ヒョンジンが食べたラーメンは?");
        ja.put("quiz_a1", "辛ラーメン");
        ja.put("quiz_a2", "ジンラーメン");
        ja.put("tts_quiz", "広告の視聴が完了しました。30パーセント割引が適用されます。クイズにお答えください。");
        ja.put("correct", "🎉 正解! +100 ポイント");
        ja.put("tts_correct", "正解です。100ポイントが貯まりました。");
        ja.put("wrong", "不正解ですが、広告視聴30%割引は適用されます。");
        ja.put("tts_wrong", "不正解です。ですが広告割引は適用されます。");
        ja.put("pay_ing", "カカオペイ決済処理中...");
        ja.put("tts_paid", "決済が完了しました。安全運転を。");
        ja.put("paid_done", "決済完了 — 安全運転を");
        ja.put("tts_return", "待機位置に戻ります。");
        ja.put("tts_return_low", "バッテリー不足です。充電ステーションに戻ります。");
        STR.put("ja", ja);

        java.util.Map<String, String> zh = new java.util.HashMap<>();
        zh.put("subtitle", "请输入车牌号后四位");
        zh.put("search", "查找车辆");
        zh.put("ready", "Temi 准备就绪");
        zh.put("waiting", "正在连接 Temi...");
        zh.put("input4", "请输入四位数字");
        zh.put("notfound", "未找到该号码的车辆。");
        zh.put("tts_notfound", "未找到已登记的车辆。");
        zh.put("select", "请选择您的车辆 🚙");
        zh.put("tts_guide", "为您带路到区域。");
        zh.put("zone_suffix", " 区");
        zh.put("navi", "引导中...");
        zh.put("arrived_ad", "区。观看广告后进行结算。");
        zh.put("arrived_paid", "区。已完成结算。请安全驾驶。");
        zh.put("ad_watch", "请观看广告。");
        zh.put("quiz_title", "🎯 广告问答");
        zh.put("quiz_reward", "答对 +100 积分 🎁");
        zh.put("quiz_q", "柳贤振吃的是哪种拉面?");
        zh.put("quiz_a1", "辛拉面");
        zh.put("quiz_a2", "真拉面");
        zh.put("tts_quiz", "广告观看完成。已享受30%折扣。请回答问答。");
        zh.put("correct", "🎉 答对! +100 积分");
        zh.put("tts_correct", "答对了。已获得100积分。");
        zh.put("wrong", "答错了，但广告30%折扣仍然适用。");
        zh.put("tts_wrong", "答错了。但广告折扣仍然适用。");
        zh.put("pay_ing", "正在处理 KakaoPay 支付...");
        zh.put("tts_paid", "支付完成。请安全驾驶。");
        zh.put("paid_done", "支付完成 — 请安全驾驶");
        zh.put("tts_return", "正在返回待机位置。");
        zh.put("tts_return_low", "电量不足。正在返回充电站。");
        STR.put("zh", zh);
    }

    private String t(String key) {
        java.util.Map<String, String> m = STR.get(lang);
        if (m == null) m = STR.get("ko");
        String v = m.get(key);
        return v != null ? v : key;
    }

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

    // UI 참조 (다국어 갱신용)
    private TextView tvSubtitle;
    private Button btnSearchRef;
    private TextView tvQuizTitle, tvQuizReward;

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
        tvSubtitle    = findViewById(R.id.tvSubtitle);
        btnSearchRef  = findViewById(R.id.btnSearch);

        // 광고
        adLayout  = findViewById(R.id.adLayout);
        videoView = findViewById(R.id.videoView);

        // 퀴즈
        quizLayout    = findViewById(R.id.quizLayout);
        quizQuestion  = findViewById(R.id.quizQuestion);
        btnAnswer1    = findViewById(R.id.btnAnswer1);
        btnAnswer2    = findViewById(R.id.btnAnswer2);
        tvQuizTitle   = findViewById(R.id.tvQuizTitle);
        tvQuizReward  = findViewById(R.id.tvQuizReward);

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
        btnSearchRef.setOnClickListener(v -> {
            hideKeyboard();
            String last4 = etPlateNumber.getText().toString().trim();
            if (!LAST4_PATTERN.matcher(last4).matches()) {
                Toast.makeText(this, t("input4"), Toast.LENGTH_SHORT).show();
                return;
            }
            searchByLast4(last4);
        });

        // 퀴즈 답변 버튼 (정답 비교는 한국어 기준 키로 판정)
        btnAnswer1.setOnClickListener(v -> handleQuizAnswer(false)); // 신라면 = 오답
        btnAnswer2.setOnClickListener(v -> handleQuizAnswer(true));  // 진라면 = 정답

        // 언어 선택 버튼
        findViewById(R.id.btnLangKo).setOnClickListener(v -> applyLanguage("ko"));
        findViewById(R.id.btnLangEn).setOnClickListener(v -> applyLanguage("en"));
        findViewById(R.id.btnLangJa).setOnClickListener(v -> applyLanguage("ja"));
        findViewById(R.id.btnLangZh).setOnClickListener(v -> applyLanguage("zh"));
    }

    // ─── 언어 전환 ────────────────────────────────────────────────
    private void applyLanguage(String newLang) {
        lang = newLang;
        // 선택된 버튼 강조
        int[] ids = {R.id.btnLangKo, R.id.btnLangEn, R.id.btnLangJa, R.id.btnLangZh};
        String[] langs = {"ko", "en", "ja", "zh"};
        for (int i = 0; i < ids.length; i++) {
            Button b = findViewById(ids[i]);
            b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(
                    Color.parseColor(langs[i].equals(lang) ? "#FFE0D8" : "#FFFFFF")));
        }
        // UI 텍스트 갱신
        tvSubtitle.setText(t("subtitle"));
        btnSearchRef.setText(t("search"));
        tvSelectLabel.setText(t("select"));
        quizQuestion.setText(t("quiz_q"));
        btnAnswer1.setText(t("quiz_a1"));
        btnAnswer2.setText(t("quiz_a2"));
        tvQuizTitle.setText(t("quiz_title"));
        tvQuizReward.setText(t("quiz_reward"));
        if (isRobotReady) updateStatus(t("ready"));
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
        updateStatus(isReady ? t("ready") : t("waiting"));
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
                    updateStatus(t("notfound"));
                    speak(t("tts_notfound"));
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
        tvZone.setText(currentZone + t("zone_suffix"));
        updateStatus(currentPlate + " → " + currentZone + t("zone_suffix"));
        speak(currentZone + " " + t("tts_guide"));
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

    // ─── 광고 영상 재생 화면 ─────────────────────────────────────
    private void showAdScreen() {
        runOnUiThread(() -> {
            mainLayout.setVisibility(View.GONE);
            navLayout.setVisibility(View.GONE);
            adLayout.setVisibility(View.VISIBLE);
            adWatched = true;   // 도착 후 강제 광고이므로 시청 = 30% 할인 자동 적용
            videoView.start();
            speak(t("ad_watch"));
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
        quizQuestion.setText(t("quiz_q"));
        btnAnswer1.setText(t("quiz_a1"));
        btnAnswer2.setText(t("quiz_a2"));
        tvQuizTitle.setText(t("quiz_title"));
        tvQuizReward.setText(t("quiz_reward"));
        speak(t("tts_quiz"));
    }

    private void handleQuizAnswer(boolean isCorrect) {
        if (isCorrect) {
            quizCorrect = true;
            Toast.makeText(this, t("correct"), Toast.LENGTH_LONG).show();
            speak(t("tts_correct"));
            addPointsToUser(currentPlate, QUIZ_REWARD_POINTS);
        } else {
            quizCorrect = false;
            Toast.makeText(this, t("wrong"), Toast.LENGTH_LONG).show();
            speak(t("tts_wrong"));
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
        runOnUiThread(() -> updateStatus(t("pay_ing")));
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

                int responseCode = conn.getResponseCode();
                if (responseCode == 200) {
                    Scanner s = new Scanner(conn.getInputStream()).useDelimiter("\\A");
                    String response = s.hasNext() ? s.next() : "";
                    JSONObject json = new JSONObject(response);
                    String redirectUrl = json.getString("next_redirect_mobile_url");

                    runOnUiThread(() -> {
                        layoutWebViewContainer.setVisibility(View.VISIBLE);
                        paymentWebView.loadUrl(redirectUrl);
                    });
                } else {
                    runOnUiThread(() -> updateStatus("결제 API 응답 오류 (" + responseCode + ")"));
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
                updateNav(currentZone, t("paid_done"));
                speak(t("tts_paid"));
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
            adLayout.setVisibility(View.GONE);
            quizLayout.setVisibility(View.GONE);
            navLayout.setVisibility(View.VISIBLE);

            tvNavZone.setText(currentZone + t("zone_suffix"));
            tvNavStatus.setText(t("navi"));
            navInfo.setText(currentZone + t("zone_suffix") + "\n" + t("navi"));
        });
    }

    private void backToMainScreen() {
        runOnUiThread(() -> {
            mainLayout.setVisibility(View.VISIBLE);
            adLayout.setVisibility(View.GONE);
            quizLayout.setVisibility(View.GONE);
            navLayout.setVisibility(View.GONE);
            layoutWebViewContainer.setVisibility(View.GONE);
            etPlateNumber.setText("");
            resetResultUI();
            updateStatus(t("ready"));
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
        card.setBackground(androidx.core.content.ContextCompat.getDrawable(this, R.drawable.bg_card));
        card.setPadding(28, 28, 28, 28);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(560, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(28, 0, 28, 0);
        card.setLayoutParams(lp);

        ImageView iv = new ImageView(this);
        iv.setLayoutParams(new LinearLayout.LayoutParams(500, 160));
        iv.setBackgroundColor(Color.parseColor("#F7F0EC"));
        iv.setScaleType(ImageView.ScaleType.FIT_CENTER);
        if (imageUrl != null && !imageUrl.isEmpty()) {
            Glide.with(this).load(imageUrl).into(iv);
        }
        card.addView(iv);

        TextView tv = new TextView(this);
        tv.setText(plate);
        tv.setTextColor(Color.parseColor("#3C3237"));
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
                } else if (currentSnapshot != null && readPaidStatus(currentSnapshot)) {
                    // 이미 결제된 차량 → 광고/결제 스킵하고 바로 복귀
                    speak(location + " " + t("arrived_paid"));
                    updateNav(location, t("paid_done"));
                    scheduleAutoReturn();
                } else {
                    // 미결제 차량 → 광고 영상 자동 재생
                    speak(location + " " + t("arrived_ad"));
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
                speak(t("tts_return_low"));
            } else {
                speak(t("tts_return"));
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
        try {
            if (robot != null) robot.speak(TtsRequest.create(text, false));
        } catch (Exception e) {
            e.printStackTrace();
        }
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

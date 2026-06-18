package com.example.wimc;

import android.app.Activity;
import android.content.Context;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.InputMethodManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.ArrayAdapter;
import android.widget.AutoCompleteTextView;
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

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
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
    private static final String HOME_BASE = "복귀";   // Temi에 저장된 복귀 지점 웨이포인트 이름

    // ───── 결제 (내차로페이 — 자체 WebView 데모) ─────
    private static final int    FEE_PER_10_MIN = 500;
    private static final int    QUIZ_REWARD_POINTS = 100;
    private static final String PAY_SUCCESS_URL = "https://wimc.local/payment/success";

    // ───── UI: 메인 ─────
    private LinearLayout mainLayout;
    private AutoCompleteTextView etPlateNumber;
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
        ko.put("title", "🚗 내 차로");
        ko.put("ad_skip", "건너뛰기 ▶▶");
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
        ko.put("tts_quiz_a", "광고 시청이 완료되었습니다.");
        ko.put("tts_quiz_b", "광고 퀴즈에 답해주세요.");
        ko.put("tts_discount", "%d퍼센트 할인이 적용됩니다.");
        ko.put("tts_no_discount", "주차 시간이 짧아 아직 할인이 적용되지 않습니다.");
        ko.put("correct", "🎉 정답! +100 포인트 적립");
        ko.put("tts_correct", "정답입니다. 100 포인트가 적립되었습니다.");
        ko.put("point_title", "🎁 포인트 적립 완료");
        ko.put("point_earned", "퀴즈 정답! +100P 적립");
        ko.put("point_balance_label", "보유 포인트");
        ko.put("point_use", "이번 결제에 사용");
        ko.put("point_keep", "다음에 쓰기 (적립 유지)");
        ko.put("tts_point", "포인트가 적립되었습니다. 이번 결제에 사용할지 선택해 주세요.");
        ko.put("pay_point_use", "포인트 사용");
        ko.put("wrong", "오답입니다! 다시 선택해 주세요 🎯");
        ko.put("tts_wrong", "오답입니다. 다시 선택해 주세요.");
        ko.put("quiz_retry", "아쉽지만 오답! 한 번 더 기회를 드릴게요 🎯");
        ko.put("tts_retry", "오답입니다. 한 번 더 도전해 보세요.");
        ko.put("discount_label", "⏱ 주차 시간 할인");
        ko.put("discount_now", "현재 적용");
        ko.put("pay_ing", "내차로페이 결제 진행 중...");
        ko.put("tts_paid", "결제가 완료되었습니다. 안전 운전 하세요.");
        ko.put("paid_done", "결제 완료 — 안전 운전 하세요");
        ko.put("tts_return", "대기 위치로 복귀하겠습니다.");
        ko.put("tts_return_low", "배터리가 부족합니다. 충전소로 복귀하겠습니다.");
        ko.put("return_done", "복귀가 완료되었습니다.");
        STR.put("ko", ko);

        java.util.Map<String, String> en = new java.util.HashMap<>();
        en.put("subtitle", "Enter the last 4 digits of your plate");
        en.put("title", "🚗 Where's My Car");
        en.put("ad_skip", "Skip ▶▶");
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
        en.put("tts_quiz_a", "The ad is finished.");
        en.put("tts_quiz_b", "Please answer the quiz.");
        en.put("tts_discount", "A %d percent discount is applied.");
        en.put("tts_no_discount", "Parking time is too short, no discount yet.");
        en.put("correct", "🎉 Correct! +100 points");
        en.put("tts_correct", "Correct. 100 points have been earned.");
        en.put("point_title", "🎁 Points Earned");
        en.put("point_earned", "Quiz correct! +100P earned");
        en.put("point_balance_label", "Your Points");
        en.put("point_use", "Use on this payment");
        en.put("point_keep", "Save for later");
        en.put("tts_point", "Points have been earned. Please choose whether to use them now.");
        en.put("pay_point_use", "Points used");
        en.put("wrong", "Wrong! Please choose again 🎯");
        en.put("tts_wrong", "Wrong answer. Please choose again.");
        en.put("quiz_retry", "Wrong! One more try 🎯");
        en.put("tts_retry", "Wrong. Try one more time.");
        en.put("discount_label", "⏱ Parking-time Discount");
        en.put("discount_now", "Applied");
        en.put("pay_ing", "Processing WIMC Pay...");
        en.put("tts_paid", "Payment complete. Drive safely.");
        en.put("paid_done", "Payment complete — Drive safely");
        en.put("tts_return", "Returning to standby position.");
        en.put("tts_return_low", "Low battery. Returning to charging station.");
        en.put("return_done", "Return complete.");
        STR.put("en", en);

        java.util.Map<String, String> ja = new java.util.HashMap<>();
        ja.put("subtitle", "ナンバープレート末尾4桁を入力してください");
        ja.put("title", "🚗 私の車はどこ");
        ja.put("ad_skip", "スキップ ▶▶");
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
        ja.put("tts_quiz_a", "広告の視聴が完了しました。");
        ja.put("tts_quiz_b", "クイズにお答えください。");
        ja.put("tts_discount", "%dパーセント割引が適用されます。");
        ja.put("tts_no_discount", "駐車時間が短いため、まだ割引は適用されません。");
        ja.put("correct", "🎉 正解! +100 ポイント");
        ja.put("tts_correct", "正解です。100ポイントが貯まりました。");
        ja.put("point_title", "🎁 ポイント獲得");
        ja.put("point_earned", "クイズ正解！+100P 獲得");
        ja.put("point_balance_label", "保有ポイント");
        ja.put("point_use", "今回の決済に使う");
        ja.put("point_keep", "次回に貯める");
        ja.put("tts_point", "ポイントが貯まりました。今回使うか選んでください。");
        ja.put("pay_point_use", "ポイント使用");
        ja.put("wrong", "不正解です！もう一度選んでください 🎯");
        ja.put("tts_wrong", "不正解です。もう一度選んでください。");
        ja.put("quiz_retry", "残念！もう一度チャンスを 🎯");
        ja.put("tts_retry", "不正解です。もう一度挑戦してください。");
        ja.put("discount_label", "⏱ 駐車時間割引");
        ja.put("discount_now", "適用");
        ja.put("pay_ing", "WIMC Pay 決済処理中...");
        ja.put("tts_paid", "決済が完了しました。安全運転を。");
        ja.put("paid_done", "決済完了 — 安全運転を");
        ja.put("tts_return", "待機位置に戻ります。");
        ja.put("tts_return_low", "バッテリー不足です。充電ステーションに戻ります。");
        ja.put("return_done", "復帰が完了しました。");
        STR.put("ja", ja);

        java.util.Map<String, String> zh = new java.util.HashMap<>();
        zh.put("subtitle", "请输入车牌号后四位");
        zh.put("title", "🚗 我的车在哪");
        zh.put("ad_skip", "跳过 ▶▶");
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
        zh.put("tts_quiz_a", "广告观看完成。");
        zh.put("tts_quiz_b", "请回答问答。");
        zh.put("tts_discount", "已享受百分之%d的折扣。");
        zh.put("tts_no_discount", "停车时间较短，暂无折扣。");
        zh.put("correct", "🎉 答对! +100 积分");
        zh.put("tts_correct", "答对了。已获得100积分。");
        zh.put("point_title", "🎁 积分已获得");
        zh.put("point_earned", "答对了！+100P 积分");
        zh.put("point_balance_label", "我的积分");
        zh.put("point_use", "用于本次支付");
        zh.put("point_keep", "留到下次");
        zh.put("tts_point", "积分已获得。请选择是否本次使用。");
        zh.put("pay_point_use", "使用积分");
        zh.put("wrong", "答错了！请重新选择 🎯");
        zh.put("tts_wrong", "答错了。请重新选择。");
        zh.put("quiz_retry", "答错了！再给一次机会 🎯");
        zh.put("tts_retry", "答错了。请再试一次。");
        zh.put("discount_label", "⏱ 停车时长折扣");
        zh.put("discount_now", "已适用");
        zh.put("pay_ing", "正在处理 WIMC Pay 支付...");
        zh.put("tts_paid", "支付完成。请安全驾驶。");
        zh.put("paid_done", "支付完成 — 请安全驾驶");
        zh.put("tts_return", "正在返回待机位置。");
        zh.put("tts_return_low", "电量不足。正在返回充电站。");
        zh.put("return_done", "已返回待机位置。");
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
    private long parkingMinutes = 0;          // 주차 경과 시간(분) — 할인 계산용
    private int availablePoints = 0;          // 적립 후 보유 포인트 (포인트 화면 표시용)
    private int pointsUsed = 0;               // 이번 결제에 사용한 포인트 (1P = 1원)
    private Uri adVideoUri;                    // 광고 영상 URI (재생 시마다 재설정)
    private boolean awaitingAdAfterTts = false;   // 도착 음성안내 종료 후 광고 재생 대기
    private boolean awaitingReturnAfterTts = false;   // 복귀 안내 종료 후 복귀 대기
    private String returnCueText = null;          // 복귀 안내 TTS 식별용 문구

    // UI 참조 (다국어 갱신용)
    private TextView tvSubtitle;
    private Button btnSearchRef;
    private TextView tvQuizTitle, tvQuizReward, tvDiscountInfo;

    // ───── UI: 포인트 ─────
    private LinearLayout pointLayout;
    private TextView tvPointTitle, tvPointEarned, tvPointBalanceLabel, tvPointBalance;
    private Button btnUsePoints, btnKeepPoints;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        bindViews();
        initWebView();
        initAdVideo();
        setupListeners();

        setMediaVolume(5);

        try {
            dbRef = FirebaseDatabase.getInstance(DB_URL).getReference(DB_PATH);
            loadPlateSuggestions();
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
        tvDiscountInfo = findViewById(R.id.tvDiscountInfo);

        // 포인트
        pointLayout         = findViewById(R.id.pointLayout);
        tvPointTitle        = findViewById(R.id.tvPointTitle);
        tvPointEarned       = findViewById(R.id.tvPointEarned);
        tvPointBalanceLabel = findViewById(R.id.tvPointBalanceLabel);
        tvPointBalance      = findViewById(R.id.tvPointBalance);
        btnUsePoints        = findViewById(R.id.btnUsePoints);
        btnKeepPoints       = findViewById(R.id.btnKeepPoints);

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

        // 4자리 다 입력하면 키보드 자동으로 내림
        etPlateNumber.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int st, int c, int a) {}
            @Override public void onTextChanged(CharSequence s, int st, int b, int c) {}
            @Override public void afterTextChanged(Editable s) {
                if (s.length() >= 4) {
                    hideKeyboard();
                    etPlateNumber.dismissDropDown();
                }
            }
        });

        // 퀴즈 답변 버튼 (정답 비교는 한국어 기준 키로 판정)
        btnAnswer1.setOnClickListener(v -> handleQuizAnswer(false)); // 신라면 = 오답
        btnAnswer2.setOnClickListener(v -> handleQuizAnswer(true));  // 진라면 = 정답

        // 포인트 사용/적립 선택 버튼
        btnUsePoints.setOnClickListener(v -> proceedToPayment(true));   // 보유 포인트 차감
        btnKeepPoints.setOnClickListener(v -> proceedToPayment(false)); // 적립 유지

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
            boolean sel = langs[i].equals(lang);
            b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(
                    Color.parseColor(sel ? "#FF5A1F" : "#FFFFFF")));
            b.setTextColor(Color.parseColor(sel ? "#FFFFFF" : "#1A1A1A"));
        }
        // UI 텍스트 갱신
        ((TextView) findViewById(R.id.tvTitle)).setText(t("title"));
        ((Button) findViewById(R.id.btnSkipAd)).setText(t("ad_skip"));
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
        adVideoUri = Uri.parse("android.resource://" + getPackageName() + "/" + R.raw.jinramen_ad);
        // 준비(prepare) 완료 후에 재생 시작 → 첫 프레임 깨짐 방지
        videoView.setOnPreparedListener(mp -> {
            mp.setLooping(false);
            mp.start();
        });
        videoView.setOnCompletionListener(mp -> onAdComplete());   // 광고 끝나면 퀴즈로
        // 광고 스킵 버튼 → 광고 끄고 퀴즈로
        findViewById(R.id.btnSkipAd).setOnClickListener(v -> {
            videoView.stopPlayback();
            onAdComplete();
        });
    }

    @Override
    protected void onStart() {
        super.onStart();
        robot.addOnRobotReadyListener(this);
        robot.addOnGoToLocationStatusChangedListener(this);
        robot.addTtsListener(this);
        // 앱이 다시 포그라운드로 올 때(재실행 등) 멈춘 광고 화면 대신 메인으로 초기화
        backToMainScreen();
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
        if (isReady) {
            // Temi 기본 내비게이션 오버레이("가는 중입니다/도착했습니다")를 숨김
            // → 우리 앱의 광고/안내 화면이 가려지지 않게 함
            try { robot.toggleNavigationBillboard(true); } catch (Throwable ignored) {}
        }
        updateStatus(isReady ? t("ready") : t("waiting"));
    }

    // ─── 자동완성: DB의 번호판 뒷4자리 후보를 입력칸 아래에 표시 ──────────────
    private void loadPlateSuggestions() {
        if (dbRef == null) return;
        dbRef.addValueEventListener(new ValueEventListener() {   // 실시간 갱신
            @Override
            public void onDataChange(@NonNull DataSnapshot snapshot) {
                java.util.LinkedHashSet<String> set = new java.util.LinkedHashSet<>();
                for (DataSnapshot child : snapshot.getChildren()) {
                    if (readPaidStatus(child)) continue;   // 정산 완료 차량 제외
                    String l4 = child.child("last4").getValue(String.class);
                    if (l4 != null && !l4.isEmpty()) set.add(l4);
                }
                ArrayAdapter<String> adapter = new ArrayAdapter<>(
                        MainActivity.this,
                        android.R.layout.simple_dropdown_item_1line,
                        new ArrayList<>(set));
                etPlateNumber.setAdapter(adapter);
                etPlateNumber.setThreshold(1);
            }
            @Override
            public void onCancelled(@NonNull DatabaseError error) {}
        });
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
                for (DataSnapshot child : snapshot.getChildren()) {
                    // 이미 정산 완료된 잔여 레코드는 제외하고 정리
                    if (readPaidStatus(child)) {
                        child.getRef().removeValue();
                        continue;
                    }
                    results.add(child);
                }
                if (results.isEmpty()) {
                    updateStatus(t("notfound"));
                    speak(t("tts_notfound"));
                    return;
                }

                // 단일·중복 상관없이 번호판 사진 카드를 띄워 본인 차량을 선택하게 함
                if (results.size() == 1) {
                    updateStatus("차량을 찾았습니다. 번호판 사진을 확인하고 선택하세요.");
                } else {
                    updateStatus("차량이 " + results.size() + "대 검색됐습니다. 본인 차량을 선택하세요.");
                }
                showPlateSelection(results);
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
        // 요금 계산 + 주차 경과시간 저장(할인 계산용)
        parkingMinutes = minutesParked(entryTimeStr);
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
        long diffMin = minutesParked(entryTimeStr);
        if (diffMin <= 0) return 0;
        int intervals = (int) Math.ceil((double) diffMin / 10);
        return intervals * FEE_PER_10_MIN;
    }

    // 주차 경과 시간(분)
    private long minutesParked(String entryTimeStr) {
        if (entryTimeStr == null || entryTimeStr.isEmpty()) return 0;
        SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.KOREA);
        try {
            Date entryTime = fmt.parse(entryTimeStr);
            if (entryTime == null) return 0;
            long diffMin = (new Date().getTime() - entryTime.getTime()) / (1000 * 60);
            return Math.max(0, diffMin);
        } catch (Exception e) {
            return 0;
        }
    }

    // 주차 시간 기반 할인율: 1시간↑ 10%, 2시간↑ 20%, 3시간↑ 30%
    private double discountRate(long minutes) {
        if (minutes >= 180) return 0.30;
        if (minutes >= 120) return 0.20;
        if (minutes >= 60)  return 0.10;
        return 0.0;
    }

    // ─── 광고 영상 재생 화면 ─────────────────────────────────────
    private void showAdScreen() {
        runOnUiThread(() -> {
            mainLayout.setVisibility(View.GONE);
            navLayout.setVisibility(View.GONE);
            quizLayout.setVisibility(View.GONE);
            pointLayout.setVisibility(View.GONE);
            layoutWebViewContainer.setVisibility(View.GONE);
            adLayout.setVisibility(View.VISIBLE);
            adWatched = true;   // 광고 노출 → 30% 할인 자동 적용
            setMediaVolume(3);  // 광고 재생 중 볼륨 낮춤
            // setVideoURI → 준비 완료되면 onPreparedListener에서 재생 시작
            if (adVideoUri != null) videoView.setVideoURI(adVideoUri);
        });
    }

    private void onAdComplete() {
        adWatched = true;
        setMediaVolume(5);  // 광고 끝 → 음성안내 볼륨으로 복귀
        runOnUiThread(this::showQuizScreen);
    }

    // ─── 퀴즈 화면 ────────────────────────────────────────────────
    private void showQuizScreen() {
        mainLayout.setVisibility(View.GONE);
        navLayout.setVisibility(View.GONE);
        adLayout.setVisibility(View.GONE);
        pointLayout.setVisibility(View.GONE);
        quizLayout.setVisibility(View.VISIBLE);
        quizQuestion.setText(t("quiz_q"));
        btnAnswer1.setText(t("quiz_a1"));
        btnAnswer2.setText(t("quiz_a2"));
        tvQuizTitle.setText(t("quiz_title"));
        tvQuizReward.setText(t("quiz_reward"));
        tvDiscountInfo.setText(buildDiscountInfo());
        // 음성안내: 실제 적용 할인율에 맞게 동적 생성 (0%면 할인 없음 안내)
        speak(t("tts_quiz_a") + " " + buildDiscountTts() + " " + t("tts_quiz_b"));
    }

    // 현재 할인율 기반 음성 문구 (0%면 '아직 할인 없음')
    private String buildDiscountTts() {
        int rate = (int) Math.round(discountRate(parkingMinutes) * 100);
        return rate > 0 ? String.format(Locale.KOREA, t("tts_discount"), rate) : t("tts_no_discount");
    }

    // 주차 시간 할인 안내 문구 (단계표 + 현재 적용 할인)
    private String buildDiscountInfo() {
        int rate = (int) Math.round(discountRate(parkingMinutes) * 100);
        long h = parkingMinutes / 60;
        long m = parkingMinutes % 60;
        return t("discount_label") + "\n"
                + "1h↑ 10%    2h↑ 20%    3h↑ 30%\n"
                + t("discount_now") + ": " + rate + "%  (" + h + "h " + m + "m)";
    }

    private void handleQuizAnswer(boolean isCorrect) {
        if (!isCorrect) {
            // 오답: 오답 안내만, 결제로 절대 넘어가지 않음
            Toast.makeText(this, t("wrong"), Toast.LENGTH_LONG).show();
            speak(t("tts_wrong"));
            return;
        }

        // 정답(진라면)일 때만 다음 단계 진행
        quizCorrect = true;
        Toast.makeText(this, t("correct"), Toast.LENGTH_LONG).show();
        speak(t("tts_correct"));

        // 광고 시청 할인까지 적용한 결제 금액 확정 (포인트 차감은 포인트 화면에서 결정)
        finalFee = (int) Math.round(originalFee * (1 - discountRate(parkingMinutes)));
        pointsUsed = 0;

        // 100P 적립 → 최신 보유 포인트를 받아 포인트 사용/적립 선택 화면 표시
        addPointsToUser(currentPlate, QUIZ_REWARD_POINTS, total -> {
            availablePoints = total;
            runOnUiThread(this::showPointScreen);
        });
    }

    private void setMediaVolume(int level) {
        android.media.AudioManager am = (android.media.AudioManager) getSystemService(Context.AUDIO_SERVICE);
        if (am != null) am.setStreamVolume(android.media.AudioManager.STREAM_MUSIC, level, 0);
    }

    // 포인트 적립 후 갱신된 보유 포인트를 콜백으로 전달
    private interface OnPointsLoaded { void onLoaded(int total); }

    private void addPointsToUser(String plate, int points, OnPointsLoaded cb) {
        if (plate == null || dbRef == null) { if (cb != null) cb.onLoaded(0); return; }
        DatabaseReference userRef = FirebaseDatabase.getInstance(DB_URL)
                .getReference("users").child(plate).child("total_points");
        userRef.addListenerForSingleValueEvent(new ValueEventListener() {
            @Override
            public void onDataChange(@NonNull DataSnapshot snapshot) {
                Integer current = snapshot.getValue(Integer.class);
                int updated = (current == null ? 0 : current) + points;
                userRef.setValue(updated);
                if (cb != null) cb.onLoaded(updated);
            }
            @Override
            public void onCancelled(@NonNull DatabaseError error) {
                if (cb != null) cb.onLoaded(0);
            }
        });
    }

    // ─── 포인트 적립/사용 선택 화면 ──────────────────────────────
    private void showPointScreen() {
        mainLayout.setVisibility(View.GONE);
        adLayout.setVisibility(View.GONE);
        quizLayout.setVisibility(View.GONE);
        navLayout.setVisibility(View.GONE);
        layoutWebViewContainer.setVisibility(View.GONE);
        pointLayout.setVisibility(View.VISIBLE);

        int usable = Math.min(availablePoints, finalFee);   // 요금 한도 내에서만 사용 가능
        tvPointTitle.setText(t("point_title"));
        tvPointEarned.setText(t("point_earned"));
        tvPointBalanceLabel.setText(t("point_balance_label"));
        tvPointBalance.setText(String.format(Locale.KOREA, "%,dP", availablePoints));
        btnUsePoints.setText(t("point_use") + "  (-" + String.format(Locale.KOREA, "%,d", usable) + "원)");
        btnKeepPoints.setText(t("point_keep"));
        speak(t("tts_point"));
    }

    // 포인트 사용 여부 결정 후 결제 진행 (use=true면 보유 포인트를 요금 한도 내 전액 차감)
    private void proceedToPayment(boolean usePoints) {
        if (usePoints) {
            pointsUsed = Math.min(availablePoints, finalFee);
            finalFee -= pointsUsed;
            if (pointsUsed > 0 && currentPlate != null && dbRef != null) {
                // 사용한 만큼 DB 잔여 포인트 차감
                FirebaseDatabase.getInstance(DB_URL)
                        .getReference("users").child(currentPlate).child("total_points")
                        .setValue(availablePoints - pointsUsed);
            }
        } else {
            pointsUsed = 0;
        }
        pointLayout.setVisibility(View.GONE);
        showNavScreen();
        tvNavStatus.setText(t("pay_ing"));
        requestKakaoPay(finalFee, currentZone);
    }

    // ─── 결제 화면 표시 (자체 간편결제 '내차로페이', 토스 스타일 데모) ───────────
    // 외부 결제 API/제휴 없이 동작하는 자체 결제 UI. 실제 돈은 오가지 않는다.
    // [결제하기] → payment/success URL → 기존 WebView 가로채기 → handlePaymentSuccess()
    // [X / 취소] → payment/cancel → handlePaymentFailure()
    private void requestKakaoPay(int amount, String zone) {
        final int payAmount = Math.max(amount, 0);   // 포인트로 전액 결제 시 0원 허용 (자체 데모)
        final String zoneLabel = (zone == null ? "" : zone) + t("zone_suffix");
        runOnUiThread(() -> {
            updateStatus(t("pay_ing"));
            layoutWebViewContainer.setVisibility(View.VISIBLE);
            paymentWebView.loadDataWithBaseURL(
                    PAY_SUCCESS_URL, buildWimcPayHtml(payAmount, zoneLabel),
                    "text/html", "UTF-8", null);
        });
    }

    // 토스 결제창 느낌의 '내차로페이' 결제 페이지 HTML 생성
    private String buildWimcPayHtml(int payAmount, String zoneLabel) {
        String finalText = String.format(Locale.KOREA, "%,d", payAmount);
        // 할인 분리: 광고/주차 할인분과 포인트 사용분을 따로 표시
        int adDiscount = Math.max(0, originalFee - payAmount - pointsUsed);
        boolean showOrig = originalFee > 0 && originalFee > payAmount;
        String origBlock = showOrig
                ? "<div class='orig'>" + String.format(Locale.KOREA, "%,d", originalFee) + "원</div>" : "";
        String discountRow = adDiscount > 0
                ? "<div class='row'><div class='k'>주차 할인</div><div class='v'>-"
                  + String.format(Locale.KOREA, "%,d", adDiscount) + "원<span class='chev'>›</span></div></div>" : "";
        // 포인트: 사용했으면 '-원' 행, 안 썼으면 적립 안내 유지
        String pointRow = pointsUsed > 0
                ? "<div class='row'><div class='k'>" + t("pay_point_use") + "</div><div class='v'>-"
                  + String.format(Locale.KOREA, "%,d", pointsUsed) + "원<span class='chev'>›</span></div></div>"
                : "<div class='row'><div class='k'>포인트 적립</div><div class='v blue'>+100P<span class='chev'>›</span></div></div>";
        return "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            + "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            + "<style>"
            + "*{margin:0;padding:0;box-sizing:border-box;font-family:'Apple SD Gothic Neo',sans-serif;-webkit-tap-highlight-color:transparent;}"
            + "body{background:#fff;min-height:100vh;display:flex;flex-direction:column;color:#191F28;}"
            + ".close{font-size:34px;color:#191F28;padding:20px 26px;width:fit-content;}"
            + ".top{text-align:center;margin-top:10px;}"
            + ".merchant{color:#8B95A1;font-size:22px;margin-bottom:16px;}"
            + ".amount{font-size:66px;font-weight:800;letter-spacing:-1px;}"
            + ".amount small{font-size:34px;font-weight:800;margin-left:4px;}"
            + ".orig{color:#B0B8C1;font-size:28px;text-decoration:line-through;margin-top:10px;}"
            + ".rows{margin-top:56px;padding:0 28px;}"
            + ".row{display:flex;justify-content:space-between;align-items:center;padding:26px 4px;border-top:1px solid #F2F4F6;font-size:24px;}"
            + ".row:last-child{border-bottom:1px solid #F2F4F6;}"
            + ".row .k{color:#4E5968;display:flex;align-items:center;gap:14px;}"
            + ".row .v{color:#191F28;font-weight:700;display:flex;align-items:center;gap:8px;}"
            + ".dot{width:42px;height:42px;border-radius:50%;background:#FF5A1F;color:#fff;display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:800;}"
            + ".chev{color:#C4CDD5;font-size:24px;}"
            + ".blue{color:#FF5A1F;}"
            + ".spacer{flex:1;min-height:40px;}"
            + ".paybtn{margin:20px 24px 12px;background:#FF5A1F;color:#fff;border:none;font-size:30px;font-weight:700;padding:28px;border-radius:18px;width:calc(100% - 48px);}"
            + ".foot{text-align:center;color:#B0B8C1;font-size:20px;padding-bottom:26px;}"
            + "</style></head><body>"
            + "<div class='close' onclick=\"location.href='https://wimc.local/payment/cancel'\">✕</div>"
            + "<div class='top'>"
            + "<div class='merchant'>내차로 주차 정산 · " + zoneLabel + "</div>"
            + "<div class='amount'>" + finalText + "<small>원</small></div>"
            + origBlock
            + "</div>"
            + "<div class='rows'>"
            + "<div class='row'><div class='k'><span class='dot'>내</span>내차로페이</div><div class='v'>간편결제<span class='chev'>›</span></div></div>"
            + discountRow
            + pointRow
            + "</div>"
            + "<div class='spacer'></div>"
            + "<button class='paybtn' onclick=\"location.href='https://wimc.local/payment/success'\">결제하기</button>"
            + "<div class='foot'>구매 내용에 동의하면 결제해주세요</div>"
            + "</body></html>";
    }

    // ─── 결제 성공 (도착 후 결제 → 자동 복귀) ───────────────────
    private void handlePaymentSuccess() {
        runOnUiThread(() -> {
            layoutWebViewContainer.setVisibility(View.GONE);
            paymentWebView.loadUrl("about:blank");

            if (currentSnapshot != null && currentZone != null) {
                // 정산 완료 → 활성 주차 목록(parking_lot)에서 차량 레코드 삭제.
                // (DB에 남겨두면 재검색 시 '이미 정산됨'으로 처리돼 바로 복귀해버림)
                currentSnapshot.getRef().removeValue();

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
            pointLayout.setVisibility(View.GONE);
            navLayout.setVisibility(View.VISIBLE);

            tvNavZone.setText(currentZone + t("zone_suffix"));
            tvNavStatus.setText(t("navi"));
            navInfo.setText(currentZone + t("zone_suffix") + "\n" + t("navi"));
        });
    }

    private void backToMainScreen() {
        // 다음 거래를 위해 포인트 상태 초기화
        availablePoints = 0;
        pointsUsed = 0;
        runOnUiThread(() -> {
            mainLayout.setVisibility(View.VISIBLE);
            adLayout.setVisibility(View.GONE);
            quizLayout.setVisibility(View.GONE);
            navLayout.setVisibility(View.GONE);
            pointLayout.setVisibility(View.GONE);
            layoutWebViewContainer.setVisibility(View.GONE);
            etPlateNumber.setText("");
            resetResultUI();
            updateStatus(t("ready"));
        });
    }

    // ─── 공통 이동 (waypoint 소문자 정규화) ─────────────────────────
    // 이동 직전에 Firebase에서 zone을 한 번 더 읽어 카메라가 갱신한 최신 구역으로 이동한다.
    private void startNavigationAfterDelay(String zone) {
        if (zone == null || zone.trim().isEmpty()) {
            updateStatus("이동할 구역 정보가 없습니다.");
            return;
        }
        if (!isRobotReady) {
            updateStatus("Temi가 아직 준비되지 않았습니다.");
            return;
        }
        new Handler(Looper.getMainLooper()).postDelayed(
                () -> refreshZoneAndGo(zone), NAV_DELAY_MS);
    }

    // 이동 직전 Firebase에서 최신 zone 재조회 → 카메라가 갱신한 실시간 구역 반영
    private void refreshZoneAndGo(String fallbackZone) {
        if (currentPlate == null || dbRef == null) {
            goToZone(fallbackZone);
            return;
        }
        dbRef.child(currentPlate).child("zone")
                .addListenerForSingleValueEvent(new ValueEventListener() {
            @Override
            public void onDataChange(@NonNull DataSnapshot snapshot) {
                String latestZone = snapshot.getValue(String.class);
                if (latestZone == null || latestZone.trim().isEmpty()) {
                    latestZone = fallbackZone;
                }
                // 최신 구역으로 화면/상태 동기화 후 이동
                if (!latestZone.equals(currentZone)) {
                    currentZone = latestZone;
                    updateNav(latestZone, t("navi"));
                }
                goToZone(latestZone);
            }
            @Override
            public void onCancelled(@NonNull DatabaseError error) {
                goToZone(fallbackZone);   // 조회 실패 시 기존 구역으로 이동
            }
        });
    }

    private void goToZone(String zone) {
        if (zone == null || zone.trim().isEmpty() || !isRobotReady) return;
        robot.goTo(zone.trim().toLowerCase());
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
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(820, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(28, 0, 28, 0);
        card.setLayoutParams(lp);

        ImageView iv = new ImageView(this);
        LinearLayout.LayoutParams ivLp = new LinearLayout.LayoutParams(760, ViewGroup.LayoutParams.WRAP_CONTENT);
        iv.setLayoutParams(ivLp);
        iv.setBackgroundColor(Color.parseColor("#F0EFEC"));
        iv.setAdjustViewBounds(true);
        iv.setScaleType(ImageView.ScaleType.FIT_CENTER);
        if (imageUrl != null && !imageUrl.isEmpty()) {
            Glide.with(this).load(imageUrl).fitCenter().into(iv);
        }
        card.addView(iv);

        TextView tv = new TextView(this);
        tv.setText(plate);
        tv.setTextColor(Color.parseColor("#1A1A1A"));
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
                    // 복귀 완료 → 음성 안내 후 메인 화면
                    speak(t("return_done"));
                    backToMainScreen();
                } else if (currentSnapshot != null && readPaidStatus(currentSnapshot)) {
                    // 이미 결제된 차량 → 광고/결제 스킵하고 바로 복귀
                    speak(location + " " + t("arrived_paid"));
                    updateNav(location, t("paid_done"));
                    scheduleAutoReturn();
                } else {
                    // 미결제 차량 → 도착 음성안내가 끝나면 광고 영상 재생
                    awaitingAdAfterTts = true;
                    speak(location + " " + t("arrived_ad"));
                    // TTS 완료 신호가 안 오는 경우 대비한 안전 폴백(최대 10초)
                    new Handler(Looper.getMainLooper()).postDelayed(this::triggerAdAfterTts, 10000);
                }
                break;
            case OnGoToLocationStatusChangedListener.ABORT:
                updateNav(location, "이동 중단");
                if (HOME_BASE.equalsIgnoreCase(location)) {
                    // 복귀 이동이 중단됨 → 무한 반복 방지, 메인 화면으로
                    speak("이동이 중단되었습니다.");
                    backToMainScreen();
                } else {
                    // 일반 안내 중단 → 복귀 위치로 되돌아감
                    speak("이동이 중단되었습니다. 복귀하겠습니다.");
                    updateNav(HOME_BASE, "복귀 중...");
                    if (isRobotReady) robot.goTo(HOME_BASE);
                }
                break;
        }
    }

    private void updateNav(String location, String status) {
        runOnUiThread(() -> {
            tvNavStatus.setText(status);
            navInfo.setText("목적지: " + location + "\n상태: " + status + "\n방향: 직진");
        });
    }

    // ─── 자동 복귀: 복귀 안내 TTS가 끝나고 2초 뒤 복귀 위치로 이동 ──────────
    private void scheduleAutoReturn() {
        int battery = readBatteryLevel();
        returnCueText = (battery >= 0 && battery < LOW_BATTERY_THRESHOLD)
                ? t("tts_return_low") : t("tts_return");
        awaitingReturnAfterTts = true;
        speak(returnCueText);
        // TTS 완료 신호가 안 오는 경우 대비한 안전 폴백
        new Handler(Looper.getMainLooper()).postDelayed(this::triggerReturn, 8000);
    }

    // 복귀 안내 TTS 종료(또는 폴백) → 2초 뒤 복귀 위치로 이동 (1회만)
    private void triggerReturn() {
        if (!awaitingReturnAfterTts) return;
        awaitingReturnAfterTts = false;
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            updateNav(HOME_BASE, "복귀 중...");
            if (isRobotReady) robot.goTo(HOME_BASE);
        }, 2000);
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
    public void onTtsStatusChanged(@NonNull TtsRequest ttsRequest) {
        boolean completed = ttsRequest.getStatus() == TtsRequest.Status.COMPLETED;
        // 도착 음성안내(TTS)가 끝나면 광고 재생
        if (awaitingAdAfterTts && completed) {
            triggerAdAfterTts();
        }
        // 복귀 안내 TTS가 끝나면 2초 뒤 복귀 (다른 음성과 헷갈리지 않게 문구로 식별)
        if (awaitingReturnAfterTts && completed
                && returnCueText != null && returnCueText.equals(ttsRequest.getSpeech())) {
            triggerReturn();
        }
    }

    // 음성안내 종료(또는 폴백 타임아웃) 시 광고 화면 1회만 실행
    private void triggerAdAfterTts() {
        if (!awaitingAdAfterTts) return;
        awaitingAdAfterTts = false;
        runOnUiThread(this::showAdScreen);
    }

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

    private void hideKeyboard() {
        InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        View focused = getCurrentFocus();
        if (imm != null && focused != null) {
            imm.hideSoftInputFromWindow(focused.getWindowToken(), 0);
        }
        if (etPlateNumber != null) etPlateNumber.clearFocus();
    }
}

# 🔄 SESSION HANDOFF — WIMC 개발 인수인계 문서

**마지막 업데이트**: 2026-05-08
**프로젝트**: 내차로 (WIMC — Where Is My Car?)
**작업자**: 유명현 (Temi Control)

> 이 세션이 끊기거나 다른 환경에서 작업을 이어갈 때 **이 파일 하나만 보고 즉시 시작 가능**하도록 작성되었습니다. 변경 사항이 있을 때마다 최신화합니다.

---

## 🎯 즉시 알아야 할 것 (1분 요약)

- **현재 상태**: 중간 발표 완료, 최종 발표용 4가지 부가 기능 추가 예정
- **코드 위치**: `C:\wimc\wimc\` (Android 프로젝트)
- **GitHub**: `https://github.com/famouxsss24/Project-Whereismycar` (Control 브랜치 = 본인 작업)
- **빌드 상태**: ✅ 정상 (BatteryData API 수정 완료, 2026-05-08)
- **다음 작업**: 다국어 선택 UI부터 시작 권장

---

## 📂 핵심 파일 위치

### 코드 (수정 대상)
```
C:\wimc\wimc\
├── app\
│   ├── src\main\java\com\example\wimc\
│   │   └── MainActivity.java           ← 메인 로직 (320줄)
│   ├── src\main\res\layout\
│   │   └── activity_main.xml           ← 메인 UI
│   ├── src\main\res\values\
│   │   ├── strings.xml                 ← 한국어 문자열 (다국어 추가 시 사용)
│   │   ├── colors.xml                  ← 색상
│   │   └── themes.xml                  ← 테마
│   ├── google-services.json            ← Firebase 설정 (커밋됨)
│   └── build.gradle                    ← 의존성
├── build.gradle                        ← 프로젝트 레벨
└── settings.gradle                     ← Maven 저장소 (Temi SDK 포함)
```

### 발표 자료 (참고용, 더 이상 안 씀)
```
C:\Users\유명현\Desktop\광운대_정융 유명현\정융 유명현_ 2-1 과정\정융 유명현_2026_2-1_ [모바일로봇의이해 - 박수한]\
├── WIMC_프로젝트_정리.md       ← 프로젝트 전체 청사진
├── 내차로_중간발표.pptx        ← 중간 발표 PPT (14장)
├── 내차로_발표스크립트.txt     ← 발표 멘트 + Q1~Q20
├── 내차로_QnA대비.txt          ← QnA 18문항
└── 내차로\make_ppt.js          ← PPT 생성 코드
```

---

## 🔑 핵심 상수 (외워야 함)

```java
// Firebase
DB_URL  = "https://wimc-51ff9-default-rtdb.asia-southeast1.firebasedatabase.app"
DB_PATH = "parking_lot"

// 타이밍
NAV_DELAY_MS = 2500          // TTS 후 goTo 딜레이
AUTO_RETURN_DELAY_MS = 15000 // 도착 후 자동 복귀 대기

// 배터리
LOW_BATTERY_THRESHOLD = 30   // 30% 미만이면 충전소 분기

// Waypoint
HOME_BASE = "home base"      // Temi 기본 충전소 (소문자 주의!)
```

### ⚠️ Temi waypoint 대소문자
- Firebase의 zone = `"A"` (대문자)
- Temi 내부 저장 = `"a"` (소문자, SDK가 자동 변환)
- 호출 직전 **반드시 `.toLowerCase()`** 적용

---

## ✅ 구현 완료 기능 (중간 발표 기준)

### 검색
- 정규식 입력 검증 (`^\d{4}$`)
- Firebase `orderByChild("last4").equalTo()` 쿼리
- 결과 0/1/2+ 분기 처리

### 중복 차량 선택
- `HorizontalScrollView` + 동적 카드 생성 (`buildPlateCard`)
- 카드 가운데 정렬, 번호판 비율 (500×160px)
- Glide로 Azure Blob 이미지 로드

### Temi 이동
- TTS → 2.5초 대기 → `goTo(zone.toLowerCase())`
- `OnGoToLocationStatusChangedListener`: START / COMPLETE / ABORT

### 자동 복귀
- 도착 후 15초 대기
- 배터리 < 30% → "충전소" 메시지, ≥ 30% → "대기 위치" 메시지
- 둘 다 실제로는 `goTo("home base")` 호출

### 안전 장치
- `isRobotReady` boolean 가드
- zone null/빈 문자열 차단
- 키보드 자동 내림 (`InputMethodManager`)

---

## 🚧 진행할 작업 (최종 발표용 부가 기능 5개)

---

### ⭐ 우선순위 0 — 카카오페이 테스트 가맹점 결제 연동 (확정 2026-05-08)

**결정 사항**: 자체 결제(내차로페이) 가 아닌 **카카오페이 테스트 가맹점** 으로 진행

#### 기본 정보
- **테스트 가맹점 ID (CID)**: `TC0ONETIME`
- **결제 흐름**: Temi 앱 → 카카오페이 ready API → 사용자 카톡 인증 → 결제 완료 콜백 → Temi 안내 시작
- **실결제 X** (테스트 가맹점이라 가상 머니로 결제)

#### 필요한 작업
1. 카카오페이 개발자 콘솔에서 테스트 Secret Key 발급 (https://developers.kakaopay.com)
2. Firebase 스키마에 결제 필드 추가:
   - `entry_time`: 입차 시각 (밀리초 또는 yyyy-MM-dd HH:mm:ss)
   - `is_paid`: boolean
3. 검색 후 요금 계산 → `is_paid` 확인 → 미결제 시 카카오페이 ready 호출
4. WebView 띄워서 `next_redirect_mobile_url` 표시
5. WebView URL 감지로 success/fail/cancel 처리
6. 결제 완료 시 Firebase `is_paid = true` 업데이트 → Temi 출발

#### ⚠️ 발표 전 반드시 체크해야 할 것
- [ ] **Wi-Fi 안정성 확보** (Temi + 시연자 폰)
- [ ] **시연자 폰에 카카오톡 로그인** + 결제 비밀번호 숙지
- [ ] **사전 리허설 1회 이상** (결제 ready ~ 완료까지 전체 흐름)
- [ ] **콜백 URL** 처리 방식 결정:
  - 옵션 A: WebView 내 URL 감지 (서현님 코드 방식)
  - 옵션 B: Firebase Hosting URL (`https://wimc-51ff9.web.app/payment/success`)
- [ ] **Secret Key 보안 처리**:
  - `local.properties` 또는 별도 변수로 분리
  - GitHub에 노출되지 않도록 `.gitignore` 처리
- [ ] **백업 시나리오 준비** (결제 실패 시 수동으로 `is_paid = true` 업데이트할 숨겨진 버튼)

#### 알려진 위험 요소
- 발표 환경 Wi-Fi 끊기면 결제 ready API 실패
- 사용자 폰 카카오톡 비밀번호 입력 시간 변수
- 카카오페이 서버 응답 지연 가능 (보통 1~3초)
- WebView 콜백 URL 감지 실패 시 결제 완료 인식 못 함

#### 발표 멘트 (예상 질문 대비)
> Q: "진짜 결제 되나요?"
> A: "**카카오페이 테스트 가맹점 TC0ONETIME** 으로 가상 머니 결제로 시연합니다. 카톡 인증·결제 완료까지 실제 흐름과 동일하지만, 실제 카드에서 돈은 빠지지 않습니다. 상용 환경에서는 사업자 등록 후 가맹점 Secret Key로 교체하면 그대로 동작합니다."

> Q: "Secret Key 노출 안 되나요?"
> A: "본 데모는 테스트 키로 가상 결제만 처리 가능합니다. 상용 배포 시에는 우리 백엔드 서버를 경유해 Secret Key를 클라이언트에 두지 않는 구조로 전환합니다."

#### 데이터 흐름
```
[1] 사용자 8016 입력
[2] Firebase orderByChild("last4").equalTo("8016")
[3] entry_time, is_paid 확인
[4] is_paid = true → 바로 안내 시작
    is_paid = false →
      [5] 요금 계산
      [6] 카카오페이 ready API 호출 (Secret Key 사용)
      [7] next_redirect_mobile_url 받음 → WebView 표시
      [8] 사용자 카톡 인증 + 결제
      [9] WebView 콜백 URL 감지 → is_paid = true 업데이트
      [10] Temi 안내 시작
```

#### 필요한 라이브러리 (build.gradle)
```gradle
// 카카오페이 API 호출은 표준 HttpURLConnection 사용 (별도 SDK 불필요)
// JSON 파싱: org.json (Android 내장)
// WebView: android.webkit.WebView (Android 내장)
```

---

### 우선순위 1 — 다국어 선택 UI ⭐
**난이도**: 쉬움 / **예상 시간**: 1시간

#### 구현 포인트
- 메인 화면 상단에 4개 언어 버튼 (🇰🇷 🇺🇸 🇯🇵 🇨🇳)
- 음성 인식 X, **텍스트만** 다국어
- TTS는 Temi 내장 엔진이 언어 자동 인식

#### 필요한 변경
1. `res/values-en/strings.xml`, `values-ja/`, `values-zh/` 생성
2. 또는 코드 내 `Map<String, Map<String, String>>` 사용
3. 언어 버튼 클릭 시 동적 텍스트 갱신
4. `Robot.speak()` 호출 시 `TtsRequest.Language` 옵션 (SDK 확인 필요)

#### 4개 언어 핵심 문구

| 한국어 | English | 日本語 | 中文 |
|--------|---------|--------|------|
| 내 차로 | WIMC | 私の車へ | 我的车 |
| 차량 번호판 뒷 4자리를 입력하세요 | Enter last 4 digits | 末尾4桁を入力 | 请输入车牌后四位 |
| 차량 찾기 | Find My Car | 車を探す | 查找车辆 |
| A 구역으로 안내합니다 | Guiding to Zone A | A区域へご案内 | 正在前往A区 |
| 본인 차량을 선택하세요 | Select your vehicle | 自分の車両を選択 | 选择您的车辆 |
| 안전 운전 하세요 | Drive safely | 安全運転を | 安全驾驶 |
| 등록된 차량이 없습니다 | Vehicle not found | 車両が見つかりません | 未找到车辆 |
| Temi 준비 완료 | Temi ready | Temi 準備完了 | Temi 准备就绪 |

---

### 우선순위 2 — 차량 사진 도착 직전 재확인
**난이도**: 쉬움 / **예상 시간**: 1시간

#### 구현 포인트
- `onGoToLocationStatusChanged` COMPLETE 콜백에서 트리거
- `AlertDialog` 또는 별도 화면
- 기존 `image_url` 재활용 (Glide)

#### 화면 구성
```
┌─────────────────────┐
│  이 차량이 맞으신가요? │
│                      │
│  [번호판 이미지]       │
│   67나 8016          │
│                      │
│  [네, 맞아요]  [아니오]│
└─────────────────────┘
```

#### 동작
- "네, 맞아요" → `scheduleAutoReturn()` 호출
- "아니오" → 메인 화면 복귀, `resetResultUI()`
- 5초 응답 없으면 자동 "네" 처리

#### 필요한 새 필드 (MainActivity)
```java
private String lastImageUrl;   // 현재 안내 중인 차량의 이미지 URL
private String lastPlate;      // 현재 안내 중인 차량 번호
```

---

### 우선순위 3 — 만족도 평가 + 재방문 쿠폰
**난이도**: 중간 / **예상 시간**: 1~2시간

#### 구현 포인트
- 차량 확인 완료 후 별점 화면
- Firebase `ratings` 노드에 저장
- 별점 입력 후 QR 코드 표시

#### Firebase 스키마 추가
```
ratings/
  └── {plate}_{timestamp}/
        ├── plate: "67나8016"
        ├── rating: 5
        └── timestamp: 1714005000000

coupons/
  └── default_coupon/
        ├── code: "REVISIT2026"
        ├── discount: "20%"
        └── description: "다음 방문 시 주차 요금 20% 할인"
```

#### QR 라이브러리
- ZXing (`com.google.zxing:core:3.5.2`)
- 또는 외부 API: `https://api.qrserver.com/v1/create-qr-code/?data=`

---

### 우선순위 4 — 출차 종합 정보 디스플레이
**난이도**: 중간 / **예상 시간**: 2~3시간 (상지님 협조 필요)

#### 화면 구성 (이동 중)
```
┌─────────────────────────────────┐
│ 🚗 67나8016 → A 구역 안내 중      │
│                                  │
│  ⏱️  주차 시간    2시간 15분      │
│  💰  예상 요금    4,500원         │
│  🚪  가까운 출구  동문 (50m)      │
│                                  │
│  [지금 결제하기]                 │
└─────────────────────────────────┘
```

#### 필요한 데이터
- **입차 timestamp** (상지님이 Firebase에 추가 푸시해야 함)
- 요금표 (시간당 X원 — Firebase `config/rate_per_hour`)
- 출구 매핑 (`config/exit_mapping/{zone}`)

#### 상지님께 부탁
```python
db.reference(f"parking_lot/{plate}").set({
    "zone": zone,
    "last4": plate[-4:],
    "image_url": blob_url,
    "timestamp": int(time.time() * 1000)   # ← 이 줄 추가
})
```

#### Firebase 스키마 추가
```
config/
  ├── rate_per_hour: 2000
  └── exit_mapping/
        ├── A: "동문 (50m)"
        ├── B: "서문 (80m)"
        └── C: "남문 (120m)"
```

---

## 🎨 디자인 가이드 (변경하지 말 것)

### 컬러
```
배경 메인:    #1A1A2E   (어두운 보라)
카드 배경:    #2A2A3E
강조·버튼:    #E94560   (빨강)
흰색 텍스트:  #FFFFFF
회색 텍스트:  #AAAAAA
보조 회색:    #555555
```

### 폰트 크기 (sp)
```
타이틀:       56sp
부제목:       22sp
입력창:       56sp
버튼:         26sp
큰 구역:      80sp
카드 라벨:    32sp
카드 번호판:  28sp
상태 메시지:  20sp
```

---

## 🤝 팀 협업 상태

### 상지님 (Vision) — Vision 브랜치
- ✅ Azure App Service + Blob 운영 중
- ✅ Firebase Push 동작 중
- 🟡 **부탁할 것**: OCR 시점에 `timestamp` 필드 같이 push (출차 정보 기능 위해)

### 서현님 (Database / 결제)
- 🟡 결제 UI 디자인 작업 중 (Control 브랜치 참고 중)
- 디자인 톤: `#E94560` + `#1A1A2E`

### 기범님 (UI/UX)
- 🟡 결제 화면 + 추가 기능 UI 디자인

---

## 🛠️ 자주 쓰는 명령어

### Git
```bash
cd C:/wimc/wimc
git add .
git commit -m "메시지"
git push
```

### PowerShell에서 Gradle 빌드 (JAVA_HOME 임시 설정)
```powershell
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
$env:PATH="$env:JAVA_HOME\bin;$env:PATH"
.\gradlew.bat :app:assembleDebug
```

### Temi ADB 연결
```powershell
adb connect <Temi-IP>:5555
adb devices
```

### PPT 재생성 (옛 발표 자료)
```bash
cd "C:/Users/유명현/Desktop/광운대_정융 유명현/정융 유명현_ 2-1 과정/정융 유명현_2026_2-1_ [모바일로봇의이해 - 박수한]/내차로"
node make_ppt.js
```

---

## 🧠 컨텍스트 (왜 이렇게 설계했는지)

### Q: 왜 Java?
- 수업에서 Java 권장
- Temi SDK 문서가 Java 기준

### Q: 왜 Firebase Realtime DB (Firestore 아님)?
- WebSocket 기반 실시간 동기화
- 단순 key-value 구조에 최적
- 평균 응답 1초 이내

### Q: 왜 Firebase + Azure 하이브리드?
- 메타데이터 = Firebase (검색·실시간 동기화 강점)
- 이미지 = Azure Blob (대용량 파일 강점)
- 앱은 Firebase 한 경로만 조회 → 클라이언트 복잡도 ↓

### Q: 왜 2.5초 딜레이?
- `robot.speak()` 비동기 → 즉시 반환
- 음성 도중 `goTo()` 호출하면 사용자가 안내 듣기 전에 출발
- 한국어 안내 멘트 평균 길이 2.5초

### Q: 왜 toLowerCase?
- Temi SDK가 waypoint 이름을 내부적으로 소문자 저장
- Firebase에는 대문자 "A"로 저장
- Logcat hex 덤프로 발견 (U+0041 vs U+0061)

### Q: 왜 자동 복귀?
- 다음 사용자 호출 대비
- 단일 안내 → 풀 사이클 운영 시나리오 완성

### Q: 왜 4대 카메라?
- 데모 환경 구성 (상지님 결정)
- 각 카메라가 자기 영역 담당 + 사선 설치로 번호판 가시성 확보

---

## 🐛 알려진 이슈 & 트러블슈팅 히스토리

### ✅ 해결됨

| 이슈 | 원인 | 해결 |
|------|------|------|
| Maven 저장소 못 찾음 | settings.gradle 등록 누락 | Temi Maven URL 추가 |
| 앱 설치 불가 | minSdk 24 vs Temi API 23 | minSdk 23으로 |
| TTS 도중 이동 시작 | speak() 비동기 충돌 | Handler 2.5초 딜레이 |
| Vision↔Firebase 연동 | HTTP POST vs Firebase 직접 | Firebase Admin SDK로 통일 |
| Waypoint 매칭 실패 | 대소문자 불일치 | `.toLowerCase()` 정규화 |
| Firebase 검색 일부만 매칭 | number vs string 타입 차이 | Firebase 콘솔에서 ABC(string) 통일 |
| Azure 이미지 안 뜸 | SAS 토큰 시작/만료 역전 | public access로 전환 또는 토큰 재생성 |
| 중복 결과 카드 안 보임 | 키보드가 가림 | `hideSoftInputFromWindow` 호출 |
| 빌드 실패 (배터리) | `getLevel()` 없음 (SDK 1.131.1) | `getBatteryPercentage()` 로 수정 |

### 🟡 알려진 한계 (해결 안 함)

- Temi waypoint는 기기 로컬 저장 → 다중 로봇 운영 시 각각 등록 필요
- 카메라 캘리브레이션은 수동 (`section_box` 설정)
- 야간·역광 환경 OCR 정확도 저하 가능
- Firebase Security Rules가 테스트 모드 (발표 후 강화 필요)

---

## 📝 변경 이력 (Changelog)

### 2026-05-08
- ✅ `BatteryData.getLevel()` → `getBatteryPercentage()` 수정 (빌드 실패 해결)
- ✅ Codex 코드 리뷰 결과 반영
- ✅ `SESSION_HANDOFF.md` 작성
- 🎯 **결제 방식 결정**: 카카오페이 테스트 가맹점 `TC0ONETIME` 직접 연동으로 진행
  - 자체 결제(내차로페이) 옵션은 백업으로 보류
  - WebView + 카카오페이 ready API + 카톡 인증 흐름
  - 발표 전 Wi-Fi 안정성 + 카톡 로그인 + 사전 리허설 필수

### 2026-05-07
- ✅ Waypoint 대소문자 트러블슈팅 (hex 덤프 디버깅)
- ✅ 자동 복귀 + 배터리 분기 코드 추가
- ✅ 키보드 자동 내림 추가
- ✅ UI 사이즈 키움 (입력창·버튼·카드)
- ✅ 테스트 버튼 제거
- ✅ GitHub Control 브랜치 push
- ✅ 중간 발표 자료 완성 (14장 PPT)

### 2026-05-06
- ✅ Firebase 연결 + 데이터 구조 설계
- ✅ 중복 차량 이미지 카드 UI
- ✅ Glide 이미지 로딩

---

## 🎤 발표 시 핵심 메시지

> **"단순 주차 안내가 아닌, 출차의 모든 순간을 통합한 다국어 종합 경험 플랫폼."**

다국어 환영 → 차량 검색 → 안내 → 사진 재확인 → 도착 → 만족도 평가 → 쿠폰 → 자동 복귀까지, 한 사이클로 완결되는 사용자 경험.

---

## 🆘 새 세션에서 작업 이어가는 법

1. **이 파일(`SESSION_HANDOFF.md`)을 처음에 보여주기**
2. 현재 작업 중인 우선순위 확인 (위 "진행할 작업" 섹션)
3. 변경 이력 보고 어디까지 왔는지 파악
4. 코드 파일 직접 읽어서 현재 상태 확인:
   - `app/src/main/java/com/example/wimc/MainActivity.java`
   - `app/src/main/res/layout/activity_main.xml`
5. 작업 시작

### 새 세션 시작 프롬프트 예시
```
이 프로젝트는 Temi 로봇 기반 주차 안내 시스템 WIMC야.
C:\wimc\wimc\SESSION_HANDOFF.md 파일을 먼저 읽고 현재 상태 파악해줘.
그 다음 [작업할 내용] 를 진행해줘.
```

---

**이 문서는 작업이 진행될 때마다 최신화됩니다.**
중요한 결정·구현·트러블슈팅이 있을 때마다 "변경 이력" 섹션에 추가하세요.

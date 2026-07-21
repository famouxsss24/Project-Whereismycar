# Android / Firebase / Temi 코드 품질 평가

점검 경로: `C:\wimc\wimc`  
점검일: 2026-06-13  
범위: Android Studio 앱 코드, Firebase 연동, Temi SDK 제어 흐름  
제외: `C:\wimc\vision` Python 구현 품질. 단, Android 앱이 Firebase에서 받는 데이터 구조는 연동 관점에서만 봄.

## 한 줄 결론

Android 앱 코드는 지금 기준으로 "스파게티 코드 성향이 강한 편"입니다. 특히 `MainActivity.java` 하나가 화면, Firebase, Temi 이동, TTS, 광고, 퀴즈, 결제 데모, 다국어 처리를 전부 들고 있어서 수정 난이도가 높습니다.

다만 "손대면 안 되는 수준"은 아닙니다. 핵심 흐름은 한 파일 안에 모여 있어서 읽히긴 합니다. 문제는 기능을 추가하거나 버그를 고칠 때 사이드 이펙트를 예측하기 어렵다는 점입니다.

## 현재 상태 요약

### 좋게 볼 수 있는 점

- 앱의 핵심 흐름은 한 곳에 모여 있어 처음 추적할 때 진입점이 명확합니다.
- Firebase에서 `last4`, `zone`, `image_url`, `entry_time`, `is_paid`를 읽고 Temi 이동으로 연결하는 흐름은 대략 파악 가능합니다.
- Temi 이동 직전에 Firebase의 최신 `zone`을 다시 읽는 로직이 있어, 카메라/비전 쪽에서 위치가 갱신되는 상황을 고려했습니다.
- 다국어 문자열이 코드 안에라도 모여 있어, 완전히 흩어진 상태는 아닙니다.

### 나쁘게 볼 수 있는 점

- `MainActivity.java`가 1,075줄입니다. Activity 하나가 앱 전체 백엔드, 프론트, 로봇 제어, 결제 흐름을 모두 담당합니다.
- `activity_main.xml`도 368줄이고, 한 레이아웃 안에 검색, 광고, 퀴즈, 네비게이션, 결제 WebView 화면이 모두 들어 있습니다.
- 상태값이 `currentPlate`, `currentZone`, `currentSnapshot`, `originalFee`, `finalFee`, `adWatched`, `quizCorrect`, `awaitingAdAfterTts`, `awaitingReturnAfterTts`처럼 Activity 필드에 흩어져 있습니다.
- Firebase 콜백, Handler 지연 실행, Temi 콜백, TTS 콜백이 서로 Activity 필드를 공유합니다. 그래서 순서가 조금만 꼬여도 예상 밖 화면 전환이나 이동이 나올 수 있습니다.
- 테스트는 기본 샘플 수준이라 핵심 기능을 보호하지 못합니다.

## 스파게티 판단

### 점수

유지보수 난이도: 8 / 10  
스파게티 위험도: 8 / 10  
당장 기능 수정 가능성: 5 / 10  
리팩터링 후 회복 가능성: 8 / 10

정리하면, 현재는 "작동하게 붙여 만든 프로토타입 코드"에 가깝습니다. 발표/시연용으로 빠르게 기능을 붙인 흔적이 강하고, 장기 유지보수용 구조는 아닙니다.

## 가장 큰 문제 1: `MainActivity`가 너무 많은 책임을 가짐

파일: `app/src/main/java/com/example/wimc/MainActivity.java`

현재 `MainActivity`가 담당하는 일:

- View 바인딩
- 언어 선택 및 다국어 문구 관리
- Firebase 연결 및 번호판 검색
- Firebase 레코드 삭제
- 차량 선택 UI 생성
- 주차요금 계산
- 광고 VideoView 제어
- 퀴즈 처리
- 포인트 적립
- 결제 WebView HTML 생성
- 결제 성공/실패 처리
- Temi 준비 상태 처리
- Temi 목적지 이동
- Temi 이동 상태 콜백 처리
- TTS 완료 콜백 처리
- 복귀 로직
- 배터리 확인

이 정도면 Activity가 컨트롤러가 아니라 앱 전체가 된 상태입니다. 그래서 "차량 검색만 바꾸고 싶은데 광고/결제/복귀가 같이 영향받는" 구조입니다.

## 가장 큰 문제 2: 상태 전환이 명시적이지 않음

앱은 실제로 아래 상태 머신처럼 동작합니다.

1. 메인 화면
2. 번호판 검색
3. 차량 선택
4. Temi 이동 시작
5. 도착
6. 광고 재생
7. 퀴즈
8. 결제 데모
9. 결제 완료
10. 복귀
11. 메인 화면

그런데 코드에는 이 상태가 `enum`이나 상태 객체로 표현되어 있지 않습니다. 대신 여러 boolean과 문자열 필드가 각 콜백에서 직접 바뀝니다.

위험한 필드 예:

- `currentSnapshot`
- `currentPlate`
- `currentZone`
- `adWatched`
- `quizCorrect`
- `awaitingAdAfterTts`
- `awaitingReturnAfterTts`
- `returnCueText`

이 방식은 처음 만들 때는 빠르지만, 나중에 "광고를 스킵했을 때", "Temi 이동이 중단됐을 때", "결제 중 앱이 백그라운드로 갔을 때", "Firebase zone이 중간에 바뀌었을 때" 같은 예외 케이스에서 깨지기 쉽습니다.

## 가장 큰 문제 3: Firebase 읽기와 쓰기 부작용이 화면 코드 안에 있음

번호판 검색 중 이미 정산 완료된 차량이면 바로 Firebase 레코드를 삭제합니다.

```java
if (readPaidStatus(child)) {
    child.getRef().removeValue();
    continue;
}
```

결제 성공 시에도 `parking_lot` 레코드를 삭제합니다.

```java
currentSnapshot.getRef().removeValue();
```

이 정책 자체가 틀렸다는 뜻은 아닙니다. 다만 삭제 정책이 UI Activity 안에 박혀 있어서 위험합니다. 나중에 "삭제하지 말고 `is_paid=true`로 남겨야 한다", "결제 이력을 따로 저장해야 한다", "비전 쪽 재감지와 충돌한다" 같은 요구가 오면 Activity 전체 흐름을 다시 봐야 합니다.

권장 방향:

- `ParkingRepository` 같은 클래스로 Firebase 읽기/쓰기 분리
- 검색 결과 필터링과 DB 삭제 정책 분리
- 결제 완료 시 `parking_lot` 삭제와 `payment_history` 기록을 별도 메서드로 명확화

## 가장 큰 문제 4: Temi 이동/TTS/광고 타이밍이 콜백에 강하게 묶임

Temi 도착 후 광고 재생은 TTS 완료 콜백 또는 10초 fallback으로 실행됩니다.

```java
awaitingAdAfterTts = true;
speak(location + " " + t("arrived_ad"));
new Handler(Looper.getMainLooper()).postDelayed(this::triggerAdAfterTts, 10000);
```

복귀도 TTS 완료 콜백 또는 8초 fallback을 사용합니다.

```java
awaitingReturnAfterTts = true;
speak(returnCueText);
new Handler(Looper.getMainLooper()).postDelayed(this::triggerReturn, 8000);
```

이 구조는 현장에서 TTS 콜백이 안정적이지 않을 때를 대비한 현실적인 처리입니다. 하지만 Handler 작업을 취소하거나 화면 상태와 묶어 관리하지 않기 때문에, 앱이 메인으로 돌아간 뒤 이전 지연 작업이 늦게 실행될 가능성이 있습니다.

권장 방향:

- `Handler`를 필드로 하나만 두고 예약 작업을 취소 가능하게 만들기
- 화면 복귀 시 광고/복귀 관련 pending 작업 제거
- `awaiting...` boolean 대신 `FlowState` enum 사용

## 가장 큰 문제 5: 보안/설정값이 코드에 섞여 있음

`MainActivity.java`에 Firebase URL과 KakaoPay 관련 상수가 직접 들어 있습니다.

```java
private static final String DB_URL = "...";
private static final String KAKAO_SECRET_KEY = "...";
```

현재 결제는 실제 KakaoPay API가 아니라 WebView HTML 데모에 가까워 보입니다. 그래도 `SECRET_KEY`라는 이름의 값이 앱 코드에 들어가 있으면 오해와 보안 리스크가 생깁니다.

권장 방향:

- 데모 결제면 KakaoPay 상수와 사용하지 않는 네트워크 코드 제거
- 실제 결제면 절대 앱에 secret key를 넣지 말고 서버에서 결제 ready/approve 처리
- Firebase URL은 `BuildConfig` 또는 설정 파일로 분리

## 가장 큰 문제 6: UI 생성 방식이 섞여 있음

대부분의 화면은 XML에 있지만, 번호판 선택 카드는 Java 코드에서 직접 만듭니다.

```java
LinearLayout card = new LinearLayout(this);
ImageView iv = new ImageView(this);
TextView tv = new TextView(this);
```

작은 프로토타입에서는 괜찮지만, 카드 디자인이나 접근성, 화면 크기 대응을 수정하려면 Java 로직을 건드려야 합니다.

권장 방향:

- `item_plate_card.xml` 생성
- `LayoutInflater`로 카드 inflate
- 가능하면 `RecyclerView`로 변경

## 테스트 상태

Android 테스트는 사실상 기본 샘플만 있습니다.

- `ExampleUnitTest`: `2 + 2 = 4`
- `ExampleInstrumentedTest`: 패키지명 확인

즉, 아래 핵심 기능은 테스트로 보호되지 않습니다.

- 번호판 4자리 검색
- 중복 차량 선택
- paid 차량 필터링
- zone 누락 처리
- 주차요금 계산
- 광고/퀴즈 후 결제 금액 계산
- Temi 이동 전 최신 zone 재조회
- 도착 후 광고 재생
- 결제 성공 후 DB 삭제 및 복귀

특히 주차요금 계산, 상태 전환, Firebase 데이터 매핑은 Activity 밖으로 빼면 단위 테스트가 가능합니다.

## 지금 당장 건드릴 때 조심할 지점

가장 위험한 수정 지점:

- `processVehicleSelection()`: 차량 선택 이후 모든 흐름의 시작점
- `onGoToLocationStatusChanged()`: 도착, 광고, 복귀가 모두 연결됨
- `handlePaymentSuccess()`: Firebase 삭제와 복귀 트리거가 같이 있음
- `backToMainScreen()`: 화면 초기화만 하는 것처럼 보이지만 기존 예약 Handler 작업은 명시적으로 취소하지 않음
- `refreshZoneAndGo()`: 이동 직전 최신 zone을 다시 읽기 때문에 `currentZone`이 중간에 바뀔 수 있음

수정 전에는 "이 메서드가 어떤 화면/로봇 상태에서 호출되는가"를 먼저 확인해야 합니다.

## 추천 리팩터링 순서

### 1단계: 도메인 로직만 Activity 밖으로 빼기

가장 안전한 첫 단계입니다. UI와 Temi는 그대로 두고, 순수 계산/판정만 분리합니다.

분리 후보:

- `ParkingFeeCalculator`
- `VehicleRecord`
- `PaymentSummary`
- `LanguageStrings`

이 단계에서 테스트 추가:

- `minutesParked`
- `calculateParkingFee`
- `discountRate`
- 최종 결제금액 계산

### 2단계: Firebase 접근 분리

`ParkingRepository`를 만들고 아래 책임을 옮깁니다.

- `loadPlateSuggestions`
- `searchByLast4`
- `readPaidStatus`
- `refreshZone`
- `removeParkingRecord`
- `addPointsToUser`

Activity는 "검색 요청 → 결과를 받아 화면 표시"만 하게 만듭니다.

### 3단계: Temi 제어 분리

`TemiNavigator` 또는 `RobotController`를 만들어 아래를 옮깁니다.

- robot ready 관리
- `goToZone`
- `speak`
- 배터리 조회
- 복귀 명령

Activity가 Temi SDK 객체를 직접 만지는 구간을 줄이면 시뮬레이터/테스트가 쉬워집니다.

### 4단계: 화면 상태를 enum으로 명시

예:

```java
enum FlowState {
    MAIN,
    SELECTING_VEHICLE,
    NAVIGATING_TO_CAR,
    ARRIVED,
    PLAYING_AD,
    QUIZ,
    PAYMENT,
    RETURNING
}
```

이렇게 하면 지금처럼 boolean 여러 개가 서로 암묵적으로 상태를 만드는 문제를 줄일 수 있습니다.

### 5단계: 레이아웃 분리

- `activity_main.xml`은 컨테이너만 유지
- 검색 화면, 광고 화면, 퀴즈 화면, 네비게이션 화면, 결제 화면을 별도 XML 또는 Fragment로 분리
- 번호판 카드는 `item_plate_card.xml`로 분리

## 추천 목표 구조

```text
app/src/main/java/com/example/wimc/
  MainActivity.java              // 화면 전환과 사용자 이벤트만 담당
  data/
    ParkingRepository.java       // Firebase 읽기/쓰기
    VehicleRecord.java           // Firebase 차량 데이터 모델
  robot/
    TemiNavigator.java           // Temi SDK 래핑
  payment/
    PaymentCalculator.java       // 요금/할인 계산
    DemoPaymentPageBuilder.java  // WebView 데모 결제 HTML
  ui/
    LanguageStrings.java         // 다국어 문구
    FlowState.java               // 앱 상태
```

이 정도만 해도 `MainActivity`는 1,075줄에서 300~400줄대로 줄일 수 있습니다.

## 최종 평가

지금 코드는 "기능은 붙어 있는데, 책임 분리가 안 된 상태"입니다. 그래서 사용자가 느끼는 "내가 건드릴 수가 없다"는 감각은 꽤 정확합니다.

하지만 망한 코드는 아닙니다. 오히려 핵심 로직이 한 파일에 몰려 있어서, 순서를 정해 빼내면 회복이 빠른 편입니다. 처음부터 전면 재작성하지 말고, 계산 로직 → Firebase → Temi → 화면 상태 순서로 분리하는 게 가장 안전합니다.

가장 먼저 할 일은 `MainActivity`에서 순수 Java 로직을 빼고 테스트를 붙이는 것입니다. 그 다음 Firebase와 Temi를 래퍼 클래스로 분리하면, 이후 기능 수정이 훨씬 덜 무서워집니다.


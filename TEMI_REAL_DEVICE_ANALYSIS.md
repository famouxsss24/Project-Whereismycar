# WIMC TEMI 실기기 구동 가능성 분석

점검 경로: `C:\wimc\wimc`  
점검일: 2026-06-03  
대상: Android TEMI 앱 `com.example.wimc`

## 결론

2026-06-03 재점검 기준으로 `assembleDebug` 빌드는 성공합니다. 따라서 이제는 실제 TEMI에 설치 가능한 debug APK가 생성되는 상태입니다.

구조 자체는 TEMI SDK 기반 Android 앱으로 방향이 맞고, `Robot.goTo()`, `OnRobotReadyListener`, `OnGoToLocationStatusChangedListener`, TTS 사용 방식도 TEMI SDK 계열과 대체로 맞습니다. 발표 데모 기준에서는 “차량 검색 → 이동 → 도착 → 광고 → 퀴즈 → 결제 화면 → 복귀” 한 사이클을 자연스럽게 보여주는 데 초점을 두면 됩니다.

판단 등급:

- 현재 APK 생성 가능성: 높음
- 단일 발표 데모 성공 가능성: 높음
- 운영/상용 안정성 평가는 이번 범위에서 제외

## 확인한 빌드 결과

실행 명령:

```powershell
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
.\gradlew.bat assembleDebug
```

결과:

```text
BUILD SUCCESSFUL
```

생성된 APK:

```text
C:\wimc\wimc\app\build\outputs\apk\debug\app-debug.apk
```

## 치명 이슈

### 1. 현재 APK 빌드 실패 문제는 해결됨

파일: `app/src/main/java/com/example/wimc/MainActivity.java:469-480`

이전에는 `conn.getResponseCode()`를 람다 안에서 다시 호출해 Java 컴파일이 실패했습니다. 현재는 `responseCode` 변수에 저장한 뒤 람다에서 사용하도록 수정되어 빌드가 통과합니다.

현재 형태:

```java
int responseCode = conn.getResponseCode();
if (responseCode == 200) {
    ...
} else {
    runOnUiThread(() -> updateStatus("결제 API 응답 오류 (" + responseCode + ")"));
}
```

### 2. 카카오페이 API URL은 최신 온라인 결제 ready 형태로 수정됨

파일: `app/src/main/java/com/example/wimc/MainActivity.java:78`

현재:

```java
private static final String KAKAO_READY_URL  = "https://open-api.kakaopay.com/online/v1/payment/ready";
```

카카오페이 개발자센터/포럼 예시에서 보이는 온라인 결제 ready URL 형태와 맞습니다. 다만 ready 이후 승인 API까지 처리하는지는 별도 문제입니다.

공식/준공식 확인 자료:

- KakaoPay Developers: https://developers.kakaopay.com/
- KakaoPay forum example: https://developers.kakaopay.com/forum/t/how-to-get-pg-token/482

### 3. 결제 성공 처리 방식은 여전히 실제 결제 승인 검증이 아님

파일: `app/src/main/java/com/example/wimc/MainActivity.java:460-493`

현재 코드는 `approval_url`을 `https://localhost/payment/success`로 넣고, WebView URL에 `payment/success` 문자열이 보이면 바로 결제 성공으로 처리합니다. 하지만 카카오페이 단건 결제는 보통 ready 이후 `tid`와 `pg_token`을 받아 승인 API를 한 번 더 호출해야 최종 결제로 확정됩니다.

발표용으로는 “테스트 결제 완료처럼 보이는 화면 전환”은 가능할 수 있지만, 실제 결제 완료 검증 로직으로는 부족합니다.

### 4. Secret Key가 앱 소스에 하드코딩되어 있음

파일: `app/src/main/java/com/example/wimc/MainActivity.java:68`

```java
private static final String KAKAO_SECRET_KEY = "...";
```

테스트 키라면 발표 데모에는 큰 문제는 아니지만, APK에 그대로 들어가므로 누구나 추출할 수 있습니다. 실제 운영에서는 반드시 서버에서 ready/approve를 처리해야 합니다.

## TEMI 실기기 관련 위험

### 1. TEMI 위치명이 정확히 저장되어 있어야 함

파일: `app/src/main/java/com/example/wimc/MainActivity.java:555-566`

현재 Firebase `zone` 값을 소문자로 바꿔서 `robot.goTo(target)`를 호출합니다.

```java
final String target = zone.trim().toLowerCase();
robot.goTo(target);
```

이 로직은 TEMI 내부 맵에 `a`, `b`, `c` 같은 위치가 정확히 저장되어 있을 때만 동작합니다. TEMI에 저장된 위치명이 `A`, `A구역`, `zone a` 등으로 다르면 이동이 실패합니다.

권장:

- 실기기에서 TEMI Location 이름을 미리 `a`, `b`, `c`로 저장
- 앱 시작 시 `robot.getLocations()`로 실제 저장 위치 목록을 표시하거나 로그 출력
- Firebase `zone`과 TEMI 위치명을 매핑 테이블로 분리

### 2. TEMI 준비 전 검색하면 이동이 중단되고 자동 재시도하지 않음

파일: `app/src/main/java/com/example/wimc/MainActivity.java:560-563`

`isRobotReady == false`이면 상태 메시지만 띄우고 끝납니다. 사용자는 다시 검색해야 합니다. 발표장에서는 앱 실행 직후 바로 입력하면 “TEMI가 아직 준비되지 않았습니다”에서 멈출 수 있습니다.

권장:

- 검색 버튼을 `isRobotReady` 이후 활성화
- 또는 준비 전 요청을 큐에 넣고 ready 콜백에서 자동 실행

### 3. 이동 상태 중 일부만 처리함

파일: `app/src/main/java/com/example/wimc/MainActivity.java:631-652`

처리 중인 상태는 `START`, `COMPLETE`, `ABORT`뿐입니다. TEMI SDK 문서에는 `CALCULATING`, `GOING`, `REPOSING` 등도 있습니다. 현재도 이동은 가능하지만, 장애물/경로 계산/재위치잡기 상태를 UI에 제대로 반영하지 못합니다.

TEMI SDK 위치 상태 문서:

- https://github-wiki-see.page/m/robotemi/sdk/wiki/Locations

### 4. Manifest의 TEMI 메타데이터가 부족할 수 있음

파일: `app/src/main/AndroidManifest.xml:17-19`

현재는 `com.robotemi.sdk.metadata.SKU`만 있습니다.

```xml
<meta-data
    android:name="com.robotemi.sdk.metadata.SKU"
    android:value="temi_v1" />
```

TEMI SDK Wiki는 앱을 TEMI OS 앱/스킬로 노출하는 메타데이터 예시로 `com.robotemi.sdk.metadata.SKILL`을 안내합니다. 런처 앱으로 직접 실행은 가능하더라도, TEMI OS의 skill/app selection 연동은 기대와 다를 수 있습니다.

참고:

- https://github-wiki-see.page/m/robotemi/sdk/wiki

### 5. 화면 방향과 해상도 고정 검증이 없음

파일: `app/src/main/res/layout/activity_main.xml`

레이아웃은 큰 `sp`, 고정 `dp`, 전체화면 `FrameLayout` 위주입니다. TEMI 태블릿 가로 화면에서는 대체로 보일 가능성이 있지만, `screenOrientation="landscape"`가 Manifest에 고정되어 있지 않습니다. 기기 회전/설정에 따라 UI가 깨질 수 있습니다.

권장:

- `MainActivity`에 landscape 고정
- TEMI 해상도에서 실제 스크린샷 확인
- 버튼과 WebView 오버레이가 잘리는지 확인

## 앱 로직상 문제

### 1. `readPaidStatus()`가 구현되어 있지만 사용되지 않음

파일: `app/src/main/java/com/example/wimc/MainActivity.java:322-326`

이미 결제된 차량인지 확인하는 함수가 있지만 실제 검색 흐름에서는 호출하지 않습니다. 현재 흐름은 차량을 찾으면 바로 이동하고, 도착 후 광고/퀴즈/결제로 갑니다.

영향:

- 이미 결제된 차량도 다시 결제로 유도될 수 있음
- 발표 문서의 “is_paid 확인” 흐름과 실제 코드가 다름

### 2. `showPaymentOptionScreen()`이 사실상 미사용

파일: `app/src/main/java/com/example/wimc/MainActivity.java:361-377`

결제 옵션 UI는 XML과 코드에 남아 있지만, 실제 `processVehicleSelection()`에서는 호출하지 않습니다. 현재 최종 흐름은 “결제 없이 이동 → 도착 후 강제 광고 → 퀴즈 → 카카오페이”입니다.

발표 시나리오가 이 흐름이라면 괜찮지만, “지금 결제/광고 보고 결제” 선택지가 있다고 설명하면 실제 코드와 불일치합니다.

### 3. `speak()`가 robot null/ready를 방어하지 않음

파일: `app/src/main/java/com/example/wimc/MainActivity.java:688-690`

```java
robot.speak(TtsRequest.create(text, false));
```

대부분의 정상 앱 생명주기에서는 `robot = Robot.getInstance()` 이후 호출되지만, Firebase 콜백/초기화 실패/비 TEMI 환경 테스트에서는 예외 가능성이 있습니다. 최소한 `robot != null && isRobotReady` 또는 try-catch 방어가 있으면 안정성이 올라갑니다.

## 긍정적으로 볼 부분

- `minSdk 23`이라 TEMI V2 Android 6.0.1 계열까지 고려한 설정입니다.
- `com.robotemi:sdk:1.131.1`을 직접 사용하고 있어 TEMI SDK 방향은 맞습니다.
- `OnRobotReadyListener`, `OnGoToLocationStatusChangedListener`, `Robot.TtsListener` 등록/해제 위치가 `onStart()`/`onStop()`으로 적절합니다.
- `zone.trim().toLowerCase()`로 waypoint 대소문자 문제를 의식한 흔적이 있습니다.
- Firebase last4 검색, 중복 차량 선택, Glide 이미지 로딩, 광고/퀴즈/자동 복귀까지 데모 플로우는 한 파일 안에 완성되어 있습니다.

TEMI SDK 최신 정보:

- GitHub README 기준 최신 의존성 예시는 `com.robotemi:sdk:1.137.1`
- 현재 프로젝트는 `1.131.1`
- GitHub: https://github.com/robotemi/sdk

## 우선 수정 순서

1. TEMI에 debug APK 설치
2. TEMI Location 이름 `a`, `b`, `c`, `home base` 확인
3. Firebase에 발표용 차량 데이터 1개 고정 세팅
4. 앱 실행 후 `Temi 준비 완료`가 뜬 다음 차량번호 검색
5. 이동 완료 후 광고 영상, 퀴즈, 카카오페이 WebView가 순서대로 뜨는지 리허설
6. 카카오페이 단계가 불안하면 발표용 백업 플랜으로 결제 성공 화면 전환을 수동 처리할 방법 준비

## 최종 예측

현재 상태는 실제 TEMI 설치 전 단계는 통과했습니다. `assembleDebug`가 성공하고 debug APK가 생성됩니다.

TEMI SDK 호출 자체는 큰 방향이 맞아서 로봇 이동 데모는 가능성이 있습니다. 단, 성공 조건은 명확합니다.

- TEMI에 목적지 위치가 정확히 저장되어 있어야 함
- Firebase `parking_lot` 데이터의 `last4`, `zone`, `entry_time`, `image_url` 타입이 맞아야 함
- 카카오페이 테스트 API URL/키/콜백 흐름이 실제로 맞아야 함
- 발표장 Wi-Fi가 안정적이어야 함

이 조건을 충족하면 “차량 검색 → TEMI 이동 → 도착 → 광고 → 퀴즈 → 결제 화면 → 복귀” 발표 시연은 충분히 가능합니다. 운영 앱 수준의 결제 검증과 예외 처리는 이번 데모 범위에서는 후순위입니다.

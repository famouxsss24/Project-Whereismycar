# WIMC 코드 점검 리포트

점검 기준 경로: `C:\wimc\wimc`  
점검일: 2026-05-20

## 결론

현재 프로젝트는 그대로는 빌드가 실패합니다.

가장 먼저 고쳐야 할 문제는 `MainActivity.java`에서 Temi SDK의 `BatteryData.getLevel()`을 호출하는 부분입니다. 현재 사용 중인 Temi SDK `1.131.1`의 `BatteryData`에는 `getLevel()` 메서드가 없고, `getBatteryPercentage()`가 존재합니다.

## 확인한 빌드 결과

처음 빌드 실행 시 로컬 환경에 `JAVA_HOME`이 설정되어 있지 않아 바로 실패했습니다.

```text
ERROR: JAVA_HOME is not set and no 'java' command could be found in your PATH.
```

Android Studio 내장 JBR을 지정해 다시 실행한 결과 Java 컴파일 단계까지 진행됐고, 아래 오류로 실패했습니다.

```text
C:\wimc\wimc\app\src\main\java\com\example\wimc\MainActivity.java:292: error: cannot find symbol
            return bd != null ? bd.getLevel() : -1;
                                  ^
  symbol:   method getLevel()
  location: variable bd of type BatteryData
```

## 치명적 이슈

### 1. Temi 배터리 API 호출 오류

파일: `app/src/main/java/com/example/wimc/MainActivity.java`

현재 코드:

```java
return bd != null ? bd.getLevel() : -1;
```

SDK 클래스 확인 결과 `BatteryData`에는 아래 메서드가 있습니다.

```text
getBatteryPercentage()
isCharging()
```

수정 권장:

```java
return bd != null ? bd.getBatteryPercentage() : -1;
```

## 환경 이슈

### 1. JAVA_HOME 미설정

터미널에서 Gradle을 실행하려면 Java 경로가 필요합니다. 현재 PC에는 Android Studio 내장 JBR이 있습니다.

사용 가능한 경로:

```text
C:\Program Files\Android\Android Studio\jbr
```

PowerShell에서 임시로 빌드할 때는 아래처럼 실행할 수 있습니다.

```powershell
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
$env:PATH="$env:JAVA_HOME\bin;$env:PATH"
.\gradlew.bat :app:assembleDebug --stacktrace
```

### 2. SDK XML 버전 경고

빌드 중 아래 경고가 나왔습니다.

```text
This version only understands SDK XML versions up to 3 but an SDK XML file of version 4 was encountered.
```

이는 Android Studio와 command-line tools 버전 차이에서 흔히 발생합니다. 현재 빌드를 막는 직접 원인은 아니지만, Android SDK Command-line Tools 업데이트 또는 정리가 필요할 수 있습니다.

## 보안 및 설정 이슈

### 1. Firebase 설정 파일이 Git에 포함됨

파일: `app/google-services.json`

이 파일이 Git에 추적되고 있습니다.

```text
app/google-services.json
```

Android Firebase 설정 파일 자체가 서버 비밀키는 아니지만, Realtime Database나 Storage 보안 규칙이 느슨하면 데이터 노출 위험이 있습니다.

확인 필요:

- Firebase Realtime Database rules
- Firebase Storage rules
- 테스트용 공개 권한이 남아 있는지 여부

### 2. Activity exported 설정 확인 필요

파일: `app/src/main/AndroidManifest.xml`

현재 `MainActivity`는 외부에서 실행 가능한 상태입니다.

```xml
<activity
    android:name=".MainActivity"
    android:exported="true">
```

런처 Activity라 `exported="true"` 자체는 필요할 수 있습니다. 다만 같은 Activity에 Temi wakeup action도 같이 들어가 있으므로, 외부 앱에서 의도치 않게 실행 가능한 구조인지 확인이 필요합니다.

## Gradle 설정 이슈

### 1. Temi SDK 정의 중복

파일: `app/build.gradle`

실제로 사용 중인 의존성:

```gradle
implementation 'com.robotemi:sdk:1.131.1'
```

파일: `gradle/libs.versions.toml`

사용되지 않는 것으로 보이는 정의:

```toml
temi = "0.10.76"
temi-sdk = { group = "com.github.robotemi", name = "temi-sdk-android", version = "0.10.76" }
```

실제 사용하는 SDK 하나로 정리하는 것이 좋습니다.

## 정상으로 확인한 부분

- `activity_main.xml`의 한글 문자열은 UTF-8 기준 정상입니다.
- `MainActivity.java`의 한글 문자열도 UTF-8 기준 정상입니다.
- 처음 깨져 보였던 것은 PowerShell 출력 인코딩 문제로 보입니다.
- Git 작업트리는 실질적인 변경 파일이 없는 상태였습니다.

## 테스트 상태

현재 테스트는 Android Studio 기본 샘플 수준입니다.

- `ExampleUnitTest`
- `ExampleInstrumentedTest`

앱의 핵심 기능인 차량번호 검색, Firebase 결과 처리, 중복 차량 선택, Temi 이동 로직은 테스트로 검증되어 있지 않습니다.

## 우선 수정 순서

1. `MainActivity.java`의 `bd.getLevel()`을 `bd.getBatteryPercentage()`로 변경
2. `JAVA_HOME` 설정 후 `.\gradlew.bat :app:assembleDebug` 재실행
3. Firebase Database/Storage rules 확인
4. Temi SDK 의존성 중복 정리
5. 차량 검색과 Firebase 결과 처리 로직 테스트 추가


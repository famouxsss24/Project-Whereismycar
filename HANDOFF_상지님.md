# 📦 WIMC(내차로) 인수인계 — 상지님께

작성: 유명현 / 갱신일: 2026-06-09
대상 저장소: `Project-Whereismycar`
- `Control` 브랜치 = Android(테미) 앱
- `Vision` 브랜치 = Python 번호판 인식(카메라) 시스템

---

## 1. 한눈에 보는 전체 흐름

```
[주차장 카메라]  cam2 → A·B구역 / cam3 → C·D구역
      │ YOLO로 번호판 검출 → PaddleOCR로 글자 인식
      │ 같은 구역에 N초(기본 5초) 머무르면 "주차 확정"
      ▼
[Firebase Realtime DB]  parking_lot/{번호판} = { zone, last4, image_url }
      ▲                         │
      │ 이동 직전 zone 재조회     │ 번호판 last4로 차량 조회
      ▼                         ▼
[테미 앱]  뒷 4자리 입력 → 차량 검색 → 해당 구역으로 이동
      → 도착 → 광고 영상 → 퀴즈(정답 시 +100p) → 카카오페이 결제 → 자동 복귀
```

핵심: **카메라(Vision)가 구역을 실시간으로 써주고, 앱(Control)이 그 구역을 읽어 테미를 보낸다.**
두 시스템은 Firebase로만 연결되어 서로 독립 실행된다.

---

## 2. 이번에 고친 4가지 (2026-06-09)

### ① Python 모델 딜레이/버벅임 + 초기화 실패  →  `Vision` 브랜치
- **원인 1 (초기화 실패):** PaddleOCR 모델이 부분 다운로드(서버 모델 `PP-OCRv5_server_rec` 누락)되어 init 실패.
  → 캐시 폴더 `%USERPROFILE%\.paddlex\official_models` 삭제 후 재실행하면 깨끗이 재다운로드됨(이미 삭제해 둠).
- **원인 2 (느림):** 기본값이 무거운 **server** 검출 모델. CPU에서 매우 느림.
  → `plate_ocr.py`에서 **경량 mobile 검출 모델(`PP-OCRv5_mobile_det`)** 우선 사용하도록 변경. 실패 시 자동 폴백.
- 효과: 다운로드 용량↓, 프레임당 추론 속도↑, 부분 다운로드 실패 위험↓.

### ② 카카오페이 API 오류  →  `Control` 브랜치
- 오류 본문이 화면에 안 보여서 디버깅이 어려웠음 → `getErrorStream()`으로 **실제 오류 메시지를 화면(navLayout)에 표시**하고 3초 후 메인 복귀(흰 화면 방지). *(에러 표면화는 직전 작업에서 반영됨)*
- 추가: `total_amount = 0`이면 카카오페이가 거절 → **최소 결제 금액 100원 보장**(`Math.max(amount, 100)`). 짧은 주차로 요금이 0원일 때 결제 실패 방지.
- 참고: 현재 키는 **테스트(sandbox)** 값. `KAKAO_CID = TC0ONETIME`, `KAKAO_SECRET_KEY = DEV...`.
  결제 성공 URL(`wimc.local/payment/success`)을 WebView가 가로채 완료 처리하는 **데모용** 흐름(실 승인 `/approve` 호출은 생략).

### ③ 실시간 구역 동기화 후 이동  →  `Control` 브랜치
- 기존: 차량 검색 시점의 zone으로 이동(검색~이동 사이 카메라가 구역을 바꿔도 반영 안 됨).
- 변경: **이동 직전 Firebase에서 `parking_lot/{번호판}/zone`을 한 번 더 읽어** 최신 구역으로 이동(`refreshZoneAndGo`).
  조회 실패 시 기존 구역으로 폴백. 화면 표시도 최신 구역으로 동기화.

### ④ Android Studio 빌드 오류 계속 발생  →  `Control` 브랜치
- 증상: `Unable to delete directory 'app\build' ... a process has files open` (clean/rebuild 실패).
- **원인:** Windows에서 Gradle **파일시스템 감시(VFS watch)** 가 `build` 폴더 핸들을 잡고 안 놓음.
- **해결:** `gradle.properties`에 `org.gradle.vfs.watch=false` 추가(+`org.gradle.caching=true`).
  → 이 상태로 `clean assembleDebug` **BUILD SUCCESSFUL** 확인 완료.
- 그래도 잠기면: Android Studio 완전 종료 → `app/build` 삭제 → 재실행. 또는 실행 중인 앱 종료 후 재빌드.

---

## 3. 실행 방법

### Vision (노트북 — 항상 켜둠)
```powershell
cd C:\wimc\vision
py -3.12 main.py
```
- Python **3.12** 필요(3.11은 PaddleOCR 미지원). `py -3.12 -m pip install -r requirements.txt`
- 프리뷰 창에서 **마우스 드래그**로 구역 박스 설정 → cam2=A·B, cam3=C·D. `settings.json`에 자동 저장.
- `settings.json` 주요 값: `cameras:[2,3]`, `zone_offsets:{"2":0,"3":2}`, `dwell_seconds:5.0`.
- 시크릿 파일(깃 제외): `secrets/firebase-service-account.json`, `secrets/azure-blob.json`.

### Control (테미 앱)
1. 테미 설정 → About에서 IP 확인, Developer Options에서 ADB 포트 ON
2. `adb connect <테미IP>:5555`
3. Android Studio에서 ▶ Run (재배포는 ⚡ Apply Changes가 빠름)

### 테스트용 더미 데이터(카메라 없이 앱만 볼 때)
```powershell
cd C:\wimc\vision
py -3.12 seed_db.py   # 184다4056→A, 12아2971→B, 136가1362→C, 476나6798→D
```
> ⚠️ `main.py` 실행 중이면 카메라가 인식한 실제 구역으로 덮어쓴다. seed는 테스트 전용.

---

## 4. Firebase 구조 / 규칙
```
parking_lot/{번호판}/  zone, last4, image_url,
                       entry_time, is_paid, original_fee, paid_amount,
                       discount_applied, quiz_correct, paid_at
users/{번호판}/total_points   # 퀴즈 정답 시 +100
```
- 데모용 규칙(읽기/쓰기 공개): `{"rules":{".read":true,".write":true}}` — 기존 만료형 규칙(`now < …`) 때문에 Permission denied가 났던 이력 있음.

---

## 5. 알아둘 점 / 남은 리스크
- **테미 waypoint 이름**: 앱이 `goTo(zone.toLowerCase())`로 보냄 → 테미에 위치가 **소문자 `a`,`b`,`c`,`d`** 로 저장돼 있어야 이동함(대문자면 실패).
- **빌드 환경**: AGP `9.1.1` + `compileSdk = release(36){…}`(프리뷰 문법) + Gradle 9.3.1. 최신 Android Studio가 아니면 빌드가 막힐 수 있음. 현재 환경에서는 정상 빌드.
- **카카오페이**: 운영 전환 시 실제 CID/시크릿 발급 + 승인(`/approve`) 단계 구현 필요.
- 시크릿(서비스계정/Azure 키)은 `.gitignore`로 제외됨 — 인수 시 별도 전달 필요.

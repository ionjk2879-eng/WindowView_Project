# CLAUDE.md — WindowView 프로젝트

## 언어 규칙

**모든 답변·설명·안내·코드 주석 제안은 반드시 한국어로 작성한다.** 영어로 설명하거나 안내하지 않는다.

---

## 프로젝트 개요

**창밖 뷰 계산기** — GPS와 나침반으로 현재 위치에서 창밖에 보이는 건물·지형·햇빛을 3D로 시각화하는 Android 앱.

- 패키지: `com.juhyeon.windowview`
- 최소 SDK: API 24 / 타깃 SDK: 36
- 언어: Kotlin + Jetpack Compose (UI 껍데기) + WebView (실제 3D 화면)

---

## 구조

```
app/src/main/
  java/.../MainActivity.kt       GPS·나침반·공유 → WebView 연결
  assets/index.html              3D 화면 + 가림·햇빛 계산 (Three.js)
  assets/three.min.js            Three.js r128
  assets/data/regions.json       지역 목록
  assets/data/eunhaeng.json      은행동 건물·도로·지형 데이터
  assets/data/dunsan.json        둔산동 건물·도로·지형 데이터

tools/
  gis_to_window.py               국토부 GIS → 지역 JSON 변환
  dem_horizon.py                 Copernicus DEM → 지형 능선 추가
  verify_sun.py                  천문연구원 API로 해 계산 검증
```

---

## 앱 ↔ 화면 인터페이스

| 방향 | 호출 |
|------|------|
| 앱 → 화면 | `window.onNativeLocation(lat, lon, 오차m)` |
| 앱 → 화면 | `window.onNativeHeading(도)` |
| 화면 → 앱 | `Android.requestLocation()` |
| 화면 → 앱 | `Android.startCompass()` / `Android.stopCompass()` |
| 화면 → 앱 | `Android.shareImage(base64, 글)` |

---

## 핵심 제약

- **INTERNET 권한 없음** — 위치가 앱 밖으로 나가지 않도록 의도된 설계. 추가하지 않는다.
- **`index.html`이 화면 로직의 중심** — Kotlin은 센서·공유 브리지 역할만 한다. 3D·계산 로직은 HTML/JS에 있다.
- **WebViewAssetLoader** 사용 — `assets://` 대신 `https://appassets.androidplatform.net/` 경로로 로드.

---

## 데이터 출처

- 건물: 국토교통부 GIS건물통합정보 (공공누리 제1유형)
- 지형: Copernicus DEM GLO-30 (© DLR e.V. / Airbus Defence and Space GmbH, EU·ESA 제공)

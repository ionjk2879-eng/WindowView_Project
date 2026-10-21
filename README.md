# 창밖 뷰 계산기: 안드로이드 스튜디오 시작 코드

## 0. 새 프로젝트 만들기
- Android Studio → New Project → **Empty Activity**
- Name: `WindowView` / Package name: `com.juhyeon.windowview`
- Minimum SDK: **API 24** / Build configuration language: Kotlin DSL

## 1. 파일 넣기 (이 zip 기준 → 내 프로젝트 같은 위치에 덮어쓰기)
| 이 zip | 내 프로젝트 |
| --- | --- |
| `app/src/main/assets/` 폴더 통째로 | `app/src/main/assets/` (없으면 만들기) |
| `app/src/main/java/com/juhyeon/windowview/MainActivity.kt` | 같은 위치 (기존 파일 덮어쓰기) |
| `app/src/main/AndroidManifest.xml` | 같은 위치 (덮어쓰기) |
| `app/src/main/res/xml/file_paths.xml` | 같은 위치 (새로 추가) |

Compose 템플릿이 만든 `ui/theme` 폴더는 그대로 둬도 돼요.

## 2. 라이브러리 한 줄 추가
`app/build.gradle.kts` 의 `dependencies { … }` 안에:
```kotlin
implementation("androidx.webkit:webkit:1.12.1")
```
그다음 오른쪽 위 **Sync Now**.

## 3. 실행
- 에뮬레이터: ▶ Run. 위치는 에뮬레이터 옆 `⋯ → Location` 에서
  위도 `36.32800`, 경도 `127.42790` (대전 은행동)을 넣고 **Set Location** 후 앱의 **내 위치** 버튼.
- 나침반은 에뮬레이터에서 거의 안 움직여요. 실제 폰(USB 디버깅)에서 확인하세요.
- 화면 코드 디버깅: PC 크롬 주소창에 `chrome://inspect` → 앱의 WebView **inspect**.

## 구조
```
assets/index.html      3D 화면 + 가림·햇빛 계산 (시제품 코드)
assets/three.min.js    3D 라이브러리 (three.js r128, MIT)
assets/data/regions.json 앱에 든 지역 목록 (은행동, 둔산동)
assets/data/eunhaeng.json, dunsan.json  지역별 건물·도로·목표물 (반경 320m)
MainActivity.kt        GPS · 나침반 · 공유를 화면에 연결
```
- 앱 → 화면: `window.onNativeLocation(lat, lon, 오차m)`, `window.onNativeHeading(도)`
- 화면 → 앱: `Android.requestLocation()`, `Android.startCompass()`, `Android.stopCompass()`, `Android.shareImage(base64, 글)`

## 건물 데이터 다시 만들기 (tools/gis_to_window.py)
`data/window.json` 은 **국토교통부 GIS건물통합정보(AL_D010_30_20261009, 대전)** 로 만든 거예요
(공공누리 제1유형: 출처 표시하면 저장·가공·상업적 이용 가능).
```
pip install pyshp pyproj
python tools/gis_to_window.py tools/AL_D010_30_20261009 tools/export.geojson app/src/main/assets/data/eunhaeng.json eunhaeng
python tools/gis_to_window.py tools/AL_D010_30_20261009 - app/src/main/assets/data/dunsan.json dunsan
```
- 다른 지역: 스크립트의 `REGIONS`에 한 칸 추가(중심 위도·경도, 반경, 목표물) → 만든 파일을 `data/`에 넣고 `regions.json`에 한 줄 추가
- 내 위치가 다른 지역 안이면 앱이 그 지역 데이터로 자동 전환해요
- 쓰는 칸: A9 용도, A16 높이(m), A24 건물명, A26 지상층수 / 좌표계 EPSG:5186
- 높이가 없으면 `층수 × 이 지역 층고`(높이·층수가 둘 다 있는 건물의 중앙값, 은행동 3.75m), 둘 다 없으면 1층

## 지형(산) 넣기 (tools/dem_horizon.py)
지형은 **Copernicus DEM GLO-30**(30m, 무료)을 써요. 대전 범위 파일:
https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N36_00_E127_00_DEM/Copernicus_DSM_COG_10_N36_00_E127_00_DEM.tif
```
pip install rasterio numpy
python tools/dem_horizon.py Copernicus_DSM_COG_10_N36_00_E127_00_DEM.tif app/src/main/assets/data/dunsan.json
```
- gis_to_window.py로 만든 지역 파일에 `terrain`(방위 360° × 거리 64칸, 30km까지 산 능선)을 덧붙여요
- 앱은 이걸로 ① 랜드마크가 산에 가려지는지 ② 산 위로 해가 실제 뜨고 지는 시각 ③ 해 드는 시간을 계산하고,
  3D 화면 배경에 산 능선을 그려요
- DSM이라 도심에선 건물 높이가 섞여 있어서, 반경 안은 쓰지 않고 땅높이는 반경 안 낮은 값(10%)으로 잡아요
- 출처 표시(앱 설명·공유 카드에 넣음): © DLR e.V. 2010-2014, © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the EU and ESA
- 국토지리정보원 공개DEM은 도엽 제공이 막히고 국외 반출 제한(공간정보관리법)이 있어서 대신 이걸 썼어요

## 해 계산 검증 (tools/verify_sun.py)
```
python tools/verify_sun.py 공공데이터포털_서비스키
```
천문연구원 출몰시각(지평선 기준)과 앱 계산을 날짜별로 비교해요. 1분 이내면 통과.

## 주의
- INTERNET 권한을 넣지 않았어요. 위치가 폰 밖으로 나갈 길 자체가 없어서 심사 때 설명하기 쉬워요.

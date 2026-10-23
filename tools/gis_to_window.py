"""
국토교통부 GIS건물통합정보(SHP) → 앱용 data/window.json

사용법 (PC에서):
    pip install pyshp pyproj
    python gis_to_window.py AL_D010_30_20261009 export.geojson window.json eunhaeng
    python gis_to_window.py AL_D010_30_20261009 - window.json dunsan

- 첫 번째 인자: SHP 파일 이름(확장자 빼고). 같은 폴더에 .shp .shx .dbf .prj 가 있어야 해요
- 두 번째 인자: 도로용 오픈스트리트맵 GeoJSON (overpass-turbo에서 받은 export.geojson), 없으면 -
- 세 번째 인자: 만들 파일 (앱의 app/src/main/assets/data/window.json 에 넣기)
- 네 번째 인자: 지역 이름 (아래 REGIONS 에서 고르기, 기본 eunhaeng)

GIS건물통합정보 칸 (A0~A28 중 쓰는 것):
    A9  건축물용도명   A16 높이(m)   A24 건물명   A26 지상층수
좌표계: EPSG:5186 (중부원점, .prj 파일에 적혀 있음)

출력 buildings 한 칸 = [지상층수, [x0,z0,x1,z1,...], 높이m, 추정여부(0/1)]
  x = 중심에서 동쪽(m), z = 중심에서 남쪽(m)
"""
import json, math, statistics, sys

import shapefile  # pyshp
from pyproj import Transformer

# ── 지역 설정: 새 지역은 REGIONS 에 한 칸 추가 ──
# 목표물 y = 보일지 확인할 높이(m). 건물 목표물은 GIS 데이터의 그 건물 높이를 넣으면 돼요
# (반경 R 안의 건물을 목표물로 잡으면 그 건물 자기 벽에 가려진다고 나올 수 있어서 R 밖 건물로)
REGIONS = {
    "eunhaeng": {  # 대전 중구 은행동
        "lat": 36.32772, "lon": 127.42760, "R": 320.0, "label": "대전 은행동",
        "targets": [],
    },
    "dunsan": {  # 대전 서구 둔산동 (대덕대로 179 일대)
        "lat": 36.34940, "lon": 127.37682, "R": 320.0, "label": "대전 둔산동",
        "targets": [],
    },
}
REGION = REGIONS[sys.argv[4] if len(sys.argv) > 4 else "eunhaeng"]
CLAT, CLON, R = REGION["lat"], REGION["lon"], REGION["R"]
SRC_EPSG = 5186

F_USE, F_HEIGHT, F_NAME, F_FLOORS = 9, 16, 24, 26
DEFAULT_FLOOR_H = 3.2   # 층고 추정값을 못 구할 때
UNKNOWN_FLOORS = 1      # 높이·층수 둘 다 없는 건물은 1층으로 둠

shp_base, osm_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

to_wgs = Transformer.from_crs(SRC_EPSG, 4326, always_xy=True)
to_src = Transformer.from_crs(4326, SRC_EPSG, always_xy=True)
CX, CY = to_src.transform(CLON, CLAT)
KX = math.cos(math.radians(CLAT)) * 111320.0
KZ = 110540.0


def local(lon, lat):
    """위도·경도 → 앱 좌표 (x 동쪽, z 남쪽). 이전 데이터와 같은 방식"""
    return (lon - CLON) * KX, -(lat - CLAT) * KZ


def rings(shape):
    """SHP 폴리곤을 고리(ring) 목록으로. 바깥 고리만 남김 (구멍 제외)"""
    pts, parts = shape.points, list(shape.parts) + [len(shape.points)]
    out = []
    for a, b in zip(parts[:-1], parts[1:]):
        ring = pts[a:b]
        if len(ring) < 4:
            continue
        area2 = sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1))
        if area2 < 0:  # SHP에서 바깥 고리는 시계 방향(면적 음수)
            out.append(ring)
    return out


reader = shapefile.Reader(shp_base, encoding="cp949")
raw = []
for sr in reader.iterShapeRecords():
    bx0, by0, bx1, by1 = sr.shape.bbox
    if (((bx0 + bx1) / 2 - CX) ** 2 + ((by0 + by1) / 2 - CY) ** 2) > R * R:
        continue
    rec = sr.record
    h = float(rec[F_HEIGHT] or 0)
    fl = int(rec[F_FLOORS] or 0)
    for ring in rings(sr.shape):
        raw.append((h, fl, ring, rec[F_NAME], rec[F_USE]))

# 이 지역 층고 = 높이·층수가 둘 다 있는 건물의 (높이 ÷ 층수) 중앙값
ratios = [h / fl for h, fl, *_ in raw if h > 0 and fl > 0 and 2.0 <= h / fl <= 8.0]
floor_h = statistics.median(ratios) if ratios else DEFAULT_FLOOR_H

buildings, named, stat = [], [], {"height": 0, "floors_only": 0, "none": 0}
for h, fl, ring, name, use in raw:
    est = 0
    if h > 0 and fl > 0:
        stat["height"] += 1
    elif h > 0:  # 높이만 있음 → 층수 추정
        fl = max(1, round(h / floor_h)); est = 1; stat["height"] += 1
    elif fl > 0:  # 층수만 있음 → 높이 추정
        h = fl * floor_h; est = 1; stat["floors_only"] += 1
    else:  # 둘 다 없음 → 1층으로
        fl = UNKNOWN_FLOORS; h = fl * floor_h; est = 1; stat["none"] += 1
    xz = []
    for x5186, y5186 in ring:
        lon, lat = to_wgs.transform(x5186, y5186)
        xz.append(local(lon, lat))
    # 앱 좌표(z가 남쪽)에서 반시계 방향으로 통일 → 바깥 법선 = (dz, -dx)
    area2 = sum(xz[i][0] * xz[i + 1][1] - xz[i + 1][0] * xz[i][1] for i in range(len(xz) - 1))
    if area2 < 0:
        xz = xz[::-1]
    flat = [round(v, 2) for p in xz for v in p]
    buildings.append([fl, flat, round(h, 1), est])
    name_str = (name or "").strip()
    if name_str:
        n = len(flat) // 2
        named.append([round(sum(flat[i] for i in range(0, len(flat), 2)) / n, 1),
                      round(sum(flat[i] for i in range(1, len(flat), 2)) / n, 1),
                      name_str])

# ── 도로 (오픈스트리트맵, 화면 표시용) ──
CAR = {"primary": 14, "primary_link": 8, "secondary": 12, "secondary_link": 8, "tertiary": 10,
       "unclassified": 7, "residential": 6, "service": 4}
FOOT = {"pedestrian": 5, "footway": 2.5, "path": 2, "steps": 2.5}


def clip(a, b, r):
    dx, dz = b[0] - a[0], b[1] - a[1]
    A = dx * dx + dz * dz
    if A < 1e-9:
        return None
    B_ = 2 * (a[0] * dx + a[1] * dz)
    C = a[0] ** 2 + a[1] ** 2 - r * r
    disc = B_ * B_ - 4 * A * C
    if disc <= 0:
        return None
    s = math.sqrt(disc)
    t0, t1 = max(0, (-B_ - s) / (2 * A)), min(1, (-B_ + s) / (2 * A))
    if t0 >= t1:
        return None
    return (a[0] + dx * t0, a[1] + dz * t0), (a[0] + dx * t1, a[1] + dz * t1)


roads = []
for f in ([] if osm_path == "-" else json.load(open(osm_path, encoding="utf-8"))["features"]):
    p, g = f["properties"], f["geometry"]
    hw = p.get("highway")
    if not hw or g["type"] != "LineString" or p.get("tunnel") == "yes" or str(p.get("layer", "0")).startswith("-"):
        continue
    if p.get("footway") == "crossing":
        continue
    w = CAR.get(hw) or FOOT.get(hw)
    if not w:
        continue
    try:
        lanes = int(p.get("lanes", 0) or 0)
        if lanes and hw in CAR:
            w = lanes * 3.0 + 1
    except ValueError:
        pass
    pts = [local(*c) for c in g["coordinates"]]
    for k in range(len(pts) - 1):
        c = clip(pts[k], pts[k + 1], R + 30)
        if c:
            roads.append([round(w, 1), 1 if hw in FOOT else 0,
                          round(c[0][0], 1), round(c[0][1], 1), round(c[1][0], 1), round(c[1][1], 1)])


# ── 목표물 (직접 정리) ──
def tgt(name, lon, lat, y, kind, approx=False):
    x, z = local(lon, lat)
    return {"name": name, "x": round(x, 1), "y": y, "z": round(z, 1), "kind": kind, "approx": approx}


targets = [tgt(n, lon, lat, y, k, a) for n, lon, lat, y, k, a in REGION["targets"]]

out = {
    "R": R, "lat": CLAT, "lon": CLON, "label": REGION["label"], "floorH": round(floor_h, 2),
    "source": "국토교통부 GIS건물통합정보 (공공누리 제1유형)",
    "buildings": buildings, "names": named, "roads": roads, "targets": targets,
}
json.dump(out, open(out_path, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
print(f"건물 {len(buildings)}채 (실제 높이 {stat['height']}, 층수로 추정 {stat['floors_only']}, "
      f"정보 없음→1층 {stat['none']}), 도로 {len(roads)}조각, 이 지역 층고 {floor_h:.2f}m")

"""
국토교통부 GIS건물통합정보(SHP) → 500m 격자 타일 JSON (data/tiles/ 폴더)

사용법:
    pip install pyshp pyproj
    python gis_to_tiles.py AL_D010_30_20261009 export.geojson app/src/main/assets/data/tiles
    python gis_to_tiles.py AL_D010_30_20261009 - app/src/main/assets/data/tiles

타일 ID = floor(lat / 0.005) _ floor(lon / 0.005)  (~500m 격자)
각 파일: { lat, lon, floorH, buildings, roads, names }
  buildings: [[fl, [x0,z0,...], 높이m, 추정], ...]
  roads: [[너비, 보행자여부, x1,z1,x2,z2], ...]
  names: [[cx, cz, "건물명"], ...]  (건물명 있는 것만)
좌표는 타일 중심 기준 상대 좌표 (x=동쪽 m, z=남쪽 m)

앱 JS: loadTiles(lat, lon) 이 주변 3×3 타일을 읽어 자동 병합
"""
import json, math, os, statistics, sys

import shapefile
from pyproj import Transformer

TILE_DEG = 0.005        # ~500m
F_HEIGHT, F_NAME, F_FLOORS = 16, 24, 26
DEFAULT_FLOOR_H = 3.2
UNKNOWN_FLOORS = 1
SRC_EPSG = 5186

shp_base, osm_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out_dir, exist_ok=True)

to_wgs = Transformer.from_crs(SRC_EPSG, 4326, always_xy=True)


def tile_key(lat, lon):
    return math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG)


def tile_center(tk):
    return (tk[0] + 0.5) * TILE_DEG, (tk[1] + 0.5) * TILE_DEG


def to_local(clat, clon, lat, lon):
    kx = math.cos(math.radians(clat)) * 111320.0
    return (lon - clon) * kx, -(lat - clat) * 110540.0


def rings(shape):
    pts, parts = shape.points, list(shape.parts) + [len(shape.points)]
    out = []
    for a, b in zip(parts[:-1], parts[1:]):
        ring = pts[a:b]
        if len(ring) < 4:
            continue
        area2 = sum(ring[i][0] * ring[i+1][1] - ring[i+1][0] * ring[i][1] for i in range(len(ring) - 1))
        if area2 < 0:   # SHP 바깥 고리 = 시계방향 = 면적 음수
            out.append(ring)
    return out


# ── 건물 수집 ──
print("건물 읽는 중 …", flush=True)
tiles_raw = {}   # tile_key → [(h, fl, wgs_ring, name_str)]
reader = shapefile.Reader(shp_base, encoding="cp949")
total = 0
for sr in reader.iterShapeRecords():
    rec = sr.record
    h = float(rec[F_HEIGHT] or 0)
    fl = int(rec[F_FLOORS] or 0)
    name_str = (rec[F_NAME] or "").strip()
    for ring in rings(sr.shape):
        wgs = [to_wgs.transform(x, y) for x, y in ring]   # [(lon, lat), ...]
        clat_c = sum(p[1] for p in wgs) / len(wgs)
        clon_c = sum(p[0] for p in wgs) / len(wgs)
        tk = tile_key(clat_c, clon_c)
        tiles_raw.setdefault(tk, []).append((h, fl, wgs, name_str))
    total += 1
    if total % 10000 == 0:
        print(f"  {total}채 …", flush=True)
print(f"총 {total}채 → {len(tiles_raw)}개 타일")

# ── 타일별 JSON 생성 ──
for tk, raw in tiles_raw.items():
    clat, clon = tile_center(tk)

    ratios = [h / fl for h, fl, *_ in raw if h > 0 and fl > 0 and 2.0 <= h / fl <= 8.0]
    floor_h = statistics.median(ratios) if ratios else DEFAULT_FLOOR_H

    buildings, named = [], []
    for h, fl, wgs, name_str in raw:
        est = 0
        if h > 0 and fl > 0:
            pass
        elif h > 0:
            fl = max(1, round(h / floor_h)); est = 1
        elif fl > 0:
            h = fl * floor_h; est = 1
        else:
            fl = UNKNOWN_FLOORS; h = fl * floor_h; est = 1

        xz = [to_local(clat, clon, lat, lon) for lon, lat in wgs]
        area2 = sum(xz[i][0] * xz[i+1][1] - xz[i+1][0] * xz[i][1] for i in range(len(xz) - 1))
        if area2 < 0:
            xz = xz[::-1]

        flat = [round(v, 2) for p in xz for v in p]
        buildings.append([fl, flat, round(h, 1), est])
        if name_str:
            n = len(flat) // 2
            named.append([round(sum(flat[i] for i in range(0, len(flat), 2)) / n, 1),
                          round(sum(flat[i] for i in range(1, len(flat), 2)) / n, 1),
                          name_str])

    out = {"lat": clat, "lon": clon, "floorH": round(floor_h, 2),
           "buildings": buildings, "roads": [], "names": named}
    tid = f"{tk[0]}_{tk[1]}"
    json.dump(out, open(os.path.join(out_dir, f"{tid}.json"), "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)

# ── 도로 추가 (OSM GeoJSON, 없으면 생략) ──
if osm_path != "-":
    CAR  = {"primary": 14, "primary_link": 8, "secondary": 12, "secondary_link": 8,
            "tertiary": 10, "unclassified": 7, "residential": 6, "service": 4}
    FOOT = {"pedestrian": 5, "footway": 2.5, "path": 2, "steps": 2.5}
    roads_by_tile = {}
    for f in json.load(open(osm_path, encoding="utf-8"))["features"]:
        p, g = f["properties"], f["geometry"]
        hw = p.get("highway")
        if not hw or g["type"] != "LineString": continue
        if p.get("tunnel") == "yes" or str(p.get("layer", "0")).startswith("-"): continue
        if p.get("footway") == "crossing": continue
        w = CAR.get(hw) or FOOT.get(hw)
        if not w: continue
        try:
            lanes = int(p.get("lanes", 0) or 0)
            if lanes and hw in CAR: w = lanes * 3.0 + 1
        except ValueError:
            pass
        coords = g["coordinates"]
        for k in range(len(coords) - 1):
            lon1, lat1 = coords[k]; lon2, lat2 = coords[k + 1]
            tk = tile_key((lat1 + lat2) / 2, (lon1 + lon2) / 2)
            clat, clon = tile_center(tk)
            x1, z1 = to_local(clat, clon, lat1, lon1)
            x2, z2 = to_local(clat, clon, lat2, lon2)
            roads_by_tile.setdefault(tk, []).append(
                [round(w, 1), 1 if hw in FOOT else 0,
                 round(x1, 1), round(z1, 1), round(x2, 1), round(z2, 1)])

    for tk, roads in roads_by_tile.items():
        tid = f"{tk[0]}_{tk[1]}"
        path = os.path.join(out_dir, f"{tid}.json")
        if not os.path.exists(path): continue
        data = json.load(open(path, encoding="utf-8"))
        data["roads"] = roads
        json.dump(data, open(path, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)

print(f"완료 → {out_dir}  ({len(tiles_raw)}개 타일)")

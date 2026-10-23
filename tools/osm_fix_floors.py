"""
OSM building:levels → 타일 GIS 건물 층수 업데이트

GIS 타일의 est=1(층수 추정) 건물을 OSM building:levels 로 교정합니다.
중심 좌표가 8m 이내로 겹치는 건물만 업데이트 (오매칭 방지).

사용법:
    python tools/osm_fix_floors.py app/src/main/assets/data/tiles 36.330 127.344 1200
"""
import json, math, os, sys, urllib.request, urllib.parse

TILE_DEG = 0.005
DEFAULT_FLOOR_H = 3.2
MATCH_M = 15


def tile_key(lat, lon):
    return math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG)


def tile_center(tk):
    return (tk[0] + 0.5) * TILE_DEG, (tk[1] + 0.5) * TILE_DEG


def to_local(clat, clon, lat, lon):
    kx = math.cos(math.radians(clat)) * 111320.0
    return (lon - clon) * kx, -(lat - clat) * 110540.0


if len(sys.argv) < 4:
    sys.exit("사용법: osm_fix_floors.py <타일폴더> <위도> <경도> [반경m]")

tiles_dir, clat, clon = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
radius = float(sys.argv[4]) if len(sys.argv) > 4 else 1200

query = f"""[out:json][timeout:60];
way["building"]["building:levels"](around:{radius},{clat},{clon});
(._;>;);
out body;"""

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
print(f"Overpass 쿼리 중 … (중심 {clat},{clon}  반경 {radius}m)", flush=True)
data = urllib.parse.urlencode({"data": query}).encode()
osm = None
for endpoint in ENDPOINTS:
    try:
        req = urllib.request.Request(endpoint, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("User-Agent", "WindowViewApp/1.0")
        with urllib.request.urlopen(req, timeout=120) as resp:
            osm = json.loads(resp.read())
        print(f"  → {endpoint}", flush=True)
        break
    except Exception as e:
        print(f"  실패({endpoint}): {e}", flush=True)
if osm is None:
    sys.exit("Overpass 응답 없음")

nodes = {e["id"]: (e["lat"], e["lon"]) for e in osm["elements"] if e["type"] == "node"}
ways = [e for e in osm["elements"]
        if e["type"] == "way" and "building:levels" in e.get("tags", {})]
print(f"OSM building:levels 있는 건물 {len(ways)}채", flush=True)

tile_cache = {}


def load_tile(tk):
    if tk not in tile_cache:
        path = os.path.join(tiles_dir, f"{tk[0]}_{tk[1]}.json")
        tile_cache[tk] = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
    return tile_cache[tk]


updated = 0
modified = set()

for elem in ways:
    nd_ids = elem.get("nodes", [])
    if len(nd_ids) < 4 or nd_ids[0] != nd_ids[-1]:
        continue
    coords = [nodes[nid] for nid in nd_ids if nid in nodes]
    if len(coords) < 4:
        continue

    tags = elem.get("tags", {})
    try:
        fl_osm = int(float(tags["building:levels"]))
    except (ValueError, KeyError):
        continue
    if fl_osm < 1:
        continue

    h_osm = float(tags.get("height", 0) or 0) or round(fl_osm * DEFAULT_FLOOR_H, 1)

    clat_b = sum(p[0] for p in coords) / len(coords)
    clon_b = sum(p[1] for p in coords) / len(coords)
    tk = tile_key(clat_b, clon_b)

    d = load_tile(tk)
    if not d:
        continue

    tile_clat, tile_clon = tile_center(tk)
    cx_osm, cz_osm = to_local(tile_clat, tile_clon, clat_b, clon_b)

    for b in d["buildings"]:
        if b[3] != 1:  # 이미 확정된 GIS 데이터는 건드리지 않음
            continue
        flat = b[1]
        xs, zs = flat[0::2], flat[1::2]
        cx_gis = sum(xs) / len(xs)
        cz_gis = sum(zs) / len(zs)
        if math.hypot(cx_osm - cx_gis, cz_osm - cz_gis) < MATCH_M:
            if b[0] != fl_osm:
                b[0] = fl_osm
                b[2] = h_osm
                b[3] = 0  # 확정값으로 표시
                modified.add(tk)
                updated += 1
                print(f"  {tags.get('name','(이름없음)')}  {b[0]}층 → {fl_osm}층  ({clat_b:.5f},{clon_b:.5f})")
            break

for tk in modified:
    path = os.path.join(tiles_dir, f"{tk[0]}_{tk[1]}.json")
    json.dump(tile_cache[tk], open(path, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)

print(f"\n완료: {updated}채 층수 업데이트 → {len(modified)}개 타일 수정")

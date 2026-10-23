"""
osm_add_missing.py 로 잘못 추가된 건물(building:levels 없는 1층) 타일에서 제거

사용법:
    python tools/osm_revert_no_levels.py app/src/main/assets/data/tiles 36.335 127.344 1200
"""
import json, math, os, sys, urllib.request, urllib.parse

TILE_DEG = 0.005
MATCH_M = 8


def tile_key(lat, lon):
    return math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG)


def tile_center(tk):
    return (tk[0] + 0.5) * TILE_DEG, (tk[1] + 0.5) * TILE_DEG


def to_local(clat, clon, lat, lon):
    kx = math.cos(math.radians(clat)) * 111320.0
    return (lon - clon) * kx, -(lat - clat) * 110540.0


if len(sys.argv) < 4:
    sys.exit("사용법: osm_revert_no_levels.py <타일폴더> <위도> <경도> [반경m]")

tiles_dir, clat, clon = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
radius = float(sys.argv[4]) if len(sys.argv) > 4 else 1200

# building:levels 없는 건물만 쿼리 (이전에 잘못 추가한 것들)
query = f"""[out:json][timeout:30];
way["building"][!"building:levels"](around:{radius},{clat},{clon});
(._;>;);
out body;"""

print(f"Overpass 쿼리 중 … (제거 대상 탐색)", flush=True)
data = urllib.parse.urlencode({"data": query}).encode()
req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=data, method="POST")
req.add_header("Content-Type", "application/x-www-form-urlencoded")
req.add_header("User-Agent", "WindowViewApp/1.0")
with urllib.request.urlopen(req, timeout=90) as resp:
    osm = json.loads(resp.read())

nodes = {e["id"]: (e["lat"], e["lon"]) for e in osm["elements"] if e["type"] == "node"}
ways = [e for e in osm["elements"]
        if e["type"] == "way"
        and "building" in e.get("tags", {})
        and "building:levels" not in e.get("tags", {})]
print(f"제거 후보 OSM 건물 {len(ways)}채", flush=True)

tile_cache = {}


def load_tile(tk):
    if tk not in tile_cache:
        path = os.path.join(tiles_dir, f"{tk[0]}_{tk[1]}.json")
        tile_cache[tk] = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
    return tile_cache[tk]


removed = 0
modified = set()

for elem in ways:
    nd_ids = elem.get("nodes", [])
    if len(nd_ids) < 4 or nd_ids[0] != nd_ids[-1]:
        continue
    coords = [nodes[nid] for nid in nd_ids if nid in nodes]
    if len(coords) < 4:
        continue

    clat_b = sum(p[0] for p in coords) / len(coords)
    clon_b = sum(p[1] for p in coords) / len(coords)
    tk = tile_key(clat_b, clon_b)

    d = load_tile(tk)
    if not d:
        continue

    tile_clat, tile_clon = tile_center(tk)
    cx_osm, cz_osm = to_local(tile_clat, tile_clon, clat_b, clon_b)

    new_buildings = []
    for b in d["buildings"]:
        if b[0] == 1 and b[3] == 1:  # fl=1, est=1 인 것만 제거 후보
            flat = b[1]
            xs, zs = flat[0::2], flat[1::2]
            cx = sum(xs) / len(xs)
            cz = sum(zs) / len(zs)
            if math.hypot(cx - cx_osm, cz - cz_osm) < MATCH_M:
                removed += 1
                modified.add(tk)
                continue
        new_buildings.append(b)
    d["buildings"] = new_buildings

for tk in modified:
    path = os.path.join(tiles_dir, f"{tk[0]}_{tk[1]}.json")
    json.dump(tile_cache[tk], open(path, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)

print(f"\n완료: {removed}채 제거 → {len(modified)}개 타일 수정")

"""
OSM Overpass API → 타일 JSON에 누락 건물 추가

GIS 타일에 없는 건물(예미지 같은 신축 아파트)을 OSM 데이터로 보완합니다.
기존 건물과 중심 좌표가 8m 이내면 이미 있는 건물로 보고 skip.

사용법:
    python tools/osm_add_missing.py <타일폴더> <위도> <경도> [반경m]

예시 (도안 예미지 근처):
    python tools/osm_add_missing.py app/src/main/assets/data/tiles 36.335 127.344 800
"""
import json, math, os, sys, urllib.request, urllib.parse

TILE_DEG = 0.005
DEFAULT_FLOOR_H = 3.2
DEDUP_M = 8  # 이 거리(m) 이내 기존 건물 있으면 skip


def tile_key(lat, lon):
    return math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG)


def tile_center(tk):
    return (tk[0] + 0.5) * TILE_DEG, (tk[1] + 0.5) * TILE_DEG


def to_local(clat, clon, lat, lon):
    kx = math.cos(math.radians(clat)) * 111320.0
    return (lon - clon) * kx, -(lat - clat) * 110540.0


if len(sys.argv) < 4:
    sys.exit("사용법: osm_add_missing.py <타일폴더> <위도> <경도> [반경m]")

tiles_dir, clat, clon = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
radius = float(sys.argv[4]) if len(sys.argv) > 4 else 600

# ── Overpass 쿼리 ──
query = f"""[out:json][timeout:30];
way["building"](around:{radius},{clat},{clon});
(._;>;);
out body;"""

print(f"Overpass 쿼리 중 … (중심 {clat},{clon}  반경 {radius}m)", flush=True)
data = urllib.parse.urlencode({"data": query}).encode()
req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=data, method="POST")
req.add_header("Content-Type", "application/x-www-form-urlencoded")
req.add_header("User-Agent", "WindowViewApp/1.0")
with urllib.request.urlopen(req, timeout=90) as resp:
    osm = json.loads(resp.read())

nodes = {e["id"]: (e["lat"], e["lon"]) for e in osm["elements"] if e["type"] == "node"}
ways  = [e for e in osm["elements"] if e["type"] == "way" and "building" in e.get("tags", {})]
print(f"OSM 건물 {len(ways)}채 수신", flush=True)

# ── 타일 캐시 ──
tile_cache = {}


def load_tile(tk):
    if tk not in tile_cache:
        path = os.path.join(tiles_dir, f"{tk[0]}_{tk[1]}.json")
        tile_cache[tk] = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
    return tile_cache[tk]


def existing_centroids(tk):
    d = load_tile(tk)
    if not d:
        return []
    centroids = []
    for b in d["buildings"]:
        flat = b[1]
        xs, zs = flat[0::2], flat[1::2]
        centroids.append((sum(xs) / len(xs), sum(zs) / len(zs)))
    return centroids


# ── 건물 추가 ──
added = 0
modified = set()

for elem in ways:
    nd_ids = elem.get("nodes", [])
    if len(nd_ids) < 4 or nd_ids[0] != nd_ids[-1]:
        continue
    coords = [nodes[nid] for nid in nd_ids if nid in nodes]
    if len(coords) < 4:
        continue

    tags = elem.get("tags", {})
    fl = int(float(tags.get("building:levels", 0) or 0))
    if fl < 1:
        continue  # building:levels 없는 건물은 추가하지 않음
    h = float(tags.get("height", 0) or 0) or fl * DEFAULT_FLOOR_H
    est = 0

    clat_b = sum(p[0] for p in coords) / len(coords)
    clon_b = sum(p[1] for p in coords) / len(coords)
    tk = tile_key(clat_b, clon_b)

    d = load_tile(tk)
    if d is None:
        continue  # GIS 커버리지 밖 타일은 skip

    tile_clat, tile_clon = tile_center(tk)
    xz = [to_local(tile_clat, tile_clon, lat, lon) for lat, lon in coords]
    area2 = sum(xz[i][0] * xz[i+1][1] - xz[i+1][0] * xz[i][1] for i in range(len(xz) - 1))
    if area2 < 0:
        xz = xz[::-1]

    cx_new = sum(p[0] for p in xz) / len(xz)
    cz_new = sum(p[1] for p in xz) / len(xz)

    if any(math.hypot(cx_new - ex, cz_new - ez) < DEDUP_M for ex, ez in existing_centroids(tk)):
        continue  # 기존 건물과 겹침 → skip

    flat = [round(v, 2) for p in xz for v in p]
    d["buildings"].append([fl, flat, round(h, 1), est])

    name = (tags.get("name") or tags.get("addr:housename") or "").strip()
    if name:
        n = len(flat) // 2
        d["names"].append([
            round(sum(flat[i] for i in range(0, len(flat), 2)) / n, 1),
            round(sum(flat[i] for i in range(1, len(flat), 2)) / n, 1),
            name,
        ])

    modified.add(tk)
    added += 1
    print(f"  + {name or '(이름없음)'}  {fl}층  ({clat_b:.5f}, {clon_b:.5f})")

# ── 변경된 타일 저장 ──
for tk in modified:
    path = os.path.join(tiles_dir, f"{tk[0]}_{tk[1]}.json")
    json.dump(tile_cache[tk], open(path, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)

print(f"\n완료: {added}채 추가 → {len(modified)}개 타일 수정")

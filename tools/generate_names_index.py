"""
data/tiles/ 전체 → data/names_index.json (전역 검색용)

사용법:
    python tools/generate_names_index.py app/src/main/assets/data/tiles app/src/main/assets/data/names_index.json
"""
import json, glob, math, sys

tiles_dir, out_path = sys.argv[1], sys.argv[2]

index = []
seen = set()

for f in glob.glob(f"{tiles_dir}/*.json"):
    d = json.load(open(f, encoding='utf-8'))
    clat, clon = d['lat'], d['lon']
    KZ = 110540.0
    KX = math.cos(math.radians(clat)) * 111320.0
    for n in d.get('names', []):
        cx, cz, name = n[0], n[1], n[2]
        lat = round(clat - cz / KZ, 6)
        lon = round(clon + cx / KX, 6)
        key = f"{name}_{lat:.4f}_{lon:.4f}"
        if key in seen:
            continue
        seen.add(key)
        index.append([name, lat, lon])

index.sort(key=lambda x: x[0])
json.dump(index, open(out_path, 'w', encoding='utf-8'),
          ensure_ascii=False, separators=(',', ':'))
print(f"완료: {len(index)}개 → {out_path}")

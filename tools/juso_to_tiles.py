"""
행정안전부 도로명주소 건물DB + 국토부 GIS SHP → 타일 JSON 건물명 보강
아파트 단지명 등 GIS A24 필드에 없는 건물명을 추가합니다.

작동 방식:
  1. GIS SHP에서 법정동코드+지번 → 중심좌표 사전 구축
  2. 도로명주소 건물DB에서 건물명이 있는 행을 같은 키로 조회
  3. 좌표를 구한 건물명을 타일 JSON에 추가

사용법:
  python tools/juso_to_tiles.py \\
    <SHP경로(확장자 제외)> \\
    <build_daejeon.txt> \\
    app/src/main/assets/data/tiles

예시:
  python tools/juso_to_tiles.py \\
    "C:/Users/SBS/Downloads/AL_D010_30_20261009/AL_D010_30_20261009" \\
    "C:/Users/SBS/Downloads/건물DB/build_daejeon.txt" \\
    app/src/main/assets/data/tiles
"""
import json, math, os, sys

import shapefile
from pyproj import Transformer

TILE_DEG = 0.005
SRC_EPSG = 5186

# 도로명주소 건물DB 컬럼
COL_BDONG  = 0   # 법정동코드
COL_BNUM   = 6   # 법정본번
COL_BSUB   = 7   # 법정부번
COL_DONG   = 14  # 건물명 (동 이름: "101동")
COL_DANJI  = 25  # 단지명 (아파트 단지명: "한라비발디")

# GIS SHP 필드 인덱스
SHP_BDONG  = 3   # A3: 법정동코드
SHP_JIBUN  = 5   # A5: 지번 (예: "153-3" 또는 "96")

shp_base, txt_path, tiles_dir = sys.argv[1], sys.argv[2], sys.argv[3]

to_wgs = Transformer.from_crs(SRC_EPSG, 4326, always_xy=True)


def tile_key(lat, lon):
    return math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG)


def tile_center(tk):
    return (tk[0] + 0.5) * TILE_DEG, (tk[1] + 0.5) * TILE_DEG


def to_local(clat, clon, lat, lon):
    kx = math.cos(math.radians(clat)) * 111320.0
    return (lon - clon) * kx, -(lat - clat) * 110540.0


def jibun_key(bdong, bnum, bsub):
    """법정동코드_본번_부번 형태 키"""
    try:
        return f"{str(bdong).strip()}_{int(bnum)}_{int(bsub or 0)}"
    except (ValueError, TypeError):
        return None


def parse_jibun(jibun_str):
    """'153-3' → (153, 3), '96' → (96, 0)"""
    parts = str(jibun_str).strip().split('-')
    try:
        bnum = int(parts[0])
        bsub = int(parts[1]) if len(parts) > 1 else 0
        return bnum, bsub
    except (ValueError, IndexError):
        return None, None


# ── 1단계: GIS SHP → 법정동+지번 → 중심좌표 사전 구축 ──
print("SHP 읽는 중 …", flush=True)
jibun_to_coord = {}   # key → (lat, lon)
reader = shapefile.Reader(shp_base, encoding="cp949")
count = 0
for sr in reader.iterShapeRecords():
    rec = sr.record
    bdong = str(rec[SHP_BDONG]).strip()
    bnum, bsub = parse_jibun(rec[SHP_JIBUN])
    if bnum is None:
        continue
    key = jibun_key(bdong, bnum, bsub)
    pts = sr.shape.points
    if not pts:
        continue
    cx5 = sum(p[0] for p in pts) / len(pts)
    cy5 = sum(p[1] for p in pts) / len(pts)
    lon, lat = to_wgs.transform(cx5, cy5)
    coord = (lat, lon)

    if key not in jibun_to_coord:
        jibun_to_coord[key] = coord
    # 부번 무시 폴백 키 (본번만으로 매칭)
    fallback = f"{bdong}_{bnum}"
    if fallback not in jibun_to_coord:
        jibun_to_coord[fallback] = coord
    count += 1
    if count % 20000 == 0:
        print(f"  SHP {count}채 처리 …", flush=True)

print(f"SHP 완료: {count}개 키 구축", flush=True)

# ── 2단계: 도로명주소 건물DB 파싱 → 타일에 이름 추가 ──
for enc in ('utf-8-sig', 'utf-8', 'cp949'):
    try:
        open(txt_path, encoding=enc).readline()
        encoding = enc
        break
    except UnicodeDecodeError:
        continue

print(f"건물DB 읽는 중 (인코딩={encoding}) …", flush=True)
tile_cache = {}
added = 0
modified = set()
nomatch = 0

with open(txt_path, encoding=encoding) as f:
    for lineno, line in enumerate(f):
        cols = line.rstrip('\n').split('|')
        if len(cols) <= COL_DONG:
            continue
        danji = cols[COL_DANJI].strip() if len(cols) > COL_DANJI else ""
        dong  = cols[COL_DONG].strip()
        if danji and dong:
            name = f"{danji} {dong}"
        elif danji:
            name = danji
        elif dong:
            name = dong
        else:
            continue

        key = jibun_key(cols[COL_BDONG], cols[COL_BNUM], cols[COL_BSUB])
        fallback = f"{cols[COL_BDONG].strip()}_{cols[COL_BNUM].strip()}"
        coord = jibun_to_coord.get(key) or jibun_to_coord.get(fallback)
        if not coord:
            nomatch += 1
            continue

        lat, lon = coord
        if not (36.1 <= lat <= 36.6 and 127.2 <= lon <= 127.7):
            continue

        tk = tile_key(lat, lon)
        tid = f"{tk[0]}_{tk[1]}"
        path = os.path.join(tiles_dir, f"{tid}.json")
        if not os.path.exists(path):
            continue

        if tid not in tile_cache:
            tile_cache[tid] = json.load(open(path, encoding='utf-8'))

        data = tile_cache[tid]
        clat, clon = tile_center(tk)
        cx, cz = to_local(clat, clon, lat, lon)

        names = data.setdefault('names', [])
        if any(n[2] == name and abs(n[0] - cx) < 50 and abs(n[1] - cz) < 50 for n in names):
            continue

        names.append([round(cx, 1), round(cz, 1), name])
        modified.add(tid)
        added += 1

        if added % 500 == 0:
            print(f"  {added}개 추가 중 …", flush=True)

# 변경된 타일만 저장
for tid in modified:
    path = os.path.join(tiles_dir, f"{tid}.json")
    json.dump(tile_cache[tid], open(path, 'w', encoding='utf-8'),
              separators=(',', ':'), ensure_ascii=False)

print(f"\n완료: {added}개 이름 추가 → {len(modified)}개 타일 업데이트 (매칭 실패 {nomatch}개)")

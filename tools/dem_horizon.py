"""
지형(DEM) → 지역 데이터(json)에 "산 능선" 정보 추가

사용법 (PC에서):
    pip install rasterio numpy
    python dem_horizon.py Copernicus_DSM_COG_10_N36_00_E127_00_DEM.tif ../app/src/main/assets/data/dunsan.json

지역 json(gis_to_window.py가 만든 것)을 읽어서 같은 파일에 "terrain"을 덧붙여요.
  terrain.ground  지역 중심 땅높이(해발 m). 건물은 이 높이 위에 서 있다고 봐요
  terrain.dists   거리 구간 시작점(m) 목록. 반경 밖 ~30km를 64칸으로 (멀수록 넓게)
  terrain.h       [방위 0°,1°,...,359°][거리칸] = 그 칸에서 가장 높은 땅의 '보이는 높이'
                  (지역 땅높이 기준 m, 지구 곡률·대기 굴절 반영)
산 목표물(kind = "mountain")은 높이를 DEM 값으로 다시 맞춰요.

DEM: Copernicus DEM GLO-30 (30m). DSM이라 도심에서는 건물 높이가 섞여 있어서
반경 R 안(건물은 GIS건물통합정보로 따로 세움)은 쓰지 않고, 땅높이는 반경 안의 낮은 값(10%)으로 잡아요.
출처 표시: © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018,
provided under COPERNICUS by the European Union and ESA
"""
import json, math, sys

import numpy as np
import rasterio

tif_path, region_path = sys.argv[1], sys.argv[2]
MAX_D = 30000.0       # 산을 찾는 거리(m)
N_BINS = 64           # 거리 칸 수
STEP = 30.0           # 광선 위 샘플 간격(m) = DEM 해상도
K_REFRACT = 0.13      # 대기 굴절 계수 (곡률 효과를 13% 줄여 줌)
EARTH_R = 6371000.0

reg = json.load(open(region_path, encoding="utf-8"))
lat0, lon0, R = reg["lat"], reg["lon"], reg["R"]
mx = math.cos(math.radians(lat0)) * 111320.0  # 경도 1도 = m
my = 110540.0                                   # 위도 1도 = m

ds = rasterio.open(tif_path)
dem = ds.read(1).astype(np.float32)
inv = ~ds.transform


def sample(lon, lat):
    """양선형 보간 높이. 범위 밖은 NaN"""
    c, r = inv * (lon, lat)
    c, r = np.asarray(c) - 0.5, np.asarray(r) - 0.5
    c0, r0 = np.floor(c).astype(int), np.floor(r).astype(int)
    ok = (c0 >= 0) & (r0 >= 0) & (c0 < dem.shape[1] - 1) & (r0 < dem.shape[0] - 1)
    c0c, r0c = np.clip(c0, 0, dem.shape[1] - 2), np.clip(r0, 0, dem.shape[0] - 2)
    fc, fr = c - c0c, r - r0c
    v = (dem[r0c, c0c] * (1 - fc) * (1 - fr) + dem[r0c, c0c + 1] * fc * (1 - fr)
         + dem[r0c + 1, c0c] * (1 - fc) * fr + dem[r0c + 1, c0c + 1] * fc * fr)
    return np.where(ok, v, np.nan)


# 1) 지역 땅높이: 반경 R 안 격자의 10% 값 (DSM의 건물 높이를 피하려고 낮은 값)
gx, gy = np.meshgrid(np.arange(-R, R + 1, 15.0), np.arange(-R, R + 1, 15.0))
inside = gx ** 2 + gy ** 2 <= R * R
hv = sample(lon0 + gx[inside] / mx, lat0 + gy[inside] / my)
ground = float(np.nanpercentile(hv, 10))

# 2) 방위마다 광선을 쏴서 거리 칸별 최고점
start = R + 80.0
edges = start * (MAX_D / start) ** (np.arange(N_BINS + 1) / N_BINS)
d = np.arange(start, MAX_D, STEP)
bin_of = np.clip(np.searchsorted(edges, d, side="right") - 1, 0, N_BINS - 1)
drop = d ** 2 / (2 * EARTH_R) * (1 - K_REFRACT)  # 곡률로 낮아 보이는 만큼

H = np.full((360, N_BINS), -999, dtype=np.int32)
for az in range(360):
    a = math.radians(az)
    lon = lon0 + d * math.sin(a) / mx
    lat = lat0 + d * math.cos(a) / my
    h = sample(lon, lat) - ground - drop
    best = np.full(N_BINS, -np.inf)
    np.maximum.at(best, bin_of, np.nan_to_num(h, nan=-np.inf))
    H[az] = np.where(np.isfinite(best), np.round(best), -999)

reg["terrain"] = {
    "ground": round(ground, 1),
    "dists": [round(float(x)) for x in edges[:-1]],
    "h": H.tolist(),
    "source": "Copernicus DEM GLO-30 © DLR e.V. 2010-2014, © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the EU and ESA",
}

# 3) 산 목표물 높이를 DEM 값으로 (지역 땅높이 기준)
for t in reg["targets"]:
    if t.get("kind") == "mountain":
        lon = lon0 + t["x"] / mx
        lat = lat0 - t["z"] / my
        # 정상 근처(반경 150m) 최고점
        ox, oy = np.meshgrid(np.arange(-150, 151, 15.0), np.arange(-150, 151, 15.0))
        top = float(np.nanmax(sample(lon + ox.ravel() / mx, lat + oy.ravel() / my)))
        t["y"] = round(top - ground + 2, 1)
        t["approx"] = False

json.dump(reg, open(region_path, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)

# 확인용: 중심 땅 위 20m에서 본 방위별 산 높이각 상위
eye = 20.0
ang = np.degrees(np.arctan2(H - eye, np.array(edges[:-1])[None, :])).max(axis=1)
top = np.argsort(-ang)[:5]
print(f"{reg.get('label', region_path)}: 땅높이 {ground:.1f}m, 거리칸 {N_BINS}개({start:.0f}m~{MAX_D/1000:.0f}km)")
print("  가장 높이 보이는 산 방향(눈높이 20m): " + ", ".join(f"{a}° {ang[a]:.1f}°" for a in top))
print("  동쪽(90°) %.1f°, 남쪽(180°) %.1f°, 서쪽(270°) %.1f°" % (ang[90], ang[180], ang[270]))

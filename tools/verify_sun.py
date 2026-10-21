"""
앱의 해돋이·해넘이 계산을 한국천문연구원 출몰시각 정보(공공데이터포털 15012688)와 대조

사용법 (PC에서, 인터넷 연결 필요):
    python verify_sun.py                 # 앱 계산값만 출력
    python verify_sun.py 내_서비스키      # 천문연구원 값과 비교

서비스키: 공공데이터포털 → '한국천문연구원_출몰시각 정보' 활용신청 → 마이페이지의
'일반 인증키(Decoding)' 값. 키는 이 파일에 적지 말고 실행할 때만 넣으세요.

앱(index.html의 sunDir)과 같은 NOAA 공식, 같은 지평선 기준(-0.833°: 대기 굴절 + 해 반지름)을 써요.
"""
import math, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta

PLACES = {  # 앱에 들어 있는 지역 중심
    "대전 은행동": (36.32772, 127.42760),
    "대전 둔산동": (36.34940, 127.37682),
}
HORIZON = -0.833
API = "https://apis.data.go.kr/B090041/openapi/service/RiseSetInfoService/getLCRiseSetInfo"


def sun_alt(d: date, minute_kst: float, lat: float, lon: float) -> float:
    """해의 고도(도). index.html의 sunDir과 같은 식"""
    rad = math.pi / 180
    jd = (date(d.year, d.month, d.day) - date(1970, 1, 1)).days + 2440587.5 + (minute_kst / 60 - 9) / 24
    T = (jd - 2451545) / 36525
    L0 = (280.46646 + T * (36000.76983 + 0.0003032 * T)) % 360
    M = 357.52911 + T * (35999.05029 - 0.0001537 * T)
    e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T)
    C = (math.sin(M * rad) * (1.914602 - T * (0.004817 + 0.000014 * T))
         + math.sin(2 * M * rad) * (0.019993 - 0.000101 * T) + math.sin(3 * M * rad) * 0.000289)
    om = 125.04 - 1934.136 * T
    lam = L0 + C - 0.00569 - 0.00478 * math.sin(om * rad)
    eps0 = 23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(om * rad)
    dec = math.asin(math.sin(eps * rad) * math.sin(lam * rad))
    y = math.tan(eps * rad / 2) ** 2
    eot = 4 / rad * (y * math.sin(2 * L0 * rad) - 2 * e * math.sin(M * rad)
                     + 4 * e * y * math.sin(M * rad) * math.cos(2 * L0 * rad)
                     - 0.5 * y * y * math.sin(4 * L0 * rad) - 1.25 * e * e * math.sin(2 * M * rad))
    tst = ((minute_kst - 9 * 60) + eot + 4 * lon) % 1440
    H = (tst / 4 - 180) * rad
    la = lat * rad
    return math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(H)) / rad


def rise_set(d: date, lat: float, lon: float):
    """지평선(-0.833°)을 지나는 순간을 초 단위까지 찾아 분(소수)으로"""
    def cross(lo, hi):  # lo~hi 사이에서 이분법
        for _ in range(30):
            mid = (lo + hi) / 2
            if (sun_alt(d, lo, lat, lon) - HORIZON) * (sun_alt(d, mid, lat, lon) - HORIZON) <= 0:
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2
    rise = set_ = None
    for m in range(3 * 60, 22 * 60):
        a, b = sun_alt(d, m, lat, lon) - HORIZON, sun_alt(d, m + 1, lat, lon) - HORIZON
        if a <= 0 < b and rise is None:
            rise = cross(m, m + 1)
        if a > 0 >= b:
            set_ = cross(m, m + 1)
    return rise, set_


def hhmm(minute):  # 천문연구원 발표처럼 반올림한 시:분
    m = int(minute + 0.5)
    return f"{m // 60:02d}:{m % 60:02d}"


def kasi(key, d: date, lat, lon):
    q = urllib.parse.urlencode({
        "serviceKey": key, "locdate": d.strftime("%Y%m%d"),
        "longitude": f"{lon:.4f}", "latitude": f"{lat:.4f}", "dnYn": "Y",  # Y = 소수점 도 단위
    })
    with urllib.request.urlopen(f"{API}?{q}", timeout=15) as r:
        root = ET.fromstring(r.read())
    item = root.find(".//item")
    if item is None:
        msg = root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or "응답에 item 없음"
        raise RuntimeError(msg)
    t = lambda tag: (item.findtext(tag) or "").strip()
    to_min = lambda s: int(s[:2]) * 60 + int(s[2:4])
    return to_min(t("sunrise")), to_min(t("sunset"))


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else None
    today = date.today()
    days = sorted({today, date(today.year + 1, 1, 1)} | {date(today.year, m, 21) for m in (3, 6, 9, 12)})
    worst = 0.0
    for name, (lat, lon) in PLACES.items():
        print(f"\n■ {name} ({lat}, {lon})")
        print("날짜         앱 해돋이  앱 해넘이" + ("   천문연 해돋이  천문연 해넘이  차이(분)" if key else ""))
        for d in days:
            r, s = rise_set(d, lat, lon)
            line = f"{d}   {hhmm(r)}      {hhmm(s)}"
            if key:
                try:
                    kr, ks = kasi(key, d, lat, lon)
                    dr, ds = r - kr, s - ks
                    worst = max(worst, abs(int(r + 0.5) - kr), abs(int(s + 0.5) - ks))
                    line += f"     {hhmm(kr)}          {hhmm(ks)}       {dr:+.1f} / {ds:+.1f}"
                except Exception as e:
                    line += f"     (조회 실패: {e})"
            print(line)
    if key:
        print(f"\n가장 큰 차이: {worst:.0f}분 → " + ("통과 (1분 이내)" if worst <= 1 else "확인 필요"))
        print("천문연구원 값은 분 단위로 잘라 발표해서, 0.5~1분 차이는 반올림 차이일 수 있어요.")


if __name__ == "__main__":
    main()

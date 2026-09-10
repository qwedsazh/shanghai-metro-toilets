# -*- coding: utf-8 -*-
"""把 data/raw/stations/*.json 清洗聚合成发布版 data/stations.json。

做的事：
  1. 换乘站多记录按站名合并，厕所条目按 (线路, 描述) 去重取并集
  2. 坐标：以官方百度坐标(BD-09)为源，统一转 GCJ-02（高德/腾讯/微信地图用）
     和 WGS84（GPS 原始坐标，距离计算用），三套都存
  3. 每个厕所从描述文本解析费区属性(inside/outside/station_outside/both)，
     与图标冲突时以描述为准并记 zone_conflict
  4. 忽略官方不可靠的 toilet_inside 字段和机翻英文字段
"""
import json
import math
import re
from collections import OrderedDict
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw"
OUT = BASE / "data" / "stations.json"

# ---------------- 坐标转换 ----------------
X_PI = math.pi * 3000.0 / 180.0
PI = math.pi
A = 6378245.0
EE = 0.00669342162296594323


def bd09_to_gcj02(bd_lng: float, bd_lat: float):
    x = bd_lng - 0.0065
    y = bd_lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * X_PI)
    return z * math.cos(theta), z * math.sin(theta)


def _out_of_china(lng: float, lat: float) -> bool:
    return not (72.004 < lng < 137.8347 and 0.8293 < lat < 55.8271)


def _transform_delta(lng: float, lat: float):
    x = lng - 105.0
    y = lat - 35.0
    dlat = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    dlat += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    dlat += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    dlat += (160.0 * math.sin(y / 12.0 * PI) + 320 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    dlng = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    dlng += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    dlng += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    dlng += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    radlat = lat / 180.0 * PI
    magic = 1 - EE * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * PI)
    dlng = (dlng * 180.0) / (A / sqrtmagic * math.cos(radlat) * PI)
    return dlng, dlat


def gcj02_to_wgs84(lng: float, lat: float):
    """粗略逆变换，迭代一次精化，误差 <1m，对本应用足够。"""
    if _out_of_china(lng, lat):
        return lng, lat
    dlng, dlat = _transform_delta(lng, lat)
    w_lng, w_lat = lng - dlng, lat - dlat
    dlng2, dlat2 = _transform_delta(w_lng, w_lat)
    return lng - dlng2, lat - dlat2


# ---------------- 费区属性解析 ----------------
ICON_ZONE = {"t_i.png": "inside", "t_o.png": "outside",
             "t_os.png": "station_outside", "t_io.png": "both"}


def parse_zone(desc: str, icon: str):
    """返回 (zone, zone_conflict)。描述优先，图标兜底。"""
    d = desc or ""
    if "费区内/外" in d or "费区内、外" in d:
        z = "both"
    elif "费区内" in d:
        z = "inside"
    elif "费区外" in d:
        z = "outside"
    elif "车站外" in d:
        z = "station_outside"
    else:
        z = None
    iz = ICON_ZONE.get(icon or "")
    if z is None:
        return iz or "unknown", False
    conflict = bool(iz) and iz != z and not (z == "both" and iz in ("inside", "outside"))
    return z, conflict


def main() -> None:
    # 按站名收集记录
    by_name = OrderedDict()
    skipped = []
    for f in sorted((RAW / "stations").glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not data:
            skipped.append(f.stem)
            continue
        r = data[0]
        by_name.setdefault(r["name_cn"], []).append(r)

    stations = []
    conflict_count = 0
    gao_deviations = []
    wgs_offset_bad = []
    for name, recs in by_name.items():
        lines, stat_ids, toilets = [], [], OrderedDict()
        bd_pts = []
        name_en, pinyin = "", ""
        for r in recs:
            for ln in str(r.get("lines", "")).split(","):
                ln = ln.strip()
                if ln and ln not in lines:
                    lines.append(ln)
            sid = str(r.get("stat_id", "")).zfill(4)
            if sid and sid not in stat_ids:
                stat_ids.append(sid)
            if not name_en and r.get("name_en"):
                name_en = r["name_en"]
            if not pinyin and r.get("pinyin"):
                pinyin = r["pinyin"]
            try:
                blng, blat = float(r["longitude"]), float(r["latitude"])
                if blng and blat:
                    bd_pts.append((blng, blat))
            except (TypeError, ValueError):
                pass
            # 官方高德坐标 vs 我们转换的偏差（仅统计有官方值的）
            try:
                glng, glat = float(r.get("gao_lng") or 0), float(r.get("gao_lat") or 0)
                if glng and glat:
                    clng, clat = bd09_to_gcj02(blng, blat)
                    gao_deviations.append(math.hypot((clng - glng) * 100000, (clat - glat) * 89000))
            except (TypeError, ValueError):
                pass
            try:
                items = json.loads(r.get("toilet_position") or "{}").get("toilet", [])
            except Exception:
                items = []
            for t in items:
                if not isinstance(t, dict):
                    continue
                desc = re.sub(r"\s+", " ", (t.get("description") or "").strip())
                lineno = str(t.get("lineno", "")).strip()
                icon = t.get("icon1") or ""
                zone, conflict = parse_zone(desc, icon)
                if conflict:
                    conflict_count += 1
                key = (lineno, desc)
                if key in toilets and not toilets[key].get("zone_conflict"):
                    continue
                toilets[key] = {
                    "line": lineno,
                    "zone": zone,
                    "location": desc,
                    "accessible": bool(t.get("icon2")),
                    "icon": icon or None,
                    "zone_conflict": conflict or None,
                    "status": t.get("status"),
                    "plan_close_date": t.get("plan_close_date") or None,
                    "plan_open_date": t.get("plan_open_date") or None,
                }
        for t in toilets.values():
            for k in ("zone_conflict", "status", "plan_close_date", "plan_open_date"):
                if t[k] is None:
                    del t[k]
        if not bd_pts:
            print(f"  WARN 无有效坐标: {name}")
            continue
        blng = sum(p[0] for p in bd_pts) / len(bd_pts)
        blat = sum(p[1] for p in bd_pts) / len(bd_pts)
        glng, glat = bd09_to_gcj02(blng, blat)
        wlng, wlat = gcj02_to_wgs84(glng, glat)
        # GCJ-02 与 WGS84 的偏移在国内应为百米级；超出即转换公式有误
        off_m = math.hypot((glng - wlng) * 100000, (glat - wlat) * 89000)
        if not (100 < off_m < 1500):
            wgs_offset_bad.append((name, round(off_m)))
        stations.append({
            "name": name,
            "name_en": name_en,
            "pinyin": pinyin,
            "lines": sorted(lines, key=lambda x: (len(x), x)),
            "stat_ids": stat_ids,
            "coords": {
                "bd09": [round(blng, 7), round(blat, 7)],
                "gcj02": [round(glng, 7), round(glat, 7)],
                "wgs84": [round(wlng, 7), round(wlat, 7)],
            },
            "toilet_count": len(toilets),
            "toilets": list(toilets.values()),
        })

    doc = OrderedDict([
        ("meta", OrderedDict([
            ("name", "上海地铁车站卫生间数据集"),
            ("source", "抓取自上海地铁官网移动端页面（m.shmetro.com / service.shmetro.com），非官方开放接口"),
            ("fetched_at", str(date.today())),
            ("station_count", len(stations)),
            ("toilet_count", sum(s["toilet_count"] for s in stations)),
            ("line_alias", {"41": "浦江线", "51": "市域机场线"}),
            ("zone_meaning", {
                "inside": "费区内（需进站）", "outside": "费区外（无需进站）",
                "station_outside": "车站外公共厕所", "both": "费区内/外均有",
                "unknown": "未标注",
            }),
            ("coords_note", "bd09=官方原始；gcj02=BD-09转出，用于高德/腾讯/微信地图；"
                            "wgs84=GCJ-02逆变换，用于与GPS定位直接算距离"),
            ("disclaimer", "数据整理自上海地铁官方公开信息，仅供参考，以车站现场实际为准"),
        ])),
        ("stations", stations),
    ])
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    # 网页应用使用的紧凑版（GitHub Pages 只发布 docs/ 目录）
    WEB_OUT = BASE / "docs" / "data" / "stations.json"
    WEB_OUT.parent.mkdir(parents=True, exist_ok=True)
    WEB_OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    total_toilets = doc["meta"]["toilet_count"]
    print(f"跳过无效条目: {skipped}")
    print(f"车站: {len(stations)}, 厕所条目: {total_toilets}")
    print(f"zone_conflict(图标与描述冲突): {conflict_count}")
    if gao_deviations:
        gao_deviations.sort()
        n = len(gao_deviations)
        print(f"BD→GCJ 与官方高德坐标偏差(米): n={n} 中位={gao_deviations[n//2]:.1f} "
              f"p95={gao_deviations[int(n*0.95)]:.1f} 最大={gao_deviations[-1]:.1f}")
    zero_t = [s["name"] for s in stations if s["toilet_count"] == 0]
    print(f"无厕所条目的站: {zero_t}")
    print(f"WGS84偏移异常站(应为空): {wgs_offset_bad}")
    print(f"输出: {OUT} 和 {WEB_OUT}")


if __name__ == "__main__":
    main()

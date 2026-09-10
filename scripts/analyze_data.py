# -*- coding: utf-8 -*-
"""对 data/raw/stations/*.json 做数据质量评估。"""
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw"
TODAY = date.today()

station_list = json.loads((RAW / "station_list.json").read_text(encoding="utf-8"))
files = sorted((RAW / "stations").glob("*.json"))

empty, bad_json, records = [], [], []
for f in files:
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        bad_json.append(f.stem)
        continue
    if not isinstance(data, list):
        bad_json.append(f.stem + f"(非数组:{str(data)[:20]})")
        continue
    if not data:
        empty.append(f.stem)
        continue
    records.extend(data)

print(f"== 完整性 ==")
print(f"列表车站数: {len(station_list)}, 成功文件: {len(files)}, 空响应: {len(empty)} {empty[:5]}, 解析失败: {len(bad_json)}")
print(f"详情记录数: {len(records)}（换乘站多 ID 可能合并为 1 条）")

name2ids = {}
for item in station_list:
    name2ids.setdefault(item["value"], []).append(item["key"])
dup_names = {k: v for k, v in name2ids.items() if len(v) > 1}
print(f"唯一站名: {len(name2ids)}, 其中多 ID 站名(换乘站): {len(dup_names)}")

print(f"\n== 字段完整性 ==")
no_coords = [r["name_cn"] for r in records if not r.get("gao_lng") or not r.get("gao_lat")]
no_bd = [r["name_cn"] for r in records if not r.get("longitude") or not r.get("latitude")]
no_toilet_field = [r["name_cn"] for r in records if "toilet_position" not in r]
print(f"缺高德坐标: {len(no_coords)} {no_coords}")
print(f"缺百度坐标: {len(no_bd)} {no_bd[:8]}")
print(f"缺 toilet_position 字段: {len(no_toilet_field)}")

# 坐标是否落在上海范围内
out_of_box = []
for r in records:
    try:
        lng, lat = float(r["gao_lng"]), float(r["gao_lat"])
        if not (120.8 < lng < 122.3 and 30.6 < lat < 31.95):
            out_of_box.append((r["name_cn"], lng, lat))
    except (TypeError, ValueError):
        pass
print(f"坐标超出上海范围: {len(out_of_box)} {out_of_box[:5]}")

print(f"\n== 卫生间数据 ==")
toilet_empty, toilets = [], []
icon_counter, status_counter = Counter(), Counter()
line_counter = Counter()
closed_now, with_plan = [], 0
for r in records:
    tp = (r.get("toilet_position") or "").strip()
    if not tp:
        toilet_empty.append(r["name_cn"])
        continue
    try:
        items = json.loads(tp).get("toilet", [])
    except Exception:
        toilet_empty.append(r["name_cn"] + "(解析失败)")
        continue
    if not items:
        toilet_empty.append(r["name_cn"])
    for t in items:
        if not isinstance(t, dict):
            toilets.append((r["name_cn"], {"icon1": "(null条目)", "description": ""}))
            icon_counter["(null条目)"] += 1
            continue
        toilets.append((r["name_cn"], t))
        icon_counter[t.get("icon1", "?")] += 1
        status_counter[str(t.get("status", "无字段"))] += 1
        line_counter[str(t.get("lineno", "?"))] += 1
        pc, po = t.get("plan_close_date"), t.get("plan_open_date")
        if pc or po:
            with_plan += 1
            try:
                if pc and date.fromisoformat(pc) <= TODAY and (not po or date.fromisoformat(po) > TODAY):
                    closed_now.append((r["name_cn"], t.get("lineno"), t.get("description"), pc, po))
            except ValueError:
                pass

print(f"无卫生间信息的车站: {len(toilet_empty)}")
print(f"  {toilet_empty}")
print(f"卫生间条目总数: {len(toilets)}")
print(f"图标分布: {dict(icon_counter)}")
print(f"status 分布: {dict(status_counter)}")
print(f"按线路: {dict(sorted(line_counter.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 99))}")
print(f"带改造计划日期的条目: {with_plan}, 当前处于封闭期: {len(closed_now)}")
for c in closed_now:
    print(f"  封闭中: {c}")

print(f"\n== 描述文本质量 ==")
empty_desc = [(n, t) for n, t in toilets if not (t.get("description") or "").strip()]
print(f"空描述条目: {len(empty_desc)}")
desc_samples = [t.get("description", "") for _, t in toilets[:0]]
kw = Counter()
for _, t in toilets:
    d = t.get("description", "")
    if "费区内" in d: kw["费区内"] += 1
    if "费区外" in d: kw["费区外"] += 1
    if "站台" in d: kw["含'站台'"] += 1
    if "站厅" in d: kw["含'站厅'"] += 1
    if re.search(r"\d+号口", d): kw["含N号口"] += 1
    if "车头" in d or "车尾" in d or "头部" in d or "尾端" in d: kw["含车头/尾方位"] += 1
print(f"描述关键词覆盖: {dict(kw)}")

print(f"\n== 英文翻译抽查 ==")
for n, t in toilets[:0]:
    pass
mistrans = []
for r in records:
    en = r.get("toilet_position_en", "") or ""
    cn = (r.get("toilet_position") or "")
    for m in re.finditer(r"Exit (\d+)", en):
        if f"{m.group(1)}号口" not in cn:
            mistrans.append((r["name_cn"], m.group(0)))
print(f"英文出口号与中文不匹配(疑似机翻错位): {len(mistrans)} {mistrans[:8]}")

print(f"\n== 新线路覆盖核查 ==")
all_names = set(name2ids)
for probe in ["中春路", "景洪路", "三林南", "康桥东", "上海国际旅游度假区", "浦东1号2号航站楼",
              "国家会展中心", "蟠祥路·国家会计学院", "上海松江站", "苏州轨道交通11号线"]:
    hit = [n for n in all_names if probe in n]
    print(f"  '{probe}': {'有 ' + str(hit) if hit else '无'}")
lines_in_records = Counter()
for r in records:
    for ln in str(r.get("lines", "")).split(","):
        if ln.strip():
            lines_in_records[ln.strip()] += 1
print(f"records 中线路分布: {dict(sorted(lines_in_records.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999))}")

print(f"\n== toilet_inside 标志一致性 ==")
mismatch = []
for r in records:
    tp = (r.get("toilet_position") or "").strip()
    has_inside = False
    if tp:
        try:
            has_inside = any("i" in (t.get("icon1") or "") for t in json.loads(tp).get("toilet", []))
        except Exception:
            pass
    if bool(r.get("toilet_inside")) != has_inside:
        mismatch.append((r["name_cn"], r.get("toilet_inside"), has_inside))
print(f"toilet_inside 与实际条目不一致: {len(mismatch)} {mismatch[:10]}")

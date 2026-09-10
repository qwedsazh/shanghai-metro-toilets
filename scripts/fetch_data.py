# -*- coding: utf-8 -*-
"""全量抓取上海地铁车站详情数据（含卫生间信息）。

数据源：
  车站列表  https://m.shmetro.com/core/shmetro/mdstationinfoback_new.ashx?act=getAllStations
  单站详情  https://m.shmetro.com/interface/metromap/metromap.aspx?func=stationInfo&stat_id={id}

输出：
  data/raw/station_list.json        车站 ID/名称列表
  data/raw/stations/{stat_id}.json  每站原始响应（数组，通常 1 条）
  data/raw/_failed.json             抓取失败的 ID 列表（若有）
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw"
STATIONS_DIR = RAW / "stations"
LIST_URL = "https://m.shmetro.com/core/shmetro/mdstationinfoback_new.ashx?act=getAllStations"
INFO_URL = "https://m.shmetro.com/interface/metromap/metromap.aspx?func=stationInfo&stat_id={stat_id}"

HEADERS = {"User-Agent": "Mozilla/5.0 (research; shanghai-metro-toilet-dataset)"}
SLEEP = 0.15
TIMEOUT = 15
RETRIES = 3


def get_json(url: str):
    last_err = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch failed after {RETRIES} tries: {url}: {last_err}")


def main() -> None:
    force = "--force" in sys.argv
    STATIONS_DIR.mkdir(parents=True, exist_ok=True)

    station_list = get_json(LIST_URL)
    (RAW / "station_list.json").write_text(
        json.dumps(station_list, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"station list: {len(station_list)} entries")

    failed = []
    skipped = 0
    for i, item in enumerate(station_list, 1):
        stat_id = item["key"]
        out = STATIONS_DIR / f"{stat_id}.json"
        if out.exists() and not force:
            skipped += 1
            continue
        try:
            data = get_json(INFO_URL.format(stat_id=stat_id))
            out.write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except Exception as e:  # noqa: BLE001
            failed.append({"stat_id": stat_id, "name": item["value"], "error": str(e)})
            print(f"  FAILED {stat_id} {item['value']}: {e}")
        if i % 50 == 0:
            print(f"  progress {i}/{len(station_list)}")
        time.sleep(SLEEP)

    (RAW / "_failed.json").write_text(
        json.dumps(failed, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"done. fetched={len(station_list) - skipped - len(failed)} "
          f"skipped(existed)={skipped} failed={len(failed)}")


if __name__ == "__main__":
    main()

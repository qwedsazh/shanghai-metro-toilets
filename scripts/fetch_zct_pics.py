# -*- coding: utf-8 -*-
"""下载官方站层图并压缩为 WebP 打包进 docs/pics/zct/。

流程：
  1. 从 data/stations.json 取全部唯一 stat_id
  2. 下载 https://service.shmetro.com/skin/zct/{id}.jpg 原图存 data/raw/zct/（留档，可复现）
  3. 缩放到 1800px 宽 + WebP q82 输出到 docs/pics/zct/{id}.webp（App 加载的就是它）

用法：
  python scripts/fetch_zct_pics.py               # 增量：已有原图的跳过下载
  python scripts/fetch_zct_pics.py --force       # 全量重抓重压
  python scripts/fetch_zct_pics.py --recompress  # 不下载，用本地原图按当前参数全量重压
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw" / "zct"
OUT = BASE / "docs" / "pics" / "zct"
SRC_URL = "https://service.shmetro.com/skin/zct/{stat_id}.jpg"
TARGET_W = 1800
WEBP_Q = 82

FORCE = "--force" in sys.argv
RECOMPRESS = "--recompress" in sys.argv


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    doc = json.loads((BASE / "data" / "stations.json").read_text(encoding="utf-8"))
    ids = sorted({i for s in doc["stations"] for i in s["stat_ids"]})

    downloaded = skipped = 0
    failed = []
    for n, sid in enumerate(ids, 1):
        raw_path = RAW / f"{sid}.jpg"
        if RECOMPRESS and not raw_path.exists():
            failed.append((sid, "recompress 模式缺原图"))
            continue
        if RECOMPRESS or (raw_path.exists() and not FORCE):
            skipped += 1
        else:
            try:
                req = urllib.request.Request(SRC_URL.format(stat_id=sid),
                                             headers={"User-Agent": "Mozilla/5.0"})
                raw_path.write_bytes(urllib.request.urlopen(req, timeout=20).read())
                downloaded += 1
                time.sleep(0.15)  # 礼貌限速
            except Exception as e:
                failed.append((sid, str(e)))
                if raw_path.exists():
                    raw_path.unlink()
                continue
        # 压缩（webp 已是最新则跳过；--force/--recompress 时无条件重压）
        webp_path = OUT / f"{sid}.webp"
        if (webp_path.exists() and webp_path.stat().st_mtime >= raw_path.stat().st_mtime
                and not FORCE and not RECOMPRESS):
            continue
        im = Image.open(raw_path)
        if im.mode != "RGB":
            im = im.convert("RGB")
        w, h = im.size
        if w > TARGET_W:
            im = im.resize((TARGET_W, int(h * TARGET_W / w)), Image.LANCZOS)
        im.save(webp_path, "WEBP", quality=WEBP_Q, method=6)
        if n % 50 == 0:
            print(f"  进度 {n}/{len(ids)}")

    total_raw = sum(f.stat().st_size for f in RAW.glob("*.jpg"))
    total_webp = sum(f.stat().st_size for f in OUT.glob("*.webp"))
    print(f"下载 {downloaded} 张，跳过已有 {skipped} 张，失败 {len(failed)} 张")
    if failed:
        print(f"失败列表: {[s for s, _ in failed]}")
        for s, e in failed[:5]:
            print(f"  {s}: {e}")
    print(f"原图留档 {total_raw/1024/1024:.1f}MB -> 打包 WebP {total_webp/1024/1024:.1f}MB"
          f"（{len(list(OUT.glob('*.webp')))} 张）")


if __name__ == "__main__":
    main()

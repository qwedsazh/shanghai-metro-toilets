# 上海地铁厕所通 · shanghai-metro-toilets

上海地铁**全网 415 座车站、628 个卫生间**的位置数据集 + 查询 PWA。

数据源为上海地铁官网车站信息接口，GitHub Actions **每周自动更新**，跟得上新线开通和厕所改造。

## 功能

- **定位找最近**：基于 GPS 定位，按距离列出最近车站的厕所
- **费区内/外筛选**：没进站只看费区外（含车站外公厕），已进站只看费区内
- **线路浏览**：全网 20 条线路（含浦江线、市域机场线）逐站查看
- **地图模式**：全网车站厕所一览
- **数据上报**：发现错误一键提 issue（可附现场照片/平面图）

## 在线使用

部署于 GitHub Pages：`https://<你的用户名>.github.io/shanghai-metro-toilets/`

安装到手机（无需应用商店）：

- **安卓** Chrome：菜单 → 「安装应用」/「添加到主屏幕」
- **iOS** Safari：分享 → 「添加到主屏幕」

## 数据集

发布版：`data/stations.json`（网页版用的是同内容紧凑格式 `docs/data/stations.json`）
原始抓取：`data/raw/`（车站列表 + 每站官方原始响应，可复现）

### Schema

```jsonc
{
  "meta": { "fetched_at": "2026-09-10", "station_count": 415, "toilet_count": 628 },
  "stations": [{
    "name": "武宁路", "name_en": "Wuning Road", "pinyin": "wnl",
    "lines": ["13", "14"],          // 41=浦江线, 51=市域机场线
    "stat_ids": ["1329", "1432"],   // 官方车站 ID（换乘站多个）
    "coords": {
      "bd09":  [121.43, 31.23],     // 官方原始（百度坐标系）
      "gcj02": [121.43, 31.23],     // 高德/腾讯/微信地图显示用
      "wgs84": [121.42, 31.23]      // 与 GPS 定位直接算距离用
    },
    "toilets": [{
      "line": "13",
      "zone": "inside",             // inside 费区内 / outside 费区外
                                    // station_outside 车站外公厕 / both 内外均有
      "location": "费区内 往张江路方向车头",
      "accessible": true,           // 有无障碍设施
      "plan_close_date": "2025-10-14",  // 可选：改造封闭期（仅参考）
      "plan_open_date": "2025-10-16"
    }]
  }]
}
```

坐标系注意：手机 GPS / 浏览器定位是 WGS84，高德/腾讯 SDK 是 GCJ-02，两者在上海差约 500 米，**计算和显示必须用同一坐标系**，三套坐标都已备好。

## 数据更新机制

```
scripts/fetch_data.py --force   # 全量抓取官方接口（534 站，约 3 分钟）
scripts/build_dataset.py        # 清洗聚合 + 坐标转换 → data/stations.json + docs/data/stations.json
scripts/analyze_data.py         # 数据质量检查（覆盖率/冲突/异常）
```

`.github/workflows/update-data.yml` 每周一自动执行上述流程，有变化才提交。

## 本地开发

```bash
cd docs
python -m http.server 8000
# 打开 http://localhost:8000
```

无构建步骤，纯静态文件。定位功能需要 HTTPS 或 localhost 环境。

## 已知数据问题

- **上海赛车场站**（11 号线）：官方接口无该站详情，欢迎提 issue 补充
- 官方数据中 9 处"图标与文字描述矛盾"，已以文字描述为准并标记 `zone_conflict`
- 改造封闭日期可能滞后，仅供参考；以车站现场指示为准

## 贡献

数据纠错请提 [issue](../../issues/new?template=toilet-report.yml)（可附照片）。代码改进欢迎 PR。

## 免责声明

数据整理自上海地铁官方公开信息，仅供出行参考，以车站现场实际情况为准。本项目与上海申通地铁集团无关。

## License

MIT

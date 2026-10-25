# -*- coding: utf-8 -*-
"""tools/compare_versions.py —— v1（未修）vs v2（修了 6 处缺口 + 6 轮搜索）对照

只读两个目录的产物，不做任何计算，输出 `reports/优化对比.md`：
  1. 引擎缺口：6 处补丁（P1~P6）修了什么
  2. 逐位回归：50 个配置在补丁前后是否指标一致
  3. 搜索规模：轮次 / 配置数 / 每轮配置数
  4. 八层漏斗：逐层存活对照
  5. 入围名单与封存期结果对照（有就填，没有就写不可用）

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/compare_versions.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT.parent / "ep010-research"
LAYERS = ["l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8"]
TRACK_NAMES = {"A": "AI-A", "B": "AI-B", "MONKEY": "主随机", "MS": "20 组猴子合并池"}


def jload(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                  # noqa: BLE001
        return None


def ledger_stats(path: Path) -> dict:
    led = pd.read_csv(path, dtype=str, keep_default_na=False)
    out = {"rows": len(led), "ok": int((led["status"] == "ok").sum()),
           "err": int((led["status"] != "ok").sum())}
    for g in ("A", "B", "monkey_43"):
        sub = led[led["group"] == g]
        base = sub[(sub["start"] == "20140101") & ~sub["config"].str.contains("__")]
        out[g] = {"rows": len(sub), "base": len(base.drop_duplicates("config"))}
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    md = ["# v1 → v2：优化了什么、差在哪", ""]
    md.append("v1 = 第一次复刻（引擎原样、每路 2 轮 × 24 配置）。"
              "v2 = 修掉引擎缺口后重跑（每路 6 轮 × 39 配置）。**数据完全相同**"
              "（`data/raw/daily.parquet` 逐字节一致），所以差异只来自代码与搜索规模。")
    md.append("")

    # ---------------------------------------------------------------- 1
    md += ["## 1. 引擎缺口：6 处补丁", "",
           "| 编号 | 缺口 | 修法 | 证据 |", "|---|---|---|---|"]
    md.append("| P1 | `find_config_yaml` 的配置索引只在首次调用时构建；`farm` 先建索引再写配置单，"
              "导致每个种子的 L5 全部「找不到原配置单」 | 新增 `refresh_config_index()`，"
              "`gen_monkey` 与 `plan_l5_l6` 写盘后调用 | v1 里 20 个种子共 62 条 `找不到原配置单`；"
              "v2 的 farm 再无此错误 |")
    md.append("| P2 | `canonical_config()` 把 `name`/`desc` 纳入比较键（两者唯一），"
              "rules 第 11 章的随机配置去重恒不触发 | 归一时剔除 `name`/`desc` | v2 的 204 个猴子配置"
              "规范化后 204 个不同结构（v1 做不到这一点） |")
    md.append("| P3 | 市场级零件 `etf_above_ma_n` 可作打分因子/排序键/嵌套基零件，截面秩恒并列 → "
              "零信息组合照样过 L1~L5 | 解析期拒绝并给出指引 | v1 的 `m43_028`（唯一因子就是它）"
              "进了主随机入围名单；v2 生成器不再产生这类配置 |")
    md.append("| P4 | P3 那类配置在回测期抛 `KeyError('close_adj')`（在股票面板上找 ETF 列） | "
              "市场级零件在错误面板上抛带指引的 RuntimeError | v1 的 `m43_026` 是这 1 例 |")
    md.append("| P5 | L5 的「空邻域空真通过」没有任何标记，报告无法注明检验范围（rules 5.2） | "
              "`l5_detail` 记录 `empty_neighborhood` | v2 的漏斗报告可以点名哪些 L5 是空真 |")
    md.append("| P6 | 随机配置生成器的因子池包含市场级零件（P3 的源头） | 因子池剔除 `MARKET_LEVEL_OPS` | "
              "v2 的 204 个猴子配置里 0 个含该零件作因子 |")
    md.append("")

    # ---------------------------------------------------------------- 2
    reg = jload(ROOT / "data" / "regress_50.json")
    md += ["## 2. 逐位回归（rules.md 第 12 章）", ""]
    if reg:
        md.append(f"- 样本 {reg['n_compared']} 个配置（从 v1 台账分层抽样 + 2 条邻域探针），"
                  f"比对 27 个数值列，零容差（缺失与 NaN 视为同一缺失，其余按双精度逐位相等）")
        md.append(f"- 结果：**{reg['bit_identical']}/{reg['n_compared']} 逐位一致**；"
                  f"被 P3 拒绝 {len(reg.get('rejected_by_p3') or [])} 个（预期变化）；"
                  f"不一致 {len(reg.get('mismatches') or [])} 个")
        md.append("- 明细：`reports/regress_50.md`")
    else:
        md.append("- 还没跑 `tools/regress_50.py`，本节不可用。")
    md.append("")

    # ---------------------------------------------------------------- 3
    def _scale(base: Path) -> dict:
        st = base / "strategies"
        def cnt(d):
            return len(list(d.glob("*.yaml"))) if d.is_dir() else 0
        rounds = [d for g in ("A", "B") for d in sorted((st / g).glob("round*"))]
        per = sum(cnt(d) for d in rounds) / len(rounds) if rounds else 0
        return {"rounds": len(rounds), "per_round": round(per),
                "A": cnt(st / "A") if (st / "A").is_dir() else sum(cnt(d) for d in (st / "A").glob("round*")),
                "B": sum(cnt(d) for d in (st / "B").glob("round*")) if (st / "B").is_dir() else 0,
                "random": cnt(st / "random"),
                "farm": len(list((st / "monkey_farm").glob("*.yaml"))) if (st / "monkey_farm").is_dir() else 0}
    s1, s2 = _scale(V1), _scale(ROOT)
    md += ["## 3. 搜索规模", "", "| | v1 | v2 |", "|---|---|---|",
           f"| 轮次目录 | {s1['rounds']} | {s2['rounds']} |",
           f"| 每轮配置数（实测） | {s1['per_round']} | {s2['per_round']} |",
           f"| A 组基础配置 | {s1['A']} | {s2['A']} |",
           f"| B 组基础配置 | {s1['B']} | {s2['B']} |",
           f"| 主随机组 | {s1['random']} | {s2['random']} |",
           f"| 农场配置总数 | {s1['farm']} | {s2['farm']} |", ""]

    # ---------------------------------------------------------------- 4
    md += ["## 4. 八层漏斗", "",
           "| 展示路 | 版本 | " + " | ".join(x.upper() for x in LAYERS) + " | final |",
           "|---|---|" + "---|" * (len(LAYERS) + 1)]
    for ver, base in (("v1", V1), ("v2", ROOT)):
        lay = jload(base / "data" / "funnel_layers.json") or {}
        tracks = lay.get("tracks", {})
        for key, name in TRACK_NAMES.items():
            t = tracks.get(key) or {}
            row = [f"{name}", ver] + [str(len(t.get(k) or [])) for k in LAYERS] + \
                  [str(len(t.get("final") or []))]
            md.append("| " + " | ".join(row) + " |")
    md.append("")
    md.append("读法提醒：v2 的 L5 比 v1 严（P5 会把空邻域显式标出来），"
              "而且 v2 的配置数大 4 倍，逐层计数不能直接横比，要按『占基础配置的比例』看。")
    md.append("")

    # ---------------------------------------------------------------- 5
    md += ["## 5. 入围名单", ""]
    for ver, base in (("v1", V1), ("v2", ROOT)):
        for g in ("AI", "monkey_43"):
            sl = jload(base / "data" / f"shortlist_{g}.json") or {}
            names = sl.get("shortlist") or []
            if names:
                md.append(f"- {ver} / {g}：硬性合格 {sl.get('n_qualified')} 个 → "
                          + "、".join(f"`{n}`" for n in names))
    md.append("")

    # ---------------------------------------------------------------- 6
    md += ["## 6. 开封后（封存期）", ""]
    for ver, base in (("v1", V1), ("v2", ROOT)):
        se = jload(base / "data" / "sealed_eval.json")
        if not se:
            md.append(f"- {ver}：未开封或未评估")
            continue
        b = se.get("benchmark_510300_bh", {})
        md.append(f"- {ver}：基准 510300 买入持有 {b.get('ann_ret', float('nan')):+.2%}"
                  f"（回撤 {b.get('max_dd', float('nan')):+.2%}）")
        for g, gd in se.get("groups", {}).items():
            cands = [f"{n} {c['ann_excess']:+.2%}" for n, c in gd.get("candidates", {}).items()
                     if c.get("available")]
            if cands:
                md.append(f"  - {ver} / {g}：" + "、".join(cands) + "（年化超额）")
    md.append("")

    md += ["## 7. 还没修的缺口（诚实清单）", "",
           "- `xsec_pct / ts_pct / ind_rank` 把窗口藏在 `of` 里，`enumerate_params` 只看顶层 n → "
           "这类因子不产生 L5 邻域（第 6 轮 agent 实测：A 组 IR 前 5 里有 2 条是空邻域）。"
           "v2 只做到「显式标注」（P5），没有把枚举器改成递归——那会改变 L5 的判定口径，"
           "属于研究规则层面的决定，不该由复刻方单方面改。",
           "- 并行执行偶发 `KeyError(0)`：v2 的 204 个随机配置里有 1 个在 8 worker 下报错，"
           "单进程复跑正常。未定位到根因，如实记录在台账（错误行保留、计入 N）。",
           "- 验证期（2023–2024）在流程上仍然敞开着：`guard` 只锁 2025 及以后，"
           "搜索角色能不能看验证期仍靠纪律而不是代码。",
           "- 行情仍然是合成的。", ""]
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "优化对比.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("[compare] 写出 reports/优化对比.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

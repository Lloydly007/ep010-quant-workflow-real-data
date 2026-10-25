r"""分轮统计：按 (group, 轮次) 汇总成功率与收益分布，重复行按 (config,start,end) 去重取最新。

用法：python tools/round_stats.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ledger" / "ledger.csv"

ROUND_RE = re.compile(r"^(?:a|b)_r(\d)_")


def main() -> int:
    d = pd.read_csv(LEDGER)
    d["group"] = d["group"].astype(str)

    # 同一配置同区间跑了多次的，只留最后一行（看门狗重起导致过重复）
    d = d[d["group"].astype(str) != "test"]           # test 不计入研究组 N（rules.md）
    d = d.sort_values("ts").drop_duplicates(subset=["config", "start", "end"], keep="last")

    ai = d[d["group"].isin(["A", "B"])].copy()
    # 只统计**基础配置**：名字含 __ 的是 L5 邻域探针，算进来会把 L2/L3 通过率虚高
    ai = ai[~ai["config"].astype(str).str.contains("__")]
    ai["round"] = ai["config"].map(lambda s: int(ROUND_RE.match(str(s)).group(1)) if ROUND_RE.match(str(s)) else 0)

    print(f"台账去重后 {len(d)} 行")
    print("\n== AI 组（按轮次）==")
    print(f"{'轮':>2} {'臂':>2} {'份数':>5} {'ok':>5} {'年化中位':>9} {'超额中位':>9} {'L2':>4} {'L3':>4}")
    for (rnd, arm), x in ai.groupby(["round", "group"]):
        ok = x[x["status"] == "ok"]
        if not len(ok):
            continue
        l2 = int((ok["funnel_l2"] == 1).sum())
        l3 = int((ok["funnel_l3"] == 1).sum())
        print(f"{rnd:>2} {arm:>2} {len(x):>5} {len(ok):>5} "
              f"{ok['ann_ret'].median()*100:>8.1f}% {ok['ann_excess'].median()*100:>8.1f}% "
              f"{l2:>4} {l3:>4}")

    mon = d[d["group"].str.startswith("monkey")]
    if len(mon):
        okm = mon[mon["status"] == "ok"]
        print("\n== 随机对照（monkey）==")
        print(f"唯一配置 {okm['config'].nunique()} | 年化中位 {okm['ann_ret'].median()*100:.1f}% "
              f"| 超额中位 {okm['ann_excess'].median()*100:.1f}% "
              f"| L2 {int((okm['funnel_l2']==1).sum())} | L3 {int((okm['funnel_l3']==1).sum())}")

        print("\n== AI vs 随机：L2 通过率 ==")
        for arm in ("A", "B"):
            x = ai[ai["group"] == arm]
            xo = x[x["status"] == "ok"]
            if len(xo):
                print(f"  {arm} 路: {int((xo['funnel_l2']==1).sum())}/{len(xo)} "
                      f"= {(xo['funnel_l2']==1).mean()*100:.1f}%")
        print(f"  随机:  {int((okm['funnel_l2']==1).sum())}/{len(okm)} "
              f"= {(okm['funnel_l2']==1).mean()*100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())

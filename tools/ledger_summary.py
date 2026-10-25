# -*- coding: utf-8 -*-
"""tools/ledger_summary.py —— 台账速览（复刻用的辅助脚本，不改动引擎）

按组汇总 L1~L4 的通关分布、按 IR 排序的前若干条、以及失败/报错行的原因，
用于第 4 步搜索的轮次复盘与报告取证。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/ledger_summary.py [--group A] [--top 10]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ledger" / "ledger.csv"
NUM = ["n_trades", "ann_ret", "bench_ann_ret", "ann_excess", "ir",
       "excess_max_dd", "beat_years", "total_years", "ic_mean", "icir",
       "turnover_ann", "cap_median"]


def load() -> pd.DataFrame:
    led = pd.read_csv(LEDGER, dtype=str, keep_default_na=False)
    for c in NUM:
        if c in led.columns:
            led[c] = pd.to_numeric(led[c], errors="coerce")
    lcols = ["funnel_l1", "funnel_l2", "funnel_l3", "funnel_l4"]
    for c in lcols:
        led[c] = pd.to_numeric(led[c].replace("", "0"), errors="coerce").fillna(0).astype(int)
    led["layer"] = led[lcols].astype(str).agg("".join, axis=1)
    return led


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="台账速览")
    ap.add_argument("--group", default=None, help="只看某个组（缺省=全部）")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args(argv)
    led = load()
    if a.group:
        led = led[led["group"] == a.group]
    print(f"台账行数：{len(led)}；组：{sorted(led['group'].unique())}")
    print(f"成功 {int((led['status'] == 'ok').sum())} / 非成功 {int((led['status'] != 'ok').sum())}")
    print("\n=== L1~L4 通关分布（按组）===")
    tab = led.pivot_table(index="group", columns="layer", values="config",
                          aggfunc="count", fill_value=0)
    print(tab.to_string())
    print(f"\n=== 按 IR 排序前 {a.top} 条 ===")
    cols = [c for c in ["config", "group", "type", "n_trades", "ann_excess",
                        "ir", "excess_max_dd", "beat_years", "layer",
                        "icir", "turnover_ann"] if c in led.columns]
    print(led.drop_duplicates("config").sort_values("ir", ascending=False)
          .head(a.top)[cols].to_string(index=False))
    bad = led[led["status"] != "ok"]
    if len(bad):
        print("\n=== 非成功执行 ===")
        print(bad[["config", "group", "status", "note"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

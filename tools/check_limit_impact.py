r"""封存期受涨跌停口径修正影响多大：逐笔检查已成交记录。

背景：封存评估只跑一次（engine 的 guard 会拒绝重跑，这是对的）。但我们刚刚
修正了 stk_limit 的档位（创业板/科创板 20%、ST 5%），必须回答一个问题：
**已出的封存结果有没有被这个缺陷影响？**

做法：把三席+三只猴子的封存期成交拿出来，与新旧两套涨跌停价对齐，
统计有多少笔成交发生在「两套口径会给出不同结论」的股票日上。
若为 0，则封存结论不受该缺陷影响。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "reports" / "runs"
NAMES = ["a_r6_s3_03_dose030_u250_t120", "a_r6_s3_06_dose045_u250_t120",
         "b_r5_s2_30_ulcer_extra_1to2", "m43_046", "m43_050", "m43_084"]


def main() -> int:
    new_lim = pd.read_parquet(ROOT / "data" / "sealed" / "stk_limit.parquet")
    old_lim = pd.read_parquet(ROOT / "data" / "sealed" / "stk_limit_legacy.parquet")
    for df in (new_lim, old_lim):
        df["ts_code"] = df["ts_code"].astype(str)
        df["trade_date"] = df["trade_date"].astype(str)
    key = ["ts_code", "trade_date"]
    lim = new_lim[key + ["up_limit", "down_limit"]].merge(
        old_lim[key + ["up_limit", "down_limit"]], on=key, suffixes=("_new", "_old"))
    diff = lim[(lim["up_limit_new"] - lim["up_limit_old"]).abs() > 0.005]
    print(f"封存期涨跌停价有差异的股票日：{len(diff):,} / {len(lim):,} "
          f"({len(diff)/max(len(lim),1)*100:.1f}%)")

    total_trades = 0
    hit = 0
    for name in NAMES:
        trades = None
        for d in RUNS.glob(f"{name}__2025*"):
            p = d / "trades.parquet"
            if p.exists():
                trades = pd.read_parquet(p)
                break
        if trades is None:
            print(f"  {name}: 无封存期 trades.parquet")
            continue
        cols = {c.lower(): c for c in trades.columns}
        ccode = cols.get("ts_code") or cols.get("code")
        cdate = cols.get("exec_date") or cols.get("trade_date") or cols.get("date")
        if not (ccode and cdate):
            print(f"  {name}: trades 列名不认识 {list(trades.columns)[:8]}")
            continue
        t = trades[[ccode, cdate]].copy()
        t.columns = key
        t[key] = t[key].astype(str)
        m = t.merge(diff.assign(affected=1), on=key, how="left")
        n_hit = int(m["affected"].fillna(0).sum())
        total_trades += len(t)
        hit += n_hit
        print(f"  {name}: 成交 {len(t):,} 笔，落在差异日 {n_hit} 笔")

    print(f"\n合计成交 {total_trades:,} 笔，其中 {hit} 笔发生在口径差异日")
    if hit == 0:
        print("[结论] 封存期成交没有一笔落在口径差异日 → 封存结论不受该缺陷影响")
    else:
        print("[结论] 有成交落在差异日，封存结论可能受影响，需在报告中标注")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

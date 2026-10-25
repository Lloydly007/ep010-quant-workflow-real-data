r"""核对基准口径：run 目录里的 benchmark_nav 到底是不是 510300 买入持有。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "reports" / "runs"
NAME = "a_r6_s3_03_dose030_u250_t120"

d = pd.read_csv(RUN / f"{NAME}__20250101_20260930" / "daily_returns.csv")
d["date"] = pd.to_datetime(d["date"].astype(str), format="%Y%m%d")
print("窗口", d["date"].min().date(), "~", d["date"].max().date(), "行数", len(d))
for col in ("strategy_nav", "benchmark_nav"):
    nav = d[col]
    print(f"{col}: 期末 {nav.iloc[-1]:.4f}  累计 {(nav.iloc[-1]-1)*100:.2f}%  "
          f"年化 {(nav.iloc[-1]**(250/len(nav))-1)*100:.2f}%")

fd = pd.read_parquet(ROOT / "data" / "sealed" / "fund_daily.parquet")
e = fd[fd["ts_code"] == "510300.SH"].sort_values("trade_date")
x = e[(e["trade_date"] >= "20250102") & (e["trade_date"] <= "20261023")]
if len(x):
    nav = x["close"].iloc[-1] / x["close"].iloc[0]
    print(f"510300 实际: {x['trade_date'].iloc[0]}~{x['trade_date'].iloc[-1]} 天数 {len(x)} "
          f"累计 {(nav-1)*100:.2f}% 年化 {(nav**(250/len(x))-1)*100:.2f}%")

sev = json.loads((ROOT / "data" / "sealed_eval.json").read_text(encoding="utf-8"))
print("sealed_eval benchmark_510300_bh:", sev.get("benchmark_510300_bh"))

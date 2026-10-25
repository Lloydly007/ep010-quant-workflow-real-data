r"""验证修正后的涨跌停价是否真的进了引擎面板。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

# 从落盘文件里挑一个 20% 档、且当日涨跌幅超过 10% 的样本
lim = pd.read_parquet(ROOT / "data" / "raw" / "stk_limit.parquet")
d = pd.read_parquet(ROOT / "data" / "raw" / "daily.parquet",
                    columns=["ts_code", "trade_date", "pre_close", "close", "open"])
m = lim.merge(d, on=["ts_code", "trade_date"])
m["move"] = m["close"] / m["pre_close"] - 1
pick = m[(m["band"] == 0.20) & (m["move"].abs() > 0.10)].tail(3)
print("落盘样本（20% 档且当日涨跌>10%）:")
print(pick[["ts_code", "trade_date", "pre_close", "close", "up_limit", "down_limit", "band"]]
      .to_string(index=False))

import panel_store  # noqa: E402

store = panel_store.real_store(quiet=True)
panel = store.panel
cols = [c for c in ("up_limit", "down_limit", "close", "pre_close", "open", "is_st") if c in panel.columns]
print("\n面板列检查:", cols)
for _, r in pick.iterrows():
    code = r["ts_code"]
    dt = r["trade_date"]
    sub = panel[(panel["code"] == code) & (panel["date"].astype(str) == str(dt))]
    if not len(sub):
        print(f"  {code} {dt}: 面板里找不到")
        continue
    row = sub.iloc[0]
    print(f"  {code} {dt}: 面板 up={row['up_limit']:.2f} down={row['down_limit']:.2f} "
          f"| 落盘 up={r['up_limit']:.2f} down={r['down_limit']:.2f} "
          f"| pre_close={r['pre_close']:.2f} 期望 20% 档 up={r['pre_close']*1.2:.2f}")

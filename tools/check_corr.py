r"""三席相关性：封存期日收益两两相关（判断是不是三条独立收益来源）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "reports" / "runs"
AI = ["a_r6_s3_03_dose030_u250_t120", "a_r6_s3_06_dose045_u250_t120", "b_r5_s2_30_ulcer_extra_1to2"]
RND = ["m43_046", "m43_050", "m43_084"]


def rets(name: str) -> pd.Series | None:
    p = RUN / f"{name}__20250101_20260930" / "daily_returns.csv"
    if not p.exists():
        return None
    d = pd.read_csv(p)
    return pd.Series(d["strategy_ret"].to_numpy(), index=d["date"].astype(str), name=name)


for label, names in (("AI 三席", AI), ("随机三席", RND)):
    cols = [r for r in (rets(n) for n in names) if r is not None]
    if len(cols) < 2:
        continue
    df = pd.concat(cols, axis=1).dropna()
    print(f"\n=== {label}：封存期日收益相关矩阵（{len(df)} 个交易日）===")
    print(df.corr().round(3).to_string())
    c = df.corr().to_numpy()
    pair = [c[i][j] for i in range(len(c)) for j in range(i + 1, len(c))]
    print(f"两两相关：{', '.join(f'{v:.3f}' for v in pair)}")

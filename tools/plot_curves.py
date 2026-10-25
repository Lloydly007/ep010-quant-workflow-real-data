r"""画回测曲线：封存期对照 + 全周期（搜索/验证/封存三段拼接）。

数据来源：reports/runs/<config>__<start>_<end>/daily_returns.csv
（引擎已经写好 strategy_nav / benchmark_nav，直接读，不重算）

输出：reports/figures/fig1_sealed.png、fig2_full.png、fig3_allocation.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "reports" / "runs"
FIG = ROOT / "reports" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

AI = ["a_r6_s3_03_dose030_u250_t120", "a_r6_s3_06_dose045_u250_t120", "b_r5_s2_30_ulcer_extra_1to2"]
RND = ["m43_046", "m43_050", "m43_084"]
PERIODS = [("20140101", "20221231"), ("20230101", "20241231"), ("20250101", "20260930")]
SPLIT1, SPLIT2 = "20221231", "20241231"


def load(name: str, start: str, end: str) -> pd.DataFrame | None:
    p = RUNS / f"{name}__{start}_{end}" / "daily_returns.csv"
    if not p.exists():
        return None
    d = pd.read_csv(p)
    d["date"] = pd.to_datetime(d["date"].astype(str), format="%Y%m%d")
    return d.set_index("date")


def stitched(name: str) -> pd.DataFrame:
    """三段各自以段首归 1，再按段连乘，拼成一条连续净值。"""
    frames = []
    for s, e in PERIODS:
        d = load(name, s, e)
        if d is None or not len(d):
            continue
        for col in ("strategy_nav", "benchmark_nav"):
            if col in d.columns:
                d[col] = d[col] / d[col].iloc[0]
        frames.append(d)
    if not frames:
        return pd.DataFrame()

    series = {}
    for col in ("strategy_nav", "benchmark_nav"):
        acc, parts = 1.0, []
        for d in frames:
            if col not in d.columns:
                continue
            rel = d[col] * acc
            parts.append(rel)
            acc = float(rel.iloc[-1])
        if parts:
            series[col] = pd.concat(parts)
    return pd.DataFrame(series)


def stats(d: pd.DataFrame, col: str = "strategy_nav") -> str:
    """年化按 250 个交易日（与引擎口径一致，不用 365 日历日）。"""
    nav = d[col].dropna()
    if len(nav) < 20:
        return ""
    ann = nav.iloc[-1] ** (250.0 / len(nav)) - 1
    dd = (nav / nav.cummax() - 1).min()
    return f"年化 {ann*100:+.1f}%  回撤 {dd*100:.1f}%"


def main() -> int:
    # ---------------- 图 1：封存期
    fig, ax = plt.subplots(figsize=(12, 6))
    bench = None
    for name in AI:
        d = load(name, *PERIODS[2])
        if d is None:
            continue
        bench = d["benchmark_nav"] / d["benchmark_nav"].iloc[0]
        ax.plot(d.index, d["strategy_nav"] / d["strategy_nav"].iloc[0],
                lw=2.0, label=f"AI {name[:22]}  {stats(d)}")
    for name in RND:
        d = load(name, *PERIODS[2])
        if d is None:
            continue
        ax.plot(d.index, d["strategy_nav"] / d["strategy_nav"].iloc[0],
                lw=1.4, ls="--", label=f"随机 {name}  {stats(d)}")
    if bench is not None:
        ax.plot(bench.index, bench, lw=2.4, color="black", alpha=0.55,
                label=f"股票池等权基准  {stats(pd.DataFrame({'strategy_nav': bench}))}")
    ax.axhline(1.0, color="gray", lw=0.8)
    ax.set_title("封存期（2025-01-02 ~ 2026-09-30）：AI 三席 vs 随机三席", fontsize=14)
    ax.set_ylabel("净值（起点=1）")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8.5, loc="upper left")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG / "fig1_sealed.png", dpi=150)
    plt.close(fig)

    # ---------------- 图 2：全周期三段拼接
    fig, ax = plt.subplots(figsize=(13, 6))
    for name in AI:
        d = stitched(name)
        if d.empty:
            continue
        ax.plot(d.index, d["strategy_nav"], lw=1.8, label=f"{name[:26]}  {stats(d)}")
    d0 = stitched(AI[0])
    if not d0.empty:
        ax.plot(d0.index, d0["benchmark_nav"], lw=2.2, color="black", alpha=0.5,
                label=f"股票池等权基准  {stats(d0, 'benchmark_nav')}")
    for x in (pd.Timestamp(SPLIT1), pd.Timestamp(SPLIT2)):
        ax.axvline(x, color="crimson", lw=1.2, ls=":")
    for x, label in ((pd.Timestamp("20170401"), "搜索期 2014–2022"),
                     (pd.Timestamp("20230401"), "验证期 2023–2024"),
                     (pd.Timestamp("20250401"), "封存期 2025–2026")):
        ax.text(x, 0.94, label, fontsize=11, color="crimson",
                transform=ax.get_xaxis_transform(), ha="left")
    ax.set_title("AI 三席全周期净值（三段拼接，每段以段首归 1 后连乘）", fontsize=14)
    ax.set_ylabel("净值（起点=1）")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9, loc="lower right")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG / "fig2_full.png", dpi=150)
    plt.close(fig)

    # ---------------- 图 3：三席等权 vs 组合（封存期）
    fig, ax = plt.subplots(figsize=(12, 6))
    navs = {}
    for name in AI:
        d = load(name, *PERIODS[2])
        if d is not None:
            navs[name] = d["strategy_nav"] / d["strategy_nav"].iloc[0]
    if navs:
        eq = pd.concat(navs.values(), axis=1).mean(axis=1)
        ax.plot(eq.index, eq, lw=2.6, color="darkgreen", label=f"三席等权  {stats(pd.DataFrame({'strategy_nav': eq}))}")
        for name, nav in navs.items():
            ax.plot(nav.index, nav, lw=1.0, alpha=0.55, label=name[:24])
        b = load(AI[0], *PERIODS[2])
        if b is not None:
            bn = b["benchmark_nav"] / b["benchmark_nav"].iloc[0]
            ax.plot(bn.index, bn, lw=2.2, color="black", alpha=0.5,
                    label=f"股票池等权  {stats(pd.DataFrame({'strategy_nav': bn}))}")
    ax.axhline(1.0, color="gray", lw=0.8)
    ax.set_title("封存期：三席等权卫星组合 vs 基准", fontsize=14)
    ax.set_ylabel("净值（起点=1）")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG / "fig3_allocation.png", dpi=150)
    plt.close(fig)

    for f in ("fig1_sealed.png", "fig2_full.png", "fig3_allocation.png"):
        p = FIG / f
        print(f"[fig] {p}  {p.stat().st_size/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

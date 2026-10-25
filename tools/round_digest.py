# -*- coding: utf-8 -*-
"""tools/round_digest.py —— 给下一轮搜索 agent 的「台账摘要」（口径固定，避免父级转述失真）

输出一小段 Markdown：分组计数、L1~L4 分布、按 IR 的前 N 条、零成交配置清单、
零件使用覆盖。搜索 agent 读这一段就能知道上一轮发生了什么，不必自己翻 1000 行台账。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/round_digest.py --groups A B --top 12
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ledger" / "ledger.csv"
NUM = ["n_trades", "ann_excess", "ir", "excess_max_dd", "beat_years", "total_years",
       "icir", "turnover_ann"]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="台账摘要（给下一轮 agent）")
    ap.add_argument("--groups", nargs="*", default=["A", "B"])
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args(argv)

    led = pd.read_csv(LEDGER, dtype=str, keep_default_na=False)
    for c in NUM:
        if c in led.columns:
            led[c] = pd.to_numeric(led[c], errors="coerce")
    led = led[led["start"] == "20140101"]
    led = led.drop_duplicates(["config", "group"], keep="last")

    path = ROOT / "strategies"
    out = [f"## 台账摘要（搜索期 2014-2022，截至本次读取：{len(led)} 条基础执行）", ""]
    for g in a.groups:
        sub = led[led["group"] == g]
        if not len(sub):
            continue
        l = {k: int((sub[f"funnel_l{k}"] == "1").sum()) for k in (1, 2, 3, 4)}
        zero = sub[sub["n_trades"] == 0]["config"].tolist()
        out.append(f"### {g} 组：{len(sub)} 个配置；L1 {l[1]} / L2 {l[2]} / L3 {l[3]} / L4 {l[4]} 通过")
        top = sub.dropna(subset=["ir"]).sort_values("ir", ascending=False).head(a.top)
        out.append("")
        out.append("| 配置 | 类型 | 交易数 | 年化超额 | IR | 超额回撤 | 年度为正 | L1~L4 |")
        out.append("|---|---|---|---|---|---|---|---|")
        for r in top.itertuples(index=False):
            lay = "".join(str(int(getattr(r, f"funnel_l{k}"))) for k in (1, 2, 3, 4))
            out.append(f"| {r.config} | {r.type} | {int(r.n_trades)} | "
                       f"{r.ann_excess:+.2%} | {r.ir:+.2f} | "
                       f"{r.excess_max_dd:+.1%} | {int(r.beat_years)}/{int(r.total_years)} | {lay} |")
        if zero:
            out.append("")
            out.append(f"零成交（条件在这份数据上不可达，别再重复问）：{len(zero)} 个 —— "
                       + "、".join(zero[:14]) + ("…" if len(zero) > 14 else ""))
        out.append("")

    # 零件覆盖（只统计在册配置）
    ops_used: dict[str, int] = {}
    n_cfg = 0
    for p in path.rglob("*.yaml"):
        if "__" in p.stem:
            continue
        n_cfg += 1
        txt = p.read_text(encoding="utf-8", errors="replace")
        for op in ("ret_n", "ma_n", "close_over_ma_n", "dist_high_n", "dist_low_n",
                   "close_pos_range", "vol_ratio_n", "turn", "turn_ma_n", "vol_n",
                   "atr_close_n", "streak_up", "streak_down", "break_high_n",
                   "etf_above_ma_n", "size_ln", "pe_ttm", "pb", "ps_ttm", "roe",
                   "or_yoy", "netprofit_yoy", "fc_type_code", "fc_chg_mid", "fc_days",
                   "ex_yoy", "ex_days", "ts_pct", "xsec_pct", "ind_rank",
                   "top_list_n", "inst_netbuy", "margin_ratio", "margin_chg_n",
                   "hk_ratio", "hk_chg_n", "ind_median_pb", "ind_median_ps",
                   "ind_median_fc_chg_mid", "fc_demean_ind", "ulcer_n"):
            if f"op: {op}" in txt:
                ops_used[op] = ops_used.get(op, 0) + 1
    out.append(f"## 零件覆盖（{n_cfg} 个在册配置）")
    out.append("")
    out.append("| 零件 | 配置数 | | 零件 | 配置数 |")
    out.append("|---|---|---|---|---|")
    items = sorted(ops_used.items(), key=lambda kv: -kv[1])
    for i in range(0, len(items) - len(items) % 2, 2):
        (k1, v1), (k2, v2) = items[i], items[i + 1]
        out.append(f"| {k1} | {v1} | | {k2} | {v2} |")
    if len(items) % 2:
        out.append(f"| {items[-1][0]} | {items[-1][1]} | | | |")
    unused = [op for op in ("top_list_n", "inst_netbuy", "margin_ratio", "margin_chg_n",
                            "hk_ratio", "hk_chg_n", "ind_rank", "ind_median_pb",
                            "ind_median_ps", "ind_median_fc_chg_mid", "fc_demean_ind",
                            "ulcer_n", "atr_close_n", "size_ln", "or_yoy") if op not in ops_used]
    out.append("")
    out.append("**从没被用过的零件**：" + ("、".join(unused) if unused else "无"))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

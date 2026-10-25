# -*- coding: utf-8 -*-
"""tools/style_check.py —— 风格体检（rules.md 第 13 章），对**入围对象**执行

缺口背景：引擎的 `funnel.py style --all` 只覆盖 `final`（过全部八层）的幸存者；
本次研究 final=0，所以风格体检完全没出数——但手册第 5 步第 4 条要求对**入围策略**
做风格体检。本脚本补上这一环，不改引擎的判定口径。

口径（照 rules.md 第 13 章）：
  * 持仓口径：每个调仓日（信号日 T）分别算行业权重，再对各调仓日取平均；
    权重 = 该股在 T 日的持仓市值 ÷ 全部持仓市值；持仓由 `trades.parquet` 的
    buy/sell 份额累计重建，市值用引擎面板的 adj_nav（= close × adj_factor）。
  * 成交口径：按买入金额汇总申万一级行业分布（全期占比）。
  * 交叉核对：两种口径逐行业比较，最大差异 > 15 个百分点要在报告里点名（未核清
    前不出结论性数字）。
  * 行业归属按 `index_member_all` 的 in_date ≤ T < out_date 判定（时点正确）。

产出：`reports/style_check.md` + `data/style_check.json`（每配置一行小表 + 行业明细）。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/style_check.py [--configs a,b,c] [--shortlist data/shortlist_AI.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import guard  # noqa: E402  必须先于 numpy/pandas

import prices  # noqa: E402

RUNS = ROOT / "reports" / "runs"
DATA = ROOT / "data"
DIFF_LIMIT_PP = 15.0        # rules.md 第 13 章：> 15 个百分点先查原因


def industry_map(ind: pd.DataFrame) -> dict[str, list[tuple[str, str, str]]]:
    """{code: [(in_date, out_date, l1_name), ...]}，out_date 空 → '99999999'。"""
    out: dict[str, list[tuple[str, str, str]]] = {}
    df = ind.copy()
    df["in_date"] = df["in_date"].astype("string").str.replace("-", "", regex=False).str.slice(0, 8)
    df["out_date"] = (df["out_date"].astype("string").str.replace("-", "", regex=False)
                      .str.slice(0, 8).fillna("").replace("", "99999999"))
    for code, g in df.groupby("ts_code", sort=False):
        out[str(code)] = [(str(i), str(o), str(n)) for i, o, n in
                          zip(g["in_date"], g["out_date"], g["l1_name"])]
    return out


def industry_on(imap: dict, code: str, date: str) -> str | None:
    recs = imap.get(code)
    if not recs:
        return None
    hit = None
    for i, o, name in recs:                       # 区间表：取命中的最后一条
        if i <= date < o:
            hit = name
    return hit


def holdings_by_industry(trades: pd.DataFrame, nav: dict, imap: dict
                         ) -> tuple[pd.DataFrame, list[str]]:
    """每个调仓日（signal_date）的行业权重矩阵（行=日期，列=行业）。"""
    rows, dates = [], []
    pos: dict[str, float] = {}
    tr = trades.sort_values(["exec_date", "code"], kind="stable")
    by_exec = dict(tuple(tr.groupby("exec_date", sort=True)))
    for signal in sorted(trades["signal_date"].unique()):
        # T 日持仓 = exec_date <= T 已经成交的全部买卖
        for d in [x for x in by_exec if x <= signal]:
            for r in by_exec.pop(d).itertuples(index=False):
                if r.side == "buy":
                    pos[r.code] = pos.get(r.code, 0.0) + float(r.shares)
                else:
                    pos[r.code] = pos.get(r.code, 0.0) - float(r.shares)
        vals = {c: s * nav.get((c, signal), np.nan) for c, s in pos.items() if s > 0}
        tot = float(np.nansum(list(vals.values())))
        if not np.isfinite(tot) or tot <= 0:
            continue
        w: dict[str, float] = {}
        for c, v in vals.items():
            if not np.isfinite(v):
                continue
            ind = industry_on(imap, c, signal) or "（无行业归属）"
            w[ind] = w.get(ind, 0.0) + v / tot
        rows.append(w)
        dates.append(signal)
    return pd.DataFrame(rows).fillna(0.0), dates


def one_config(name: str, store, imap: dict) -> dict | None:
    run = RUNS / f"{name}__20140101_20221231"
    if not (run / "trades.parquet").is_file():
        return None
    trades = pd.read_parquet(run / "trades.parquet")
    if trades.empty:
        return {"config": name, "available": False, "note": "0 笔成交，无法体检"}
    panel = store.panel
    nav = {(str(c), str(d)): float(v) for c, d, v in
           zip(panel["code"], panel["date"], panel["adj_nav"])}
    hold, dates = holdings_by_industry(trades, nav, imap)
    if hold.empty:
        return {"config": name, "available": False, "note": "调仓日无法重建持仓"}
    avg = hold.mean(axis=0).sort_values(ascending=False)

    buys = trades[trades["side"] == "buy"].copy()
    buys["ind"] = [industry_on(imap, str(c), str(d)) or "（无行业归属）"
                   for c, d in zip(buys["code"], buys["exec_date"])]
    trade_w = (buys.groupby("ind")["gross"].sum() / buys["gross"].sum()).sort_values(ascending=False)

    inds = sorted(set(avg.index) | set(trade_w.index))
    diffs = {i: (avg.get(i, 0.0) - trade_w.get(i, 0.0)) * 100.0 for i in inds}
    worst = max(diffs.items(), key=lambda kv: abs(kv[1]))
    hhi = float((avg ** 2).sum())
    return {
        "config": name, "available": True, "n_rebalances": len(dates),
        "n_trades": int(len(trades)),
        "hhi": round(hhi, 4),
        "max_industry": avg.index[0], "max_industry_weight": round(float(avg.iloc[0]) * 100, 2),
        "top3": [(i, round(float(w) * 100, 2)) for i, w in avg.head(3).items()],
        "trade_share_top3": [(i, round(float(w) * 100, 2)) for i, w in trade_w.head(3).items()],
        "max_diff_pp": round(worst[1], 2), "max_diff_industry": worst[0],
        "cross_check": "OK" if abs(worst[1]) <= DIFF_LIMIT_PP else "超 15pp，需先查明",
        "industry_weights_hold_pct": {i: round(float(avg[i]) * 100, 2) for i in avg.index},
        "industry_weights_trade_pct": {i: round(float(trade_w[i]) * 100, 2) for i in trade_w.index},
    }


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="入围对象风格体检（rules.md 第 13 章）")
    ap.add_argument("--configs", default="", help="逗号分隔的配置名")
    ap.add_argument("--shortlist", action="append", default=None,
                    help="从 shortlist JSON 取名，可多次给（默认两组的 shortlist）")
    a = ap.parse_args(argv)

    names: list[str] = [c for c in a.configs.split(",") if c]
    for sl in (a.shortlist or ["data/shortlist_AI.json", "data/shortlist_monkey_43.json"]):
        p = ROOT / sl
        if p.exists():
            names += json.loads(p.read_text(encoding="utf-8")).get("shortlist", [])
    names = list(dict.fromkeys(names))
    if not names:
        print("[style] 没有可体检的配置名")
        return 2

    ind = guard.read_parquet("data/raw/index_member_all.parquet")
    imap = industry_map(ind)
    store = prices.DataStore(quiet=True)
    rows = [one_config(n, store, imap) for n in names]
    rows = [r for r in rows if r]
    ok = [r for r in rows if r.get("available")]

    md = ["# 风格体检（rules.md 第 13 章，对入围对象）", ""]
    md.append("引擎自带的 `funnel.py style --all` 只覆盖 `final` 幸存者；本次 final=0，"
              "所以这一环由本脚本按同一章口径补上，判定口径未改。")
    md.append("")
    md.append("| 配置 | 调仓日数 | 交易笔数 | 行业 HHI | 最大单一行业（权重） | 持仓 vs 成交最大差 | 交叉核对 |")
    md.append("|---|---|---|---|---|---|---|")
    for r in rows:
        if not r.get("available"):
            md.append(f"| {r['config']} | — | — | — | — | — | {r.get('note', '不可用')} |")
            continue
        md.append(f"| {r['config']} | {r['n_rebalances']} | {r['n_trades']} | {r['hhi']} | "
                  f"{r['max_industry']}（{r['max_industry_weight']}%） | "
                  f"{r['max_diff_industry']} {r['max_diff_pp']:+.1f}pp | {r['cross_check']} |")
    md.append("")
    for r in ok:
        md.append(f"## {r['config']}")
        md.append("")
        md.append(f"- 持仓口径前三大行业：" + "、".join(f"{i} {w}%" for i, w in r["top3"]))
        md.append(f"- 成交口径前三大行业：" + "、".join(f"{i} {w}%" for i, w in r["trade_share_top3"]))
        md.append(f"- 行业 HHI = {r['hhi']}（越低越分散）；最大单一行业权重 "
                  f"{r['max_industry_weight']}%")
        md.append(f"- 两种口径最大差异：{r['max_diff_industry']} {r['max_diff_pp']:+.1f} 个百分点"
                  f"（阈值 ±{DIFF_LIMIT_PP:.0f}pp，{r['cross_check']}）")
        md.append("")
    md.append("## 口径与局限")
    md.append("")
    md.append("- 持仓由 `trades.parquet` 的买卖份额累计重建，市值用引擎面板的 `adj_nav`；"
              "调仓日取信号日 T（T 日收盘出信号、T+1 开盘成交）。")
    md.append("- 行业归属按 `index_member_all` 的 in_date ≤ T < out_date 时点判定；"
              "无归属的股票单列「（无行业归属）」，不并入其他行业。")
    md.append("- 本体检只报告风格暴露，不改变任何筛选结论（rules.md 第 13 章）。")
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "style_check.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (DATA / "style_check.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[style] 体检 {len(ok)}/{len(rows)} 个配置；写出 reports/style_check.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

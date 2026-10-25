# -*- coding: utf-8 -*-
"""tools/sealed_eval.py —— 第 7 步开封评估（复刻用的胶水脚本，不改动引擎）

背景：EP010 原始工程**故意不提供**开封命令（docs/CLI.md:41「不在此处提供自动
开封命令」），第 7 步要人工按提示词执行。本脚本把手册第 7 步的六项动作固化成
一条可复跑的命令，仍然遵守原始纪律：

  1. 必须存在 OPEN_SEALED 标记（engine/guard.py 强制；没有标记连 2025+ 的区间
     都过不去），脚本自己**不会**创建标记；
  2. 六个入围对象（AI 3 + monkey_43 3）**只跑一次**：若已存在
     reports/runs/<配置>__20250101_* 目录，默认直接报错退出，不重跑；
  3. 组合层复用 engine/portfolio.run_portfolio（其中封存段要求「run 目录恰好
     1 个」，这是引擎对「只跑一次」的机器强制）；
  4. 第 14 章指标：引擎只在「区间 ⊆ 搜索期」时挂载（backtest._attach_ch14），
     封存期按 rules.md 14.4「封存期同名指标仅在开封后计算」在这里显式补算，
     用的是引擎自己的 _ch14_compute，口径与搜索期一致。

产出：
  data/sealed_eval.json            机器可读的全部封存期结果
  reports/sealed_result.md         手册第 7 步第 5 条要求的报告

用法（先建标记，跑完删标记）：
    New-Item OPEN_SEALED
    .venv\\Scripts\\python.exe -X utf8 tools/sealed_eval.py
    Remove-Item OPEN_SEALED
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

import guard  # noqa: E402  必须先于 numpy/pandas（钉死 BLAS 线程）

import panel_store  # noqa: E402
from backtest import (_ch14_compute, _ch14_sanitize,  # noqa: E402
                      annualized_return, max_drawdown, run_backtest)
from config import load_config  # noqa: E402
from funnel import group_of_config, read_ledger  # noqa: E402
from portfolio import render_md, run_portfolio  # noqa: E402
from prices import ETF_BENCHMARK  # noqa: E402

SEALED_START, SEALED_END = "20250101", "20260930"      # 研究截止日同 fetch_tushare.py:41
RUNS = ROOT / "reports" / "runs"
DATA = ROOT / "data"
REPORTS = ROOT / "reports"


def _cfg_path(name: str) -> Path | None:
    for p in (ROOT / "strategies").rglob(f"{name}.yaml"):
        return p
    return None


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="第 7 步开封评估（只跑一次）")
    ap.add_argument("--allow-rerun", action="store_true",
                    help="已存在封存 run 目录时仍继续（默认拒绝，遵守「只跑一次」）")
    a = ap.parse_args(argv)

    if not guard.OPEN_SEALED_MARKER.is_file():
        print("[sealed] 拒绝执行：项目根目录没有 OPEN_SEALED（rules.md 第 1 节）")
        return 2

    groups = [("AI", DATA / "shortlist_AI.json"), ("monkey_43", DATA / "shortlist_monkey_43.json")]
    existing = {g: (json.loads(p.read_text(encoding="utf-8"))["shortlist"] if p.exists() else [])
                for g, p in groups}
    names_all = [n for _, ps in existing.items() for n in ps]
    if not names_all:
        print("[sealed] 拒绝执行：data/shortlist_AI.json / shortlist_monkey_43.json 不存在或为空")
        return 2

    done = [n for n in names_all if list(RUNS.glob(f"{n}__{SEALED_START}_*"))]
    if done and not a.allow_rerun:
        print(f"[sealed] 拒绝执行：以下配置已有封存 run 目录（只跑一次）：{done}")
        print("         确实要重跑请加 --allow-rerun（会写入新台账行，违反第 7 步纪律）")
        return 2

    ledger = read_ledger()
    store = panel_store.real_store()          # 必须在 OPEN_SEALED 之后构建才并入 sealed
    print(f"[sealed] 面板：{len(store.codes)} 只股票、交易日 {len(store.calendar)} 天"
          f"（含封存期；OPEN_SEALED 存在）")

    out: dict = {"generated_at": None, "sealed_window": [SEALED_START, SEALED_END],
                 "marker_required": "OPEN_SEALED", "groups": {}}
    for group, sl_path in groups:
        names = json.loads(sl_path.read_text(encoding="utf-8"))["shortlist"]
        print(f"\n[sealed] === {group}：{len(names)} 个入围对象 ===")
        per = {}
        for name in names:
            cfg = _cfg_path(name)
            if cfg is None:
                print(f"  {name}: 找不到 YAML，跳过")
                per[name] = {"available": False, "note": "找不到同名 YAML"}
                continue
            res = run_backtest(store, cfg, SEALED_START, SEALED_END,
                               group=group_of_config(ledger, name), quiet=True)
            ch14 = _ch14_compute(store, res, load_config(cfg))   # 封存期补算（rules 14.4）
            per[name] = {
                "available": True,
                "ann_ret": res["ann_ret"], "bench_ann_ret": res["bench_ann_ret"],
                "ann_excess": res["ann_excess"], "ir": res["ir"],
                "excess_max_dd": res["excess_max_dd"],
                "max_dd": res["max_dd"], "n_trades": res["n_trades"],
                "ch14": _ch14_sanitize(ch14["metrics"]),
            }
            print(f"  {name}: 年化 {res['ann_ret']:+.2%} 基准 {res['bench_ann_ret']:+.2%} "
                  f"超额 {res['ann_excess']:+.2%} IR {res['ir']:+.2f}")

        port = run_portfolio(names, group, store=store)
        (DATA / f"portfolio_sealed_{group}.json").write_text(
            json.dumps(port, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (REPORTS / f"portfolio_sealed_{group}.md").write_text(render_md(port), encoding="utf-8")
        sealed = port["periods"].get("sealed", {})
        print(f"  组合（60/40）封存期：{sealed.get('portfolio', {})}")
        out["groups"][group] = {"candidates": per, "portfolio": port["periods"],
                                "portfolio_md": f"reports/portfolio_sealed_{group}.md"}

    # 基准②：沪深300 ETF 买入持有（基准①「股票池等权」在每次回测的
    # daily_returns.csv → benchmark_ret 列里，逐策略已给出）
    etf = store.etfs[ETF_BENCHMARK].set_index("date")["ret"].astype(float)
    sub = etf[(etf.index >= SEALED_START) & (etf.index <= SEALED_END)]
    out["benchmark_510300_bh"] = {"from": str(sub.index.min()), "to": str(sub.index.max()),
                                  "ann_ret": float(annualized_return(list(sub))),
                                  "max_dd": float(max_drawdown(list(sub)))}
    print(f"\n[sealed] 基准 510300 买入持有：年化 {out['benchmark_510300_bh']['ann_ret']:+.2%} "
          f"最大回撤 {out['benchmark_510300_bh']['max_dd']:+.2%}")

    (DATA / "sealed_eval.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (REPORTS / "sealed_result.md").write_text(render_sealed_md(out), encoding="utf-8")
    print("[sealed] 写出 data/sealed_eval.json、reports/sealed_result.md")
    return 0


def render_sealed_md(out: dict) -> str:
    """把 sealed_eval.json 渲染成手册第 7 步第 5 条要求的报告。"""
    lines = ["# 封存期评估（第 7 步，开封后只跑一次）", ""]
    lines.append(f"- 封存区间：{out['sealed_window'][0]} ~ {out['sealed_window'][1]}"
                 "（研究截止日 2026-09-30，rules.md 第 1 节）")
    lines.append("- 开封纪律：先提交入围名单与组合规则 → 创建 OPEN_SEALED → 每个对象只跑一次 → "
                 "删除 OPEN_SEALED。本报告的数字不因结果好坏而调整参数或重跑。")
    lines.append("- **本次为合成行情（`tools/gen_synthetic_data.py`），不是 Tushare 真实数据**；"
                 "结论只能证明流程可跑通，不能当作 A 股实证。")
    lines.append("")
    b = out.get("benchmark_510300_bh", {})
    lines.append(f"基准②：沪深300 ETF（510300.SH）买入持有 {b.get('from','')}~{b.get('to','')}："
                 f"年化 {b.get('ann_ret', float('nan')):+.2%}、最大回撤 {b.get('max_dd', float('nan')):+.2%}")
    lines.append("")
    for group, g in out["groups"].items():
        lines.append(f"## {group} 组")
        lines.append("")
        lines.append("| 配置 | 年化 | 基准年化 | 年化超额 | IR | 绝对最大回撤 | 超额最大回撤 | 交易笔数 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for name, c in g["candidates"].items():
            if not c.get("available"):
                lines.append(f"| {name} | 不可用 | | | | | | {c.get('note', '')} |")
                continue
            lines.append(f"| {name} | {c['ann_ret']:+.2%} | {c['bench_ann_ret']:+.2%} | "
                         f"{c['ann_excess']:+.2%} | {c['ir']:+.2f} | {c['max_dd']:+.2%} | "
                         f"{c['excess_max_dd']:+.2%} | {c['n_trades']} |")
        lines.append("")
        sealed = g["portfolio"].get("sealed", {})
        if sealed.get("available"):
            p = sealed["portfolio"]
            lines.append(f"组合（底仓 60% + 卫星 40%，{sealed['from']}~{sealed['to']}，"
                         f"{sealed['n_days']} 个交易日）：")
            lines.append("")
            lines.append(f"- 组合年化 {p['ann_ret']:+.2%}、绝对最大回撤 {p['max_dd']:+.2%}")
            lines.append(f"- 相对 510300 买入持有年化差 {p['ann_excess_vs_510300_bh']:+.2%}、"
                         f"超额最大回撤 {p['excess_max_dd']:+.2%}")
            lines.append(f"- 底仓回撤 < 25% 检验：{'通过' if p['check_mdd_lt_25pct'] else '不通过'}"
                         "（检验项，不是换名单的依据）")
            lines.append(f"- 仅底仓：年化 {sealed['base_only']['ann_ret']:+.2%}、"
                         f"回撤 {sealed['base_only']['max_dd']:+.2%}；"
                         f"仅卫星：年化 {sealed['satellite_only']['ann_ret']:+.2%}")
        else:
            lines.append(f"组合封存段不可用：{sealed.get('note', '未计算')}")
        lines.append("")
    lines.append("## 计算边界")
    lines.append("")
    lines.append("- 封存期第 14 章指标由 `tools/sealed_eval.py` 用引擎 `_ch14_compute` 补算，"
                 "口径与搜索期一致（rules.md 14.4）。")
    lines.append("- 计算、报告与失败数量分别记录；资源错误不当筛选失败，也不会用 0 顶替缺失。")
    lines.append("- 组合最大回撤 < 25% 是检验项，不是筛选或换名单的依据（rules.md 5.5）。")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())

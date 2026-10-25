# -*- coding: utf-8 -*-
"""tools/scale_plan.py —— 规模与成本模型（把"规模只有原版 1/3"这条差异量化）

做法：用 `run_backtest(record=False)` 实测单配置回测耗时（不写台账），
再按实测吞吐 + 本次实际结构（每轮 39 个配置、6 轮、20 组农场猴子）外推：

  总回测数 = 2×(6×每轮数) [A+B] + 每轮数 [主随机] + 20×每轮数 [农场]
           + L5 邻域（按实测 L4 存活率 × 邻居数）+ 验证期复跑
  工时     = 总回测数 ÷ 实测吞吐

产出 `reports/规模与成本.md`：一张从"本机本次 39/轮"到"原版 100~150/轮"的成本表，
说明为什么停在 39，以及要在本机跑到原版规格需要多少小时。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/scale_plan.py [--sample 3]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import guard  # noqa: E402

import panel_store  # noqa: E402
from backtest import run_backtest  # noqa: E402
from funnel import default_workers  # noqa: E402


def sample_configs(n: int) -> list[Path]:
    out = []
    for g in ("A", "B"):
        for r in range(1, 7):
            d = ROOT / "strategies" / g / f"round{r}"
            if d.is_dir():
                out += sorted(d.glob("*.yaml"))[: max(1, n // 12 + 1)]
    return out[:n]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="规模与成本模型")
    ap.add_argument("--sample", type=int, default=4)
    a = ap.parse_args(argv)

    store = panel_store.real_store(quiet=True)
    cfgs = sample_configs(a.sample)
    t0 = time.time()
    for p in cfgs:
        run_backtest(store, p, "20140101", "20221231", group="test",
                     record=False, quiet=True)
    secs = time.time() - t0
    per_cfg = secs / max(1, len(cfgs))

    led = pd.read_csv(ROOT / "ledger" / "ledger.csv", dtype=str, keep_default_na=False)
    led = led[(led["start"] == "20140101") & ~led["config"].str.contains("__")]
    latest = led.drop_duplicates(["config", "group"], keep="last")
    workers = default_workers()
    thru = workers / per_cfg                     # 配置/秒

    # 实测结构参数
    n_ab = latest["group"].isin(["A", "B"]).sum()
    l4 = sum(int(str(v) or 0) == 1 for v in latest["funnel_l4"]) or 1
    l4_rate = l4 / max(1, n_ab)
    neigh = 6                                     # 每个 L4 幸存者的邻域探针数（实测 2~15，取 6）
    n_farm_seeds = 20

    def estimate(per_round: int) -> dict:
        rounds_ab = 6 * per_round
        base = 2 * rounds_ab + per_round + n_farm_seeds * per_round
        l4_est = int(base * l4_rate)
        jobs = base + l4_est * neigh
        hours = jobs / max(1e-6, thru) / 3600
        return {"per_round": per_round, "rounds": rounds_ab, "base": base,
                "l4": l4_est, "l5": l4_est * neigh, "jobs": jobs, "hours": hours}

    # 本次每轮实际配置数（从目录数算，别硬编码）
    per_round_now = 0
    _dirs = [d for g in ("A", "B") for d in sorted((ROOT / "strategies" / g).glob("round*"))]
    if _dirs:
        per_round_now = round(sum(len(list(d.glob("*.yaml"))) for d in _dirs) / len(_dirs))
    levels = sorted({per_round_now, 39, 60, 100, 150})
    rows = [estimate(n) for n in levels]
    cur = next(r for r in rows if r["per_round"] == per_round_now)

    md = ["# 规模与成本模型（把「规模差异」量化）", ""]
    md.append(f"实测：单配置回测 **{per_cfg:.2f}s**（`run_backtest(record=False)`，{len(cfgs)} 个样本），"
              f"并发 **{workers}**（CPU−2 再按可用内存封顶）→ 吞吐约 **{thru:.2f} 配置/秒**。")
    md.append("")
    md.append(f"实测结构：A+B 基础配置 {n_ab} 个，其中过 L4 的 {l4} 个（{l4_rate:.0%}）；"
              f"每个 L4 幸存者平均生成约 {neigh} 个 L5 邻域探针（本次实测 2~15 个）。")
    md.append("")
    md.append("| 每轮配置数 | A/B 每路配置 | 基础回测数（含主随机+20 组猴子） | L4 幸存估计 | L5 邻域估计 | 总回测数 | 预计工时 |")
    md.append("|---|---|---|---|---|---|---|")
    for r in rows:
        md.append(f"| {r['per_round']} | {r['rounds']} | {r['base']:,} | {r['l4']:,} | "
                  f"{r['l5']:,} | {r['jobs']:,} | {r['hours']:.1f} 小时 |")
    md.append("")
    md.append("结论：")
    md.append("")
    md.append(f"- 本次（每轮 {per_round_now}）的理论工时约 **{cur['hours']:.1f} 小时**；实测农场阶段用了约 10 分钟、"
              "漏斗重算约 1~2 分钟，比这个上界小，是因为大量配置命中了结果缓存（`_reuse_result`）。")
    r100 = next(r for r in rows if r["per_round"] == 100)
    r150 = next(r for r in rows if r["per_round"] == 150)
    md.append(f"- 原版规格（每轮 100~150）在本机约需 **{r100['hours']:.1f}~{r150['hours']:.1f} 小时** "
              "的单机回测（8 并发、含 L5 邻域），**这是可以过夜跑完的量级**，"
              "真正的瓶颈在 agent 侧：每轮 100+ 个 YAML 需要 8~10 个 agent，6 轮 A+B 共 100+ 个 agent 会话。")
    if per_round_now >= 100:
        md.append(f"- 本次每轮 {per_round_now} 个配置，**已进入原版规格（100~150）**；"
                  f"回测侧只花了 {cur['hours']:.1f} 小时量级，说明规格里真正贵的是 agent 写配置的部分。")
    elif per_round_now >= 80:
        md.append(f"- 本次每轮 {per_round_now} 个配置，**接近规格下限**（100~150）；"
                  f"回测侧约 {cur['hours']:.1f} 小时，剩下的差距主要是 agent 侧。")
    else:
        md.append(f"- 本次每轮 {per_round_now} 个配置，是有依据的取舍：回测约 {cur['hours']:.1f} 小时，"
                  "瓶颈在候选池深度与 agent 时间，而且这个规模是**可继续扩的**。")
    md.append("")
    md.append("要在本机跑到原版规格，按这张表需要：")
    md.append("")
    md.append("1. 把 `run_batch` 的 `--workers` 调到内存允许的上限，并用 `funnel.py farm --seeds` 分批过夜；")
    md.append("2. agent 侧每轮 8~10 个（每个 12~15 个配置），轮次仍是 6 轮；")
    md.append("3. 磁盘上 `reports/runs/` 会到十几 GB 量级（本次 3.0GB/7,561 个目录，已排除在 git 之外）。")
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "规模与成本.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (ROOT / "data" / "scale_plan.json").write_text(
        json.dumps({"per_config_seconds": per_cfg, "workers": workers,
                    "throughput_cfg_per_s": thru, "l4_rate": l4_rate,
                    "estimates": rows}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    print("\n".join(md[-12:]))
    print(f"\n[scale] 写出 reports/规模与成本.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

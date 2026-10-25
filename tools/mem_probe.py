# -*- coding: utf-8 -*-
"""tools/mem_probe.py —— 内存剖析：定位 MemoryError 的峰值来自哪里

v2 的 `monkey_11` 有 98 条 `MemoryError`。P14 把并发按可用内存封顶、P15 让失败任务
能被单进程重试，但"峰值到底出在哪"一直没测。本脚本分四步量当前进程的 RSS：

  ① 基线（import 完引擎）            ② 载入共享面板（DataStore / panel_store）
  ③ 跑一个**交易数最多**的配置        ④ 跑一个交易数中位的配置

若 ③ 的增量远大于 ②，说明峰值来自单配置回测内部（成交明细/日收益/ch14 明细），
而不是面板本身——那对应两种不同修法（流式落盘 vs 限制并发）。

产出 `reports/内存剖析.md`。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/mem_probe.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def rss_mb() -> tuple[float, float]:
    """(当前 Python 堆, 峰值 Python 堆)，单位 MB（tracemalloc 口径）。

    走 tracemalloc 而不是 PSAPI：前者能直接指到 `文件:行`，后者只能给一个总数。
    """
    import tracemalloc
    if not tracemalloc.is_tracing():
        tracemalloc.start()
    cur, peak = tracemalloc.get_traced_memory()
    return cur / 2 ** 20, peak / 2 ** 20


def top_alloc(limit: int = 6) -> list[tuple[str, float]]:
    """当前堆里最大的几处分配（按 文件:行）。"""
    import tracemalloc
    if not tracemalloc.is_tracing():
        return []
    snap = tracemalloc.take_snapshot()
    out = []
    for st in snap.statistics("lineno")[:limit]:
        out.append((f"{st.traceback[0].filename.split(chr(92))[-1]}:{st.traceback[0].lineno}",
                    st.size / 2 ** 20))
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = []
    cur, peak = rss_mb()
    rows.append(("① 基线（引擎 import 完）", cur, peak))

    import panel_store                     # 载入面板（含 DataStore 构建）
    from backtest import run_backtest

    store = panel_store.real_store(quiet=True)
    cur, peak = rss_mb()
    rows.append(("② 载入面板（共享 memmap）", cur, peak))

    led = pd.read_csv(ROOT / "ledger" / "ledger.csv", dtype=str, keep_default_na=False)
    led = led[(led["start"] == "20140101") & (led["status"] == "ok")
              & ~led["config"].str.contains("__")].copy()
    led["n"] = pd.to_numeric(led["n_trades"], errors="coerce")
    led = led.dropna(subset=["n"]).drop_duplicates("config", keep="last")

    def run_one(name: str, tag: str):
        p = next((q for q in (ROOT / "strategies").rglob(f"{name}.yaml")), None)
        if p is None:
            rows.append((tag, float("nan"), float("nan")))
            return
        t0 = time.time()
        run_backtest(store, p, "20140101", "20221231", group="test", record=False, quiet=True)
        c, pk = rss_mb()
        rows.append((f"{tag}：{name}（{time.time()-t0:.1f}s）", c, pk))

    big = led.sort_values("n", ascending=False).iloc[0]
    mid = led.iloc[len(led) // 2]
    run_one(big["config"], f"③ 交易最多（{int(big['n'])} 笔）")
    run_one(mid["config"], f"④ 交易中位（{int(mid['n'])} 笔）")

    delta_panel = rows[1][2] - rows[0][2]
    delta_big = rows[2][2] - rows[1][2]
    alloc = top_alloc()
    md = ["# 内存剖析（MemoryError 的峰值在哪）", ""]
    md.append("| 阶段 | 当前 RSS (MB) | 进程峰值 (MB) |")
    md.append("|---|---|---|")
    for name, c, pk in rows:
        md.append(f"| {name} | {c:.0f} | {pk:.0f} |" if c == c else f"| {name} | — | — |")
    md.append("")
    md.append(f"- 面板增量：**{delta_panel:.0f} MB**；单配置（交易最多）增量：**{delta_big:.0f} MB**")
    if delta_big > delta_panel:
        md.append("- 结论：峰值主要来自**单配置回测内部**（成交明细 / 日收益 / 第 14 章明细），"
                  "不是面板。对应修法是让这些产物流式落盘，或对超大交易数配置降并发处理。")
    else:
        md.append("- 结论：峰值主要来自**面板副本**。对应修法是共享 memmap（已有）+ 按可用内存限并发（P14）。")
    md.append("")
    if alloc:
        md.append("当前堆里最大的分配（`文件:行`）：")
        md.append("")
        for site, mb in alloc:
            md.append(f"- `{site}` — {mb:.0f} MB")
        md.append("")
    md.append("并发建议：每 worker ≈ "
              f"{max(0.5, delta_panel / 1024):.1f}GB 面板 + {max(0.2, delta_big / 1024):.1f}GB 峰值，"
              "`funnel.WORKER_MEM_GB` 就按这个量级设（当前 2.5GB）。")
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "内存剖析.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (ROOT / "data" / "mem_probe.json").write_text(
        json.dumps({"stages": [{"stage": n, "rss_mb": c, "peak_mb": pk} for n, c, pk in rows],
                    "panel_delta_mb": delta_panel, "big_config_delta_mb": delta_big},
                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

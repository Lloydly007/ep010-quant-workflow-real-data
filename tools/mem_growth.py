r"""内存增长定位：同一进程连跑 N 份配置，逐份记录 RSS。

用途：农场跑长之后 worker 从 4GB 涨到 7GB+，4 个 worker 就把 22GB 吃光。
本脚本回答两个问题：
  1. 每份配置到底留下多少内存（斜率 MB/份）；
  2. `gc.collect()` 能不能把它回收（--gc 开关对比）。

用法：
  python tools\mem_growth.py --configs 30
  python tools\mem_growth.py --configs 30 --gc
"""
from __future__ import annotations

import argparse
import gc
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))


def rss_mb() -> float:
    """当前进程 RSS（优先 psutil；没有就退回 Windows psapi / getrusage）。"""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1024 / 1024
    except Exception:                                    # noqa: BLE001
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        k32 = ctypes.windll.kernel32
        fn = getattr(k32, "K32GetProcessMemoryInfo", None) or ctypes.windll.psapi.GetProcessMemoryInfo
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        ok = fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        if not ok:
            return -1.0
        return pmc.WorkingSetSize / 1024 / 1024
    except Exception:                                    # noqa: BLE001
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="strategies/monkey_farm")
    ap.add_argument("--configs", type=int, default=30)
    ap.add_argument("--gc", action="store_true", help="每份配置后强制 gc.collect()")
    ap.add_argument("--start", default="20140101")
    ap.add_argument("--end", default="20221231")
    a = ap.parse_args(argv)

    import funnel
    from backtest import run_backtest

    files = sorted(Path(ROOT / a.dir).glob("*.yaml"))[: a.configs]
    if not files:
        print(f"[mem] {a.dir} 下没有 yaml")
        return 1

    print(f"[mem] 载入面板……", flush=True)
    store = funnel._store_for("real")
    base = rss_mb()
    print(f"[mem] 面板加载后 RSS {base:.0f} MB，开始跑 {len(files)} 份", flush=True)

    t0 = time.time()
    series = []
    for i, f in enumerate(files, 1):
        try:
            run_backtest(store, str(f), a.start, a.end, group="test", record=False, quiet=True)
        except Exception as e:                           # noqa: BLE001
            print(f"[mem] {i} {f.stem} 失败 {type(e).__name__}")
        if a.gc:
            gc.collect()
        cur = rss_mb()
        series.append(cur)
        if i % 5 == 0 or i == len(files):
            print(f"[mem] {i:3d}/{len(files)}  RSS {cur:7.0f} MB  "
                  f"Δ{(cur - base) / i:6.1f} MB/份", flush=True)

    wall = time.time() - t0
    slope = (series[-1] - base) / len(series)
    print(f"\n[mem] gc={a.gc}  {len(series)} 份用时 {wall:.1f}s（{wall / len(series):.2f}s/份）")
    print(f"[mem] 基线 {base:.0f} MB → 末值 {series[-1]:.0f} MB，斜率 {slope:.1f} MB/份")
    print(f"[mem] 外推 600 份/进程 → 约 +{slope * 600 / 1024:.1f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""tools/apply_engine_patches_22.py —— v2.2 补丁（P13/P14，幂等）

前面 12 处补丁修的是"执行正确性"和"判定口径"。这一轮修两个**运行时安全**问题：

| 编号 | 文件 | 缺口 | 修法 |
|---|---|---|---|
| P13 | engine/run_batch.py | rules 第 1 章「搜索角色不得读取验证期」在代码层只靠 P9 的可选环境变量，默认不拦 | 给搜索角色的唯一入口 `run_batch.py` 加 `--role`，**默认 search**：不带参数就只能跑搜索期；要跑验证期必须显式 `--role owner` |
| P14 | engine/funnel.py | `default_workers()` 只按 CPU 核数定并发；内存吃紧时（v2 的 `monkey_11` 出现过 98 条 `MemoryError`）会把机器打穿 | 并发再按可用内存封顶（每个 worker 约需 2.5GB 面板副本）。拿不到内存信息就退回 CPU−2，行为与原来一致 |

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/apply_engine_patches_22.py [--check-only]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATCHES = [
    # ---------------------------------------------------------------- P13
    {
        "id": "P13-run_batch 默认 search 角色",
        "file": "engine/run_batch.py",
        "old": '''    ap.add_argument("--workers", type=int, default=None,
                    help="并行 worker 数（缺省 = CPU 核数 − 2，rules.md 第 12 章；1 = 顺序）")
    a = ap.parse_args(argv)
    guard.check_date_range(a.start, a.end)''',
        "new": '''    ap.add_argument("--workers", type=int, default=None,
                    help="并行 worker 数（缺省 = CPU 核数 − 2，rules.md 第 12 章；1 = 顺序）")
    ap.add_argument("--role", default="search", choices=("search", "owner"),
                    help="执行角色（P13）：search=只能跑搜索期（默认，rules.md 第 1 章）；"
                         "owner=研究负责人，可跑验证期")
    a = ap.parse_args(argv)
    # P13：搜索角色的唯一入口就是本脚本。默认按 search 处理——不显式声明 owner，
    # 就不能把区间挪到验证期（2023-01-01 起），把 rules 第 1 章的隔离从文字纪律变成代码约束。
    os.environ["QUANT_ROLE"] = a.role
    guard.check_date_range(a.start, a.end)''',
    },
    {
        "id": "P13-import os",
        "file": "engine/run_batch.py",
        "old": "import sys\nimport time\nfrom pathlib import Path",
        "new": "import os\nimport sys\nimport time\nfrom pathlib import Path",
    },
    # ---------------------------------------------------------------- P14
    {
        "id": "P14-并发按内存封顶",
        "file": "engine/funnel.py",
        "old": "def default_workers() -> int:",
        "new": '''def _available_memory_gb() -> float | None:
    """当前可用物理内存（GB）；拿不到就返回 None（P14）。"""
    try:                                              # Windows
        import ctypes

        class _MEMSTATUS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = _MEMSTATUS()
        st.dwLength = ctypes.sizeof(_MEMSTATUS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return st.ullAvailPhys / (1024 ** 3)
    except Exception:                                 # noqa: BLE001
        pass
    try:                                              # POSIX
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / (1024 ** 2)
    except Exception:                                 # noqa: BLE001
        pass
    return None


WORKER_MEM_GB = 2.5          # 每个 worker 的面板副本经验值（v2 实测 114 只票约 1.2~1.8GB）


def default_workers() -> int:''',
    },
    {
        "id": "P14-default_workers 加内存上限",
        "file": "engine/funnel.py",
        "old": '''    """默认并行 worker 数（rules.md 第 12 章）：CPU 核数 − 2，至少 1。"""
    return max(1, (os.cpu_count() or 2) - 2)''',
        "new": '''    """默认并行 worker 数（rules.md 第 12 章）：CPU 核数 − 2，再按可用内存封顶。"""
    workers = max(1, (os.cpu_count() or 2) - 2)
    avail = _available_memory_gb()
    if avail is not None and avail > 0:
        # P14：内存不够时降并发。降并发不改变任何研究口径（rules 第 10 章），
        # 只是别让机器在 MemoryError 上炸掉——v2 的 monkey_11 就是这么废掉 76 个配置的。
        mem_cap = max(1, int(avail // WORKER_MEM_GB))
        if mem_cap < workers:
            print(f"[funnel] 可用内存 {avail:.1f}GB → 并发从 {workers} 降到 {mem_cap}"
                  f"（每个 worker 约 {WORKER_MEM_GB}GB；rules 第 10 章允许降并发）", flush=True)
            workers = mem_cap
    return workers''',
    },
]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="应用 v2.2 运行时安全补丁（幂等）")
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args(argv)

    rows, failures = [], 0
    for p in PATCHES:
        path = ROOT / p["file"]
        text = path.read_text(encoding="utf-8")
        if p["new"] in text:
            rows.append((p["id"], "已应用", ""))
            continue
        if p["old"] not in text:
            rows.append((p["id"], "FAIL", "找不到锚点"))
            failures += 1
            continue
        if not a.check_only:
            path.write_text(text.replace(p["old"], p["new"], 1), encoding="utf-8")
        rows.append((p["id"], "将应用" if a.check_only else "已应用", ""))
    width = max(len(r[0]) for r in rows)
    for pid, state, note in rows:
        print(f"  {pid:<{width}}  {state:<6} {note}")
    print(f"\n共 {len(PATCHES)} 处：应用 {sum(1 for r in rows if r[1] == '已应用')}，失败 {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

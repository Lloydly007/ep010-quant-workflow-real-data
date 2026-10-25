r"""研究进度速览：一条命令看清台账、农场、内存、配置单存量。

用法：python tools/progress.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ledger" / "ledger.csv"
TARGET_MONKEY = 12000


def free_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().available / 1024 ** 3
    except Exception:                                    # noqa: BLE001
        return -1.0


def main() -> int:
    if not LEDGER.exists():
        print("台账不存在")
        return 1
    d = pd.read_csv(LEDGER)
    d["group"] = d["group"].astype(str)
    d = d[d["group"] != "test"]          # test 组不计入研究组 N（rules.md）

    print(f"台账 {len(d)} 行")
    for g in ("A", "B", "test"):
        x = d[d["group"] == g]
        if len(x):
            ok = (x["status"] == "ok").sum()
            print(f"  {g:6s} ok {ok:5d} / {len(x):5d}")

    m = d[d["group"].str.startswith("monkey")]
    mok = int((m["status"] == "ok").sum())
    merr = int((m["status"] != "ok").sum())
    seeds = sorted(m["group"].unique(), key=lambda s: int(s.split("_")[1]) if "_" in s else 0)
    print(f"  猴子   ok {mok} / {TARGET_MONKEY} ({mok / TARGET_MONKEY * 100:.1f}%)  "
          f"错 {merr}  种子 {len(seeds)}/20  最新 {seeds[-1] if seeds else '-'}")

    for arm in ("A", "B"):
        for rnd in (1, 2, 3, 4, 5, 6):
            p = ROOT / "strategies" / arm / f"round{rnd}"
            if p.exists():
                print(f"  配置单 {arm}/round{rnd}: {len(list(p.glob('*.yaml')))} 份")

    print(f"可用内存 {free_gb():.1f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

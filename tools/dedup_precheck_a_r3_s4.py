# -*- coding: utf-8 -*-
"""跨组规范化去重预检：a_r3_s4_* 的因子规格是否与 A/round3 其它组或 A/round1-2 重复。

规范化口径近似 funnel 的去重（忽略 name/desc，只看 type/factors/holdings/rebalance/
中性化/industry_cap）。仅报告，不改文件。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

import yaml  # noqa: E402


def norm(y: Path):
    try:
        raw = yaml.safe_load(y.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, dict):
        return None
    t = raw.get("type")
    if t == "score":
        return json.dumps({
            "type": "score",
            "factors": raw.get("factors"),
            "holdings": raw.get("holdings", 30),
            "rebalance": str(raw.get("rebalance", "weekly_first_trade_day")).lower(),
            "neut_industry": bool(raw.get("neut_industry", False)),
            "neut_size": bool(raw.get("neut_size", False)),
            "industry_cap": int(raw.get("industry_cap", 0) or 0),
        }, ensure_ascii=False, sort_keys=True)
    return None


dirs = [ROOT / "strategies" / "A" / "round3",
        ROOT / "strategies" / "A" / "round2",
        ROOT / "strategies" / "A" / "round1",
        ROOT / "strategies" / "B" / "round1",
        ROOT / "strategies" / "B" / "round2"]
mine = {}
others = {}
for d in dirs:
    if not d.is_dir():
        continue
    for p in sorted(d.glob("*.yaml")):
        k = norm(p)
        if k is None:
            continue
        (mine if p.name.startswith("a_r3_s4_") else others).setdefault(k, []).append(p.name)

clash = [v for k, v in mine.items() if others.get(k)]
print(f"my score configs: {sum(len(v) for v in mine.values())} "
      f"unique: {len(mine)}")
print(f"other score configs scanned: {sum(len(v) for v in others.values())} "
      f"unique: {len(others)}")
print("normalized clashes with other rounds/groups:", clash if clash else "none")

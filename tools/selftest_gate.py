r"""自测：形态门在各目录上的判定。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from gates import require_form_gate  # noqa: E402

for d in ("strategies/A/round1", "strategies/A/round3", "strategies/B/round6",
          "strategies/random/seed_43", "strategies/examples"):
    p = ROOT / d
    if not p.exists():
        print(f"{d:28s} 不存在")
        continue
    rc, msg = require_form_gate(p.resolve())
    tail = msg if msg else "（非 strategies/{A,B}/roundN，不设门）"
    print(f"{d:28s} rc={rc}  {tail}")

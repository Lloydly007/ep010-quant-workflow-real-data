r"""形态门：检查某一轮配置单的 type 分布是否达到目标形态占比。

本次研究最贵的一条教训：第 1~2 轮 10 个 agent 全部写成 rule 型，
而原项目 92%~98% 是 score 型，导致 A 路 L2 通过率 0%~6%（正确形态下 80.5%）。
这道门应该在**回测之前**把整轮打回，而不是等跑完 200 份才发现。

用法：
  python tools/check_form.py --round 3            # 查 A/B 两路第 3 轮
  python tools/check_form.py --dir strategies/A/round6 --min-score 0.8
退出码：0 达标 / 1 不达标 / 2 目录不存在
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def form_of(p: Path) -> str:
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        return "unparsable"
    return str((raw or {}).get("type", "missing"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="", help="单个目录")
    ap.add_argument("--round", type=int, default=0, help="查 A/B 两路的第 N 轮")
    ap.add_argument("--min-score", type=float, default=0.80, help="score 型最低占比")
    a = ap.parse_args(argv)

    dirs: list[Path] = []
    if a.round:
        dirs = [ROOT / "strategies" / arm / f"round{a.round}" for arm in ("A", "B")]
    elif a.dir:
        dirs = [ROOT / a.dir]
    else:
        ap.error("需要 --round 或 --dir")

    bad = 0
    total_n = total_s = 0
    for d in dirs:
        if not d.exists():
            print(f"[form] {d.relative_to(ROOT)} 不存在")
            bad += 1
            continue
        files = sorted(d.glob("*.yaml"))
        if not files:
            print(f"[form] {d.relative_to(ROOT)} 没有配置单")
            bad += 1
            continue
        cnt: dict[str, int] = {}
        for f in files:
            k = form_of(f)
            cnt[k] = cnt.get(k, 0) + 1
        n = len(files)
        s = cnt.get("score", 0)
        total_n += n
        total_s += s
        ratio = s / n
        flag = "OK " if ratio >= a.min_score else "FAIL"
        print(f"[form] {flag} {d.relative_to(ROOT)}: {n} 份  score {s} ({ratio*100:.0f}%)  "
              f"分布 {cnt}")
        if ratio < a.min_score:
            bad += 1

    if total_n:
        print(f"[form] 合计 {total_n} 份，score 占比 {total_s/total_n*100:.1f}% "
              f"（门槛 {a.min_score*100:.0f}%）")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

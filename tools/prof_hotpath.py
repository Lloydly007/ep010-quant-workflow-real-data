r"""P18 前置测量：单配置回测的热点分布（因子计算 / 组合模拟 / 统计 / IO）。

目的：在真实面板（1698 只 × 3200 日）上判断「因子值缓存」能省多少。
做法：先加载面板（不计时），再用 cProfile 跑 N 份配置，按【源文件】聚合 tottime。

用法：
  python tools\prof_hotpath.py --strategies <yaml目录> --limit 6
  python tools\prof_hotpath.py --root <研究根目录> --strategies <配置目录>
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import sys
import time
from collections import defaultdict
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="", help="研究根目录（默认本文件上一级）")
    ap.add_argument("--strategies", required=True, help="配置单目录（递归找 yaml）")
    ap.add_argument("--start", default="20140101")
    ap.add_argument("--end", default="20221231")
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--group", default="test",
                    help="台账分组，必须合法：A / B / monkey_<seed> / example / test")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)

    root = Path(a.root) if a.root else Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "engine"))
    import funnel  # noqa: E402

    ys = sorted(Path(a.strategies).rglob("*.y*ml"))[: a.limit]
    if not ys:
        print(f"[prof] 目录里没有 yaml：{a.strategies}")
        return 1

    print(f"[prof] 根目录 {root}")
    print(f"[prof] 载入面板……", flush=True)
    t0 = time.time()
    store = funnel._store_for("real")
    load_s = time.time() - t0
    rows = getattr(getattr(store, "panel", None), "shape", None)
    print(f"[prof] 面板加载 {load_s:.1f}s shape={rows}", flush=True)

    tasks = [
        {"name": p.stem, "path": str(p), "start": a.start, "end": a.end,
         "group": a.group, "record": False}
        for p in ys
    ]
    runner = funnel.SeqRunner()
    runner._store = store

    pr = cProfile.Profile()
    t0 = time.time()
    pr.enable()
    out = runner.run(tasks)
    pr.disable()
    wall = time.time() - t0

    ok = [o for o in out if o.get("status") == "ok"]
    print(f"\n[prof] {len(ok)}/{len(tasks)} 份成功，总墙钟 {wall:.1f}s，"
          f"单份均 {wall / max(len(tasks), 1):.2f}s", flush=True)
    for o in out:
        if o.get("status") != "ok":
            print(f"[prof] 失败 {o.get('config')}: {o.get('note')}", flush=True)
    if not ok:
        print("[prof] 没有任何一份成功，不做热点结论")
        return 1

    st = pstats.Stats(pr)
    buf = io.StringIO()
    st.stream = buf

    # 按源文件聚合 tottime
    by_file: dict[str, float] = defaultdict(float)
    for (fn, _ln, _name), (_cc, _nc, tt, _ct, _callers) in st.stats.items():
        by_file[fn] += tt
    total = sum(by_file.values()) or 1.0
    top = sorted(by_file.items(), key=lambda kv: -kv[1])[:14]

    lines = []
    lines.append(f"# 热点剖析（{len(tasks)} 份配置，{a.start}~{a.end}）")
    lines.append("")
    lines.append(f"- 面板加载（不计入）：{load_s:.1f}s，shape={rows}")
    lines.append(f"- 回测墙钟：{wall:.1f}s，单份均 {wall / max(len(tasks), 1):.2f}s")
    lines.append(f"- 成功：{len(ok)}/{len(tasks)}")
    lines.append("")
    lines.append("## 按源文件聚合 tottime（自身时间，不含子调用）")
    lines.append("")
    lines.append("| 占比 | 秒/份 | 文件:行 |")
    lines.append("|---|---|---|")
    for fn, tt in top:
        short = fn.replace(str(root), ".")
        lines.append(f"| {tt / total * 100:.1f}% | {tt / max(len(tasks), 1):.2f} | `{short}` |")
    lines.append("")
    lines.append("## 函数级 Top 20（cumtime）")
    lines.append("")
    st.sort_stats("cumulative").print_stats(20)
    lines.append("```")
    lines.append(buf.getvalue())
    lines.append("```")

    text = "\n".join(lines)
    if a.out:
        p = Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        print(f"[prof] 写入 {p}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

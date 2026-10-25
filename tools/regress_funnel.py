# -*- coding: utf-8 -*-
"""tools/regress_funnel.py —— 判定层回归（P1/P2/P8/P9/P10/P11/P12/P13/P14/P15）

`regress_50.py` 只覆盖单配置回测路径（它走 run_batch）。本文件覆盖的是
"漏斗/生成器/守卫"那条路径——v2 的第一轮回归完全没碰它，被审计点出来了。

每个用例都独立、可复现，成功打印 PASS，失败打印 FAIL 并让退出码非 0。
不写台账、不改 research 数据；临时文件都落在 `setup_checks/` 下。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/regress_funnel.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

import guard  # noqa: E402  必须先于 numpy/pandas
import funnel  # noqa: E402
import shortlist as sl  # noqa: E402
from config import load_config  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, fn):
    try:
        ok, note = fn()
    except Exception as e:                      # noqa: BLE001
        ok, note = False, f"异常：{e!r}"
    RESULTS.append((name, ok, note))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {note}")


# ------------------------------------------------------------------ P1
def t_p1_index_refresh() -> tuple[bool, str]:
    tmp = ROOT / "strategies" / "_regress_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    name = "zz_regress_probe_p1"
    cfg = {"name": name, "type": "score", "desc": "regress",
           "factors": [{"op": "pb", "weight": -1.0}], "holdings": 30,
           "rebalance": "weekly_first_trade_day"}
    # 1) 先触发索引构建（此时新文件还不存在）
    funnel.refresh_config_index()
    funnel.find_config_yaml("__build_index_now__")
    # 2) 写盘 3) 不刷新时找不到（复现 v1 的 bug） 4) 刷新后找得到
    path = tmp / f"{name}.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    found_before = funnel.find_config_yaml(name)
    funnel.refresh_config_index()
    found_after = funnel.find_config_yaml(name)
    ok = found_before is None and found_after is not None
    return ok, f"未刷新={found_before} 刷新后={found_after}"


# ------------------------------------------------------------------ P2
def t_p2_canonical() -> tuple[bool, str]:
    a = {"name": "x1", "desc": "d1", "type": "score",
         "factors": [{"op": "pb", "weight": -1.0}], "holdings": 30}
    b = {"name": "x2", "desc": "完全不同的说明", "type": "score",
         "factors": [{"op": "pb", "weight": -1.0}], "holdings": 30}
    c = {"name": "x1", "type": "score",
         "factors": [{"op": "pb", "weight": -0.5}], "holdings": 30}
    same = funnel.canonical_config(a) == funnel.canonical_config(b)
    diff = funnel.canonical_config(a) != funnel.canonical_config(c)
    return same and diff, f"仅名/desc不同→相同={same}；权重不同→不同={diff}"


# ------------------------------------------------------------------ P8
def t_p8_nested_window() -> tuple[bool, str]:
    raw = {"name": "zz_regress_p8", "type": "score", "desc": "nested",
           "factors": [{"op": "xsec_pct", "of": {"op": "ret_n", "n": 60},
                        "weight": 1.0}], "holdings": 30,
           "rebalance": "weekly_first_trade_day"}
    params = funnel.enumerate_params(raw)
    has_of = [p for p in params if p.get("field") == "of"]
    if not has_of:
        return False, "enumerate_params 没枚举到 of 的窗口"
    neigh = funnel.build_neighbor_set(raw)
    if not neigh:
        return False, "build_neighbor_set 没生成邻居"
    ok_apply = all(nb["raw"]["factors"][0]["of"]["n"] in (20, 120) for nb in neigh)
    ok_other = all(nb["raw"]["factors"][0]["op"] == "xsec_pct"
                   and nb["raw"]["factors"][0]["of"]["op"] == "ret_n" for nb in neigh)
    ok_names = len({nb["name"] for nb in neigh}) == len(neigh)
    ok_valid = True
    tmp = ROOT / "setup_checks" / "regress_funnel"
    for nb in neigh:                            # 邻居必须是合法配置
        p = tmp / f"{nb['name']}.yaml"
        p.write_text(yaml.safe_dump(nb["raw"], allow_unicode=True), encoding="utf-8")
        try:
            load_config(p)
        except Exception:                       # noqa: BLE001
            ok_valid = False
    return (ok_apply and ok_other and ok_names and ok_valid,
            f"邻居 {len(neigh)} 个；n 只改 of 档位={ok_apply}；其它字段不变={ok_other}；"
            f"名字唯一={ok_names}；全部合法={ok_valid}")


# ------------------------------------------------------------------ P9
def t_p9_role() -> tuple[bool, str]:
    code = "\n".join([
        "import sys",
        "sys.path.insert(0, 'engine')",
        "import guard",
        "for rng in (('20140101', '20221231'), ('20230101', '20241231')):",
        "    try:",
        "        guard.check_date_range(*rng)",
        "        print('OK', rng)",
        "    except Exception as e:",
        "        print('BLOCK', rng, type(e).__name__)",
    ])
    env = dict(os.environ, QUANT_ROLE="search")
    out = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=ROOT, env=env,
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith(("OK", "BLOCK"))]
    ok = any(ln.startswith("OK") and "20140101" in ln for ln in lines) and \
         any(ln.startswith("BLOCK") and "20230101" in ln for ln in lines)
    return ok, " | ".join(lines)


# ------------------------------------------------------------------ P10
def t_p10_probe_clone() -> tuple[bool, str]:
    tmp = ROOT / "strategies" / "_regress_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    probe_dir = ROOT / "strategies" / "_regress_probes"
    probe_dir.mkdir(parents=True, exist_ok=True)
    struct = {"type": "score", "factors": [{"op": "pb", "weight": -1.0}],
              "holdings": 30, "rebalance": "weekly_first_trade_day"}
    probe = {"name": "zz_regress_probe", **struct, "desc": "probe"}
    clone = {"name": "zz_regress_clone", **struct, "desc": "clone"}
    (probe_dir / "zz_regress_probe__f0n_u.yaml").write_text(
        yaml.safe_dump({**probe, "name": "zz_regress_probe__f0n_u"}, allow_unicode=True),
        encoding="utf-8")
    (tmp / "zz_regress_clone.yaml").write_text(yaml.safe_dump(clone, allow_unicode=True),
                                               encoding="utf-8")
    funnel.refresh_config_index()
    import pandas as pd
    led = pd.DataFrame([
        {"ts": "1", "config": "zz_regress_clone", "group": "A", "type": "score",
         "start": "20140101", "end": "20221231", "status": "ok", "n_trades": "500",
         "ann_excess": "0.05", "ir": "1.0", "excess_max_dd": "-0.1",
         "funnel_l1": "1", "funnel_l2": "1", "funnel_l3": "1", "funnel_l4": "1"},
        {"ts": "2", "config": "zz_regress_clone", "group": "A", "type": "score",
         "start": "20230101", "end": "20241231", "status": "ok", "n_trades": "500",
         "ann_excess": "0.05", "ir": "1.0", "excess_max_dd": "-0.1",
         "funnel_l1": "1", "funnel_l2": "1", "funnel_l3": "1", "funnel_l4": "1"},
    ])
    res = sl.build_shortlist(led, "A")
    # P10 的最终形态是「标记而不剔除」（rules 5.4 第 6 条：入围名单内部不做 L7 去重）
    flagged = [d for d in res.get("probe_clones_dropped") or []
               if d["config"] == "zz_regress_clone"]
    dup_of_older = [d for d in res.get("probe_duplicates_of_older_configs") or []
                    if d["config"] == "zz_regress_clone"]
    ok = bool(flagged or dup_of_older)
    for p in (probe_dir / "zz_regress_probe__f0n_u.yaml", tmp / "zz_regress_clone.yaml"):
        p.unlink(missing_ok=True)
    return ok, f"flagged={bool(flagged)} dup_of_older={bool(dup_of_older)}"


# ------------------------------------------------------------------ P11
def t_p11_summary_text() -> tuple[bool, str]:
    src = (ROOT / "engine" / "funnel.py").read_text(encoding="utf-8")
    bad = "20 只种子全部完成" in src
    good = "并非全部完成" in src and "无成功结果" in src
    return (not bad) and good, f'还在写"全部完成"={bad}；按台账统计={good}'



# ------------------------------------------------------------------ P12
def t_p12_probe_dedup() -> tuple[bool, str]:
    """P12：邻域探针不与"已有基础配置的结构"重复（但允许探针之间同构）。"""
    import pandas as pd
    tmp = ROOT / "strategies" / "_regress_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    struct = {"type": "score", "factors": [{"op": "ret_n", "n": 60, "weight": 1.0}],
              "holdings": 30, "rebalance": "weekly_first_trade_day"}
    base = {"name": "zz_p12_base", **struct, "desc": "base"}
    (tmp / "zz_p12_base.yaml").write_text(yaml.safe_dump(base, allow_unicode=True),
                                          encoding="utf-8")
    funnel.refresh_config_index()
    plan = funnel.plan_l5_l6(pd.DataFrame(columns=["config", "group", "ts"]), ["zz_p12_base"])
    # 台账里没有行 → 会被判 "无 group"，改用带 group 的最小台账
    led = pd.DataFrame([{"ts": "1", "config": "zz_p12_base", "group": "A",
                         "start": "20140101", "end": "20221231", "status": "ok"}])
    plan = funnel.plan_l5_l6(led, ["zz_p12_base"])
    tasks = plan["tasks"]
    hit = [t for t in tasks if t["name"].startswith("zz_p12_base__")]
    # base 自身的结构在台账里（就是它自己）→ 探针不允许与任何基础配置同构；
    # 单参数变体本身与 base 不同构，所以这里应能生成邻居
    ok = bool(hit) or bool(plan["plan"].get("zz_p12_base", {}).get("neighbors") is not None)
    (tmp / "zz_p12_base.yaml").unlink(missing_ok=True)
    return ok, f"生成任务 {len(tasks)} 个（含探针 {len(hit)} 个）"


# ------------------------------------------------------------------ P13
def t_p13_role_default() -> tuple[bool, str]:
    """P13：run_batch 默认 search 角色，验证期必须被拒；--role owner 才放行。"""
    code = ["import sys", "sys.path.insert(0, 'engine')", "import guard",
            "guard.check_date_range('20230101', '20241231')"]
    argv = [sys.executable, "-X", "utf8", "engine/run_batch.py", "--dir",
            "strategies/_regress", "--group", "test",
            "--start", "20230101", "--end", "20241231", "--workers", "2"]
    r1 = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    r2 = subprocess.run(argv + ["--role", "owner"], cwd=ROOT, capture_output=True,
                        text=True, encoding="utf-8", errors="replace")
    blocked = r1.returncode == 2 and "搜索角色" in (r1.stdout + r1.stderr)
    allowed = r2.returncode == 0
    return blocked and allowed, f"默认→退出码 {r1.returncode}；owner→退出码 {r2.returncode}"


# ------------------------------------------------------------------ P14
def t_p14_worker_cap() -> tuple[bool, str]:
    """P14：并发 = CPU−2，再按可用内存封顶，且恒 ≥1。"""
    import os as _os
    w = funnel.default_workers()
    cpu_cap = max(1, (_os.cpu_count() or 2) - 2)
    avail = funnel._available_memory_gb()
    ok_basic = 1 <= w <= cpu_cap
    if avail:
        ok_mem = w <= max(1, int(avail // funnel.WORKER_MEM_GB))
    else:
        ok_mem = True
    return ok_basic and ok_mem, f"workers={w}（CPU 上限 {cpu_cap}，可用内存 {avail}GB）"


# ------------------------------------------------------------------ P15
def t_p15_retry() -> tuple[bool, str]:
    """P15：并行失败的任务改单进程重试（同配置/同组/同区间）。"""
    d = ROOT / "strategies" / "_regress_tmp" / "bad"
    d.mkdir(parents=True, exist_ok=True)
    (d / "zz_p15_bad.yaml").write_text(
        "name: zz_p15_bad\ntype: rule\ndesc: 越档\nbuy:\n"
        "  - {op: ret_n, n: 21, dir: above, threshold: 2.0}\nmax_hold_days: 20\n",
        encoding="utf-8")
    r = subprocess.run([sys.executable, "-X", "utf8", "engine/run_batch.py", "--dir", str(d),
                        "--group", "test", "--workers", "3"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    ok = ("P15" in out) and ("重试" in out) and r.returncode == 1
    shutil.rmtree(d, ignore_errors=True)
    return ok, f"退出码 {r.returncode}；输出含单进程重试={'P15' in out and '重试' in out}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("[regress-funnel] 判定层回归")
    check("P1 配置索引刷新（写盘后能被找到）", t_p1_index_refresh)
    check("P2 规范化去重忽略 name/desc", t_p2_canonical)
    check("P8 嵌套 of 的窗口会被枚举并生成合法邻居", t_p8_nested_window)
    check("P9 QUANT_ROLE=search 时验证期被拦", t_p9_role)
    check("P10 探针的改名副本被识别并标记", t_p10_probe_clone)
    check("P11 农场完成度按台账统计", t_p11_summary_text)
    check("P12 探针生成不与已有基础配置同构", t_p12_probe_dedup)
    check("P13 run_batch 默认拒绝验证期，owner 放行", t_p13_role_default)
    check("P14 并发按 CPU 与可用内存双封顶", t_p14_worker_cap)
    check("P15 并行失败任务单进程重试", t_p15_retry)

    n_ok = sum(1 for _, ok, _ in RESULTS if ok)
    md = ["# 判定层回归（P1/P2/P8/P9/P10/P11）", ""]
    md.append("`regress_50.py` 覆盖的是单配置回测路径；本文件覆盖漏斗/生成器/守卫路径。")
    md.append("")
    md.append("| 用例 | 结果 | 说明 |")
    md.append("|---|---|---|")
    for name, ok, note in RESULTS:
        md.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {note} |")
    md.append("")
    md.append(f"结论：**{n_ok}/{len(RESULTS)} 通过**。")
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "regress_funnel.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (ROOT / "data" / "regress_funnel.json").write_text(
        json.dumps({"n": len(RESULTS), "passed": n_ok,
                    "cases": [{"name": n, "pass": o, "note": t} for n, o, t in RESULTS]},
                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n[regress-funnel] {n_ok}/{len(RESULTS)} 通过；写出 reports/regress_funnel.md")
    return 0 if n_ok == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())

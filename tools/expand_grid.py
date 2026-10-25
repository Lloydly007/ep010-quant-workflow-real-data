# -*- coding: utf-8 -*-
"""tools/expand_grid.py —— 参数格展开：把每轮配置数补到目标值（规模差异的正解）

背景：v2 的 6 轮搜索每轮只有 24~39 个配置，原版规格是每轮 100~150。
补规模有两条路：再开几十个 agent 写配置，或者**确定性地在档位格上展开**。
本脚本走第二条，且刻意避开"只动一个参数"——那正好是 L5 邻域的定义，
展开成单参数变体会让 L5 变成"自己考自己"。这里每个变体同时动 **2 个参数**
（窗口 + 阈值 / 持有期 + 止损 / 权重 + 窗口 …），它们是独立的格点，不是邻域。

纪律：
  * 只动 rules.md 第 7 节档位内的参数（`funnel.enumerate_params` 给出的参数集）；
  * 每个变体都过 `config.load_config` 校验，不合法直接丢；
  * 与**全库**规范化去重（`funnel.canonical_config`），不与任何已存在配置重复；
  * 名字 `<原名>_g<k>`，desc 追加标记，报告里据此单列"agent 原创 / 格展开"。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/expand_grid.py --target 100 [--dry-run]
"""

from __future__ import annotations

import argparse
import copy
import itertools
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

import guard  # noqa: E402  必须先于 numpy/pandas

import funnel  # noqa: E402
from config import ConfigError, load_config  # noqa: E402

ROUNDS = [("A", r) for r in range(1, 7)] + [("B", r) for r in range(1, 7)]
MARK = "｜参数格展开"


def _apply(raw: dict, param: dict, value) -> dict:
    out = copy.deepcopy(raw)
    if param["key"] is None:
        out[param["field"]] = value
    elif param["field"] == "of":
        out[param["key"]][param["idx"]]["of"]["n"] = value
    elif param["idx"] is None:
        out[param["key"]][param["field"]] = value
    else:
        out[param["key"]][param["idx"]][param["field"]] = value
    return out


def variants(raw: dict) -> list[dict]:
    """同时动两个档位的变体（笛卡尔积，去重后返回）。"""
    params = funnel.enumerate_params(raw)
    if len(params) < 2:
        return []
    out, seen = [], set()
    # 只取前 6 个参数做两两组合，避免组合爆炸（每对最多 4 个方向组合）
    for p1, p2 in itertools.combinations(params[:6], 2):
        for (d1, v1), (d2, v2) in itertools.product(funnel.param_neighbors(p1),
                                                    funnel.param_neighbors(p2)):
            cand = _apply(raw, p1, v1)
            cand = _apply(cand, p2, v2)
            sig = funnel.canonical_config(cand)
            if sig in seen:
                continue
            seen.add(sig)
            out.append({"_from": f"{p1['tag']}{d1}+{p2['tag']}{d2}", "_raw": cand})
    return out


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="参数格展开到目标配置数")
    ap.add_argument("--target", type=int, default=100, help="每轮目标配置数")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    # 全库已有结构的规范化签名（含探针），展开体不得与任何一个重复
    existing: set[str] = set()
    for p in (ROOT / "strategies").rglob("*.y*ml"):
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:                                  # noqa: BLE001
            continue
        if isinstance(raw, dict) and raw.get("name"):
            existing.add(funnel.canonical_config(raw))

    rows = []
    for group, r in ROUNDS:
        d = ROOT / "strategies" / group / f"round{r}"
        if not d.is_dir():
            continue
        files = sorted(d.glob("*.yaml"))
        n0 = len(files)
        if n0 >= a.target:
            rows.append((f"{group}{r}", n0, 0, n0, "已达标"))
            continue
        made = 0
        for f in files:
            if n0 + made >= a.target:
                break
            raw = yaml.safe_load(f.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            k = 0
            for v in variants(raw):
                if n0 + made >= a.target:
                    break
                cand = v["_raw"]
                sig = funnel.canonical_config(cand)
                if sig in existing:
                    continue
                k += 1
                cand["name"] = f"{raw['name']}_g{k}"
                cand["desc"] = f"{raw.get('desc', '')}{MARK}({v['_from']})"
                path = d / f"{cand['name']}.yaml"
                # 校验走临时文件：dry-run 时真实路径不落盘，但仍要过 load_config
                tmp = ROOT / "setup_checks" / "_grid_candidate.yaml"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(yaml.safe_dump(cand, allow_unicode=True, sort_keys=False),
                               encoding="utf-8")
                try:
                    load_config(tmp)
                except ConfigError:
                    tmp.unlink(missing_ok=True)
                    continue
                tmp.unlink(missing_ok=True)
                if not a.dry_run:
                    path.write_text(yaml.safe_dump(cand, allow_unicode=True, sort_keys=False),
                                    encoding="utf-8")
                existing.add(sig)
                made += 1
        rows.append((f"{group}{r}", n0, made, n0 + made, ""))

    w = max(len(r[0]) for r in rows)
    print(f"{'轮次':<{w}}  原有  新增  合计")
    for name, n0, add, tot, note in rows:
        print(f"{name:<{w}}  {n0:>4}  {add:>4}  {tot:>4}  {note}")
    total_add = sum(r[2] for r in rows)
    total_now = sum(r[3] for r in rows)
    print(f"\n合计：新增 {total_add} 个配置，现有 {total_now} 个"
          f"{'（dry-run，未写盘）' if a.dry_run else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""tools/apply_engine_patches.py —— v2 的引擎缺口补丁（6 处，幂等，可复核）

背景：v1 复刻跑完后，六个独立审计角色在 `ep010-research/reports/audit_0*.md` 里
指出的问题里，有 6 条是引擎自身的缺口或记录缺失。v2 在**不改变任何筛选阈值**的
前提下修掉它们，并用"逐位回归"证明补丁不改变未受影响配置的结果
（`tools/regress_50.py`，50 个配置、全部指标逐位一致）。

| 编号 | 文件 | 缺口 | 修法 |
|---|---|---|---|
| P1 | engine/funnel.py | `find_config_yaml` 的模块级索引只在首次调用时构建；同一进程内先建索引再写配置单（`farm` 正是如此），后续 L5 规划全部「找不到原配置单」 | 新增 `refresh_config_index()`，`gen_monkey` 与 `plan_l5_l6` 写盘后调用 |
| P2 | engine/funnel.py | `canonical_config()` 把 `name`/`desc` 一起归一，而两者唯一 → rules.md 第 11 章的随机配置去重恒不触发（空操作） | 归一时剔除 `name` / `desc`（rules.md 第 241 行：忽略名称等元数据） |
| P3 | engine/config.py | 市场级零件（`etf_above_ma_n`）可作打分因子/排序键/嵌套基零件：截面秩恒并列 → 零信息组合照常过 L1~L5 | 解析期拒绝，给出明确 ConfigError |
| P4 | engine/operators.py | P3 那类配置在回测期表现为 `KeyError('close_adj')`（在股票面板上找 ETF 列），不可诊断 | 市场级零件在错误面板上求值时抛带指引的 RuntimeError |
| P5 | engine/funnel.py | L5 对「无可移动参数」的配置按"空真"通过，但 `l5_detail` 里没有任何标记，报告无法注明检验范围（rules.md 5.2 最后一条） | 记录 `empty_neighborhood=True`，不改通过/不通过的判定 |
| P6 | engine/funnel.py | 随机配置生成器的因子池包含市场级零件（P3 的源头） | 因子池剔除 `MARKET_LEVEL_OPS`，从源头不生成退化配置 |

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/apply_engine_patches.py [--check-only]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"

PATCHES = [
    # ---------------------------------------------------------------- P1
    {
        "id": "P1-新增 refresh_config_index",
        "file": "engine/funnel.py",
        "old": '_CONFIG_IDX: dict[str, Path] | None = None\n\n\ndef find_config_yaml(name: str) -> Path | None:',
        "new": '''_CONFIG_IDX: dict[str, Path] | None = None


def refresh_config_index() -> None:
    """作废 strategies/ 的配置索引缓存（下次 find_config_yaml 重建）。

    EP010 复刻补丁 P1：索引只在首次调用时构建。同一进程内"先建索引、再写配置单"
    的路径（farm 的 gen_monkey、layers 的邻域写盘）会让后续 L5 规划读不到新文件，
    表现为 `l5_detail[name] = {"error": "找不到原配置单 …"}` —— 那是任务失败，
    不是筛选失败（rules.md 5.2）。写盘后必须调用本函数。
    """
    global _CONFIG_IDX
    _CONFIG_IDX = None


def find_config_yaml(name: str) -> Path | None:''',
    },
    {
        "id": "P1-调用点：gen_monkey 写盘后",
        "file": "engine/funnel.py",
        "old": "        paths.append(path)\n    return paths, names",
        "new": "        paths.append(path)\n    refresh_config_index()      # P1：本批配置单已落盘，作废索引缓存\n    return paths, names",
    },
    {
        "id": "P1-调用点：plan_l5_l6 写邻域后",
        "file": "engine/funnel.py",
        "old": '''        if val_needed:
            tasks.append({"name": f"{name}__val", "path": str(src),
                          "start": VALID_START, "end": VALID_END, "group": grp})
    return {"tasks": tasks, "plan": plan}''',
        "new": '''        if val_needed:
            tasks.append({"name": f"{name}__val", "path": str(src),
                          "start": VALID_START, "end": VALID_END, "group": grp})
    refresh_config_index()      # P1：邻域配置单已落盘，作废索引缓存
    return {"tasks": tasks, "plan": plan}''',
    },
    # ---------------------------------------------------------------- P2
    {
        "id": "P2-canonical_config 忽略 name/desc",
        "file": "engine/funnel.py",
        "old": "    def norm(o):\n        if isinstance(o, dict):\n            return {f\"k:{k}\": norm(v) for k, v in",
        "new": '''    # P2：rules.md 第 11 章「规范化比较忽略名称等元数据」。原实现把 name/desc
    # 一起归一，而两者在随机生成里唯一（desc 内嵌 seed），去重因此恒不触发。
    raw = {k: v for k, v in raw.items() if str(k) not in ("name", "desc")}

    def norm(o):
        if isinstance(o, dict):
            return {f"k:{k}": norm(v) for k, v in''',
    },
    # ---------------------------------------------------------------- P5
    {
        "id": "P5-L5 记录空邻域",
        "file": "engine/funnel.py",
        "old": '''    if total == 0:
        return {"pass": True, "ratio": None, "n_total": 0, "n_pass": 0,
                "neighbors": {}, "note": "无可移动参数，空邻域按空真通过"}
    ratio = n_pass / total
    return {"pass": bool(ratio >= L5_MIN_RATIO), "ratio": ratio,
            "n_total": total, "n_pass": n_pass, "neighbors": per, "note": ""}''',
        "new": '''    if total == 0:
        # P5：判定不变（空真通过），但必须让下游能识别，报告要注明检验范围
        return {"pass": True, "ratio": None, "n_total": 0, "n_pass": 0,
                "neighbors": {}, "empty_neighborhood": True,
                "note": "无可移动参数，空邻域按空真通过（rules.md 5.2：须注明检验范围）"}
    ratio = n_pass / total
    return {"pass": bool(ratio >= L5_MIN_RATIO), "ratio": ratio,
            "n_total": total, "n_pass": n_pass, "neighbors": per,
            "empty_neighborhood": False, "note": ""}''',
    },
    # ---------------------------------------------------------------- P6
    {
        "id": "P6-因子池剔除市场级零件",
        "file": "engine/funnel.py",
        "old": "FACTOR_BASE_POOL = tuple(n for n in OPS_WITH_N + OPS_NO_ARG if n not in OF_WRAPPERS)",
        "new": '''# P6：市场级零件（当日全市场同值）作打分因子的截面秩恒并列，选股退化成按代码
# 顺序取前 N 只；这类配置仍会过 L1~L5（见 v1 的 m43_028）。从生成器源头剔除。
MARKET_LEVEL_OPS = frozenset({"etf_above_ma_n"})
FACTOR_BASE_POOL = tuple(n for n in OPS_WITH_N + OPS_NO_ARG
                         if n not in OF_WRAPPERS and n not in MARKET_LEVEL_OPS)''',
    },
    # ---------------------------------------------------------------- P3
    {
        "id": "P3-config.py 拒绝市场级零件作因子/排序键",
        "file": "engine/config.py",
        "old": "INDUSTRY_CAP_TIERS = tuple(ALLOWED_WINDOWS)",
        "new": '''INDUSTRY_CAP_TIERS = tuple(ALLOWED_WINDOWS)

# P3（EP010 复刻补丁）：市场级零件在任意截面上的值都相同（当日全市场同值），
# 因此不能作打分因子、排序键或嵌套基零件——它们的截面秩恒并列，选股退化成按
# 代码顺序取前 N 只，而引擎没有任何"因子无截面离散度"的检查（v1 的 m43_028
# 就是这样进了入围名单）。只允许作 buy/sell 条件。
MARKET_LEVEL_OPS = frozenset({"etf_above_ma_n"})


def _reject_market_level(spec: dict, what: str) -> None:
    """拒绝市场级零件作 factor / rank / 嵌套基零件（P3）。"""
    name = str(spec.get("op", ""))
    if name in MARKET_LEVEL_OPS:
        raise ConfigError(
            f"{what}: 零件 {name} 是市场级零件（当日全市场同值），不能作打分因子 / "
            f"排序键 / 嵌套基零件；只能作 buy/sell 条件（rules.md 7.5）")
    if isinstance(spec.get("of"), dict):
        _reject_market_level(spec["of"], f"{what}.of")''',
    },
    {
        "id": "P3-调用点：rank",
        "file": "engine/config.py",
        "old": '''        base = _parse_operator(rank, "rank")
        order = str(rank.get("order", "desc")).lower()''',
        "new": '''        base = _parse_operator(rank, "rank")
        _reject_market_level(base, "rank")
        order = str(rank.get("order", "desc")).lower()''',
    },
    {
        "id": "P3-调用点：factors",
        "file": "engine/config.py",
        "old": '''        base = _parse_operator(f, f"factors[{i}]")
        w = _num(f.get("weight"), f"factors[{i}].weight")''',
        "new": '''        base = _parse_operator(f, f"factors[{i}]")
        _reject_market_level(base, f"factors[{i}]")
        w = _num(f.get("weight"), f"factors[{i}].weight")''',
    },
    # ---------------------------------------------------------------- P4
    {
        "id": "P4-市场级零件在错误面板上给出可诊断错误",
        "file": "engine/operators.py",
        "old": '    close = panel["close_adj"].to_numpy(dtype="float64")',
        "new": '''    if "close_adj" not in panel.columns:      # P4：可诊断的错误，而不是 KeyError
        raise RuntimeError(
            "etf_above_ma_n 是市场级零件，必须在**单只 ETF 的日线长表**上求值"
            "（列含 close_adj）；当前传入的是股票面板。它不能作打分因子/排序键/"
            "嵌套基零件，只能作 buy/sell 条件（engine/config.py 会拒绝前者）")
    close = panel["close_adj"].to_numpy(dtype="float64")''',
    },
]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="应用 v2 引擎补丁（幂等）")
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
            rows.append((p["id"], "FAIL", "找不到锚点（文件已被改动？）"))
            failures += 1
            continue
        if text.count(p["old"]) > 1 and p["id"] != "P1-调用点：gen_monkey 写盘后":
            rows.append((p["id"], "FAIL", f"锚点出现 {text.count(p['old'])} 次，不唯一"))
            failures += 1
            continue
        if not a.check_only:
            path.write_text(text.replace(p["old"], p["new"], 1), encoding="utf-8")
        rows.append((p["id"], "将应用" if a.check_only else "已应用", ""))

    width = max(len(r[0]) for r in rows)
    for pid, state, note in rows:
        print(f"  {pid:<{width}}  {state:<6} {note}")
    applied = sum(1 for r in rows if r[1] == "已应用")
    print(f"\n共 {len(PATCHES)} 处补丁：本次应用 {sum(1 for r in rows if r[1]=='已应用')}，"
          f"失败 {failures}")
    return 0 if failures == 0 else 1


PATCHES.append({
    "id": "P7-只把成功行当作已跑",
    "file": "engine/funnel.py",
    "old": 'def known_config_names(ledger: pd.DataFrame) -> set[str]:\n'
           '    """台账中出现过的全部配置名（任何状态都算已跑，skip-existing 依据）。"""\n'
           '    return set(ledger["config"].astype(str)) if len(ledger) else set()',
    "new": '''def known_config_names(ledger: pd.DataFrame) -> set[str]:
    """台账中**至少有一次成功执行**的配置名（skip-existing 依据）。

    EP010 复刻补丁 P7：原实现把任何状态都算「已跑」，于是报错任务永远不会被重试，
    直接违反 rules.md 第 10 章「只重试尚未成功任务」。实测后果：v2 的 monkey_11 有
    76/204 个配置因 MemoryError 失败后，再跑 farm 也只会报「待回测 0」。
    现只认 status=ok 的行；报错行仍完整保留在台账（rules 第 6 章），只是不阻止重试。
    """
    if not len(ledger):
        return set()
    if "status" in ledger.columns:
        ok = ledger[ledger["status"].astype(str) == "ok"]
    else:                                                   # pragma: no cover
        ok = ledger
    return set(ok["config"].astype(str))''',
})


if __name__ == "__main__":
    raise SystemExit(main())

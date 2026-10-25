# -*- coding: utf-8 -*-
"""tools/apply_engine_patches_21.py —— v2.1 判定层补丁（P8~P11，幂等）

v2 的 7 处补丁（P1~P7，见 `tools/apply_engine_patches.py`）修的是"能不能正确执行"；
v2 的四个审计角色又指出 4 处"判定层"的缺口，本文件修它们：

| 编号 | 文件 | 缺口 | 修法 |
|---|---|---|---|
| P8 | engine/funnel.py | L5 的邻域枚举只看**顶层**窗口：`xsec_pct/ts_pct/ind_rank` 把窗口藏在 `of` 里 → 这类因子不产生邻居 → L5「空真通过」（v2 实测 A 4 / B 5 / MONKEY 2 / MS 166 条） | 递归枚举 `factors[i].of.n`，并让 `build_neighbor_set` 能改嵌套窗口 |
| P9 | engine/guard.py | rules 第 1 章要求"搜索角色不得读取验证期"，但 `guard` 只锁 2025+，2023–2024 在代码层敞开 | 增加 `QUANT_ROLE=search` 角色：该角色下 2023-01-01 起的区间也直接抛错（默认 `owner`，行为不变） |
| P10 | engine/shortlist.py | 探针按**名字**（含 `__`）排除，agent 把探针结构抄成新名字再参赛时引擎识别不了（v2 的入围 3 条里 3 条都是探针改名副本） | 入围前按**结构签名**比对已有探针，命中则剔除并记录 `probe_clones_dropped` |
| P11 | engine/funnel.py | `funnel_summary.md` 只按"JSON 份数==20"就写"20 只种子全部完成"，v2 的 `monkey_11` 当时有 76 个配置没跑出结果 | 改成按台账统计每个种子"无成功结果的配置数"再下结论 |

P8 会让 L5 变严（更多真邻居），这是设计意图：空真通过本来就不该算通过。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/apply_engine_patches_21.py [--check-only]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATCHES = [
    # ---------------------------------------------------------------- P8
    {
        "id": "P8-枚举嵌套 of 的窗口",
        "file": "engine/funnel.py",
        "old": '''            if str(f.get("op", "")) in OP_ARG_OPERATORS and f.get("n") is not None:
                add("factors", i, "n", "window", int(f["n"]), f"f{i}n")
    return params''',
        "new": '''            if str(f.get("op", "")) in OP_ARG_OPERATORS and f.get("n") is not None:
                add("factors", i, "n", "window", int(f["n"]), f"f{i}n")
            # P8：wrapper（xsec_pct/ts_pct/ind_rank）把窗口藏在 of 里。原来只枚举顶层 n，
            # 于是「全是无窗零件 + 一个 wrapper」的配置一个邻居都不产生 → L5 空真通过。
            of = f.get("of")
            if isinstance(of, dict) and str(of.get("op", "")) in OP_ARG_OPERATORS \\
                    and of.get("n") is not None:
                add("factors", i, "of", "window", int(of["n"]), f"f{i}ofn")
    return params''',
    },
    {
        "id": "P8-邻居写回支持嵌套窗口",
        "file": "engine/funnel.py",
        "old": '''            if p["key"] is None:
                nraw[p["field"]] = nv
            elif p["idx"] is None:
                nraw[p["key"]][p["field"]] = nv''',
        "new": '''            if p["key"] is None:
                nraw[p["field"]] = nv
            elif p["field"] == "of":
                # P8：嵌套基零件的窗口（factors[i].of.n）
                nraw[p["key"]][p["idx"]]["of"]["n"] = nv
            elif p["idx"] is None:
                nraw[p["key"]][p["field"]] = nv''',
    },
    # ---------------------------------------------------------------- P9
    {
        "id": "P9-guard 增加 search 角色",
        "file": "engine/guard.py",
        "old": 'SEALED_START = "20250101"          # rules.md：封存期 2025-01-01 ~ 至今',
        "new": '''SEALED_START = "20250101"          # rules.md：封存期 2025-01-01 ~ 至今
VALID_START = "20230101"           # rules.md 第 1 节：验证期 2023-01-01 起
# P9（EP010 复刻补丁）：rules 第 1 节要求「搜索角色仅可使用搜索期数据，不读取验证期」。
# 原来这条只有文字纪律（guard 只锁 2025+），2023-2024 在代码层是敞开的。现在：
#   QUANT_ROLE=search  → 任何触及 2023-01-01 及以后的区间都抛 RoleViolation；
#   QUANT_ROLE=owner（默认）/ validation / sealed → 行为与原来完全一致。
ROLE = os.environ.get("QUANT_ROLE", "owner").strip().lower()


class RoleViolation(RuntimeError):
    """搜索角色试图读取验证期/封存期数据（rules.md 第 1 节）。"""


def check_role_range(start: str | None, end: str | None) -> None:
    """搜索角色只能碰搜索期；其它角色不受此限（P9）。"""
    if ROLE != "search":
        return
    for d in (start, end):
        if d is None or str(d).strip() == "":
            continue
        if str(d).replace("-", "")[:8] >= VALID_START:
            raise RoleViolation(
                f"搜索角色不得读取验证期及以后的数据：请求区间 [{start} ~ {end}]"
                f"（rules.md 第 1 节）。以研究负责人身份运行请设 QUANT_ROLE=owner。")''',
    },
    {
        "id": "P9-接入 check_date_range",
        "file": "engine/guard.py",
        "old": '''def check_date_range(start: str | None, end: str | None) -> None:
    """校验 [start, end] 不触及封存期；否则抛 SealedDataError。"""
    if _marker_exists():
        return''',
        "new": '''def check_date_range(start: str | None, end: str | None) -> None:
    """校验 [start, end] 不触及封存期（未开封时）与验证期（search 角色）；否则抛错。"""
    check_role_range(start, end)
    if _marker_exists():
        return''',
    },
    # ---------------------------------------------------------------- P10
    {
        "id": "P10-短名单按结构签名剔除探针副本",
        "file": "engine/shortlist.py",
        "old": "def build_shortlist(ledger: pd.DataFrame, group: str, final_set: set[str] | None = None\n                    ) -> dict:",
        "new": '''def _probe_signatures() -> dict[str, str]:
    """{结构签名: 探针名}（EP010 复刻补丁 P10）。

    探针按名字（含 __）排除只对付"照抄名字"的情况；agent 把探针的结构抄成一个
    新名字再参赛时，名字检查失效（v2 的入围 3 条全部命中）。这里用与
    funnel.canonical_config 同一套归一化（剔除 name/desc）算结构签名，
    在入围前把"与已有探针结构相同"的配置剔出去。
    """
    from funnel import canonical_config          # 局部 import：避免与 funnel 循环导入
    import yaml as _yaml
    out: dict[str, str] = {}
    base = ROOT / "strategies"
    if not base.exists():
        return out
    for p in sorted(base.rglob("*.y*ml")):
        if "__" not in p.stem:
            continue
        try:
            raw = _yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:                        # noqa: BLE001
            continue
        if isinstance(raw, dict) and raw.get("name"):
            out.setdefault(canonical_config(raw), p.stem)
    return out


def build_shortlist(ledger: pd.DataFrame, group: str, final_set: set[str] | None = None
                    ) -> dict:''',
    },
    {
        "id": "P10-入围前剔除副本",
        "file": "engine/shortlist.py",
        "old": "    names = sorted(n for n in set(latest_s) | set(latest_v) if not is_probe(n))",
        "new": '''    names = sorted(n for n in set(latest_s) | set(latest_v) if not is_probe(n))
    # P10：再按结构签名剔一遍「探针的改名副本」（rules.md 5.2：探针不参与入围排名）
    cloned: list[dict] = []
    try:
        from funnel import canonical_config
        import yaml as _yaml
        probe_sigs = _probe_signatures()
        if probe_sigs:
            kept: list[str] = []
            for n in names:
                src = next((p for p in (ROOT / "strategies").rglob(f"{n}.yaml")), None)
                sig = None
                if src is not None:
                    raw = _yaml.safe_load(src.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        sig = canonical_config(raw)
                if sig and sig in probe_sigs and probe_sigs[sig] != n:
                    cloned.append({"config": n, "probe": probe_sigs[sig]})
                    continue
                kept.append(n)
            names = kept
    except Exception:                            # noqa: BLE001  任何异常都不影响原有逻辑
        cloned = []''',
    },
    {
        "id": "P10-把剔除结果写进产物",
        "file": "engine/shortlist.py",
        "old": '''        "n_qualified": sum(1 for r in rows if r["hard"]),
        "entries": entries,''',
        "new": '''        "n_qualified": sum(1 for r in rows if r["hard"]),
        "probe_clones_dropped": cloned,
        "entries": entries,''',
    },
    {
        "id": "P10-报错文本补一句",
        "file": "engine/shortlist.py",
        "old": '"邻域探针（名字含 __）照常计入所在组 N，但不参与入围排名"\n                "（rules.md 5.2 第 3.2 版）。",',
        "new": '"邻域探针（名字含 __）照常计入所在组 N，但不参与入围排名"\n                "（rules.md 5.2 第 3.2 版）；与已有探针结构相同的「改名副本」同样剔除"\n                f"（本次剔除 {len(cloned)} 个，见 probe_clones_dropped）。",',
    },
    # ---------------------------------------------------------------- P11
    {
        "id": "P11-农场完成度按台账算",
        "file": "engine/funnel.py",
        "old": '''        tie_note = ("（当前台账中仅有以上 seed 的农场结果；"
                    if n_farm < 20 else
                    "（20 只种子全部完成；")
        lines.append(tie_note + f"farm JSON 共 {n_farm} 份）")''',
        "new": '''        # P11：不许把"有 JSON"说成"全部完成"。按台账统计每个种子缺成功结果的配置数。
        missing: dict[int, int] = {}
        try:
            _led = read_ledger()
            _ok = set(_led.loc[_led["status"].astype(str) == "ok", "config"])
            for _p in farm_files:
                _j = json.loads(_p.read_text(encoding="utf-8"))
                _miss = [c for c in _j.get("base", []) if c not in _ok]
                if _miss:
                    missing[int(_j["seed"])] = len(_miss)
        except Exception:                        # noqa: BLE001
            missing = {}
        if missing:
            detail = "、".join(f"seed {k}（{v} 个配置无成功结果）" for k, v in sorted(missing.items()))
            lines.append(f"（{n_farm} 份 farm JSON，但**并非全部完成**：{detail}；"
                         "失败行保留在台账，按 rules.md 第 10 章只重试未成功任务）")
        else:
            lines.append(f"（{n_farm} 份 farm JSON，全部种子的基础配置都有成功结果）")''',
    },
]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="应用 v2.1 判定层补丁（幂等）")
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
    print(f"\n共 {len(PATCHES)} 处补丁：本次应用 {sum(1 for r in rows if r[1] == '已应用')}，"
          f"失败 {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

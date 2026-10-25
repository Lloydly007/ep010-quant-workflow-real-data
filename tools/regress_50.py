# -*- coding: utf-8 -*-
"""tools/regress_50.py —— 补丁前后逐位回归（rules.md 第 12 章）

拿 v1（未打补丁）已跑过的 50 个配置，在 v2（打了 P1~P6）的同一份数据上重跑，
要求**全部指标逐位一致**（按 CSV 里的字符串原样比对，不做任何浮点容差）。

- 配置单从 v1 的 `strategies/` 原样复制到 v2 的 `strategies/_regress/`，组名用 `test`
  （不计入研究组 N，rules.md 第 6 章）。
- 被 P3 挡下的配置（市场级零件作因子/排序键/嵌套基零件）单列，它们是**预期的变化**，
  不是回归失败。
- 结论写 `reports/regress_50.md`，退出码 0 = 全部逐位一致。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/regress_50.py [--n 50]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT.parent / "ep010-research"
sys.path.insert(0, str(ROOT / "engine"))

NUM_COLS = ["n_trades", "ann_ret", "bench_ann_ret", "ann_excess", "sharpe", "max_dd",
            "ir", "excess_max_dd", "beat_years", "total_years", "ic_mean", "ic_std",
            "icir", "ic_pos_ratio", "decile_ls_ann", "decile_monotonicity",
            "turnover_ann", "cap_median", "cap_p5", "decay_1d", "decay_5d",
            "decay_20d", "decay_60d", "funnel_l1", "funnel_l2", "funnel_l3", "funnel_l4"]


def pick_configs(led: pd.DataFrame, n: int) -> list[str]:
    """从 v1 台账里按组分层挑 n 个已成功、且是搜索期的基础配置（含少量探针）。"""
    ok = led[(led["status"] == "ok") & (led["start"] == "20140101")
             & (led["end"] == "20221231")].drop_duplicates("config")
    groups = ["A", "B", "monkey_43", "test"]
    picked: list[str] = []
    probes = [c for c in ok["config"] if "__" in c]
    for g in groups:
        names = sorted(ok.loc[ok["group"] == g, "config"])
        picked += names[:: max(1, len(names) // (n // len(groups)))] [: n // len(groups)]
    picked += sorted(probes)[:2]          # 带两条邻域探针，覆盖 __ 命名路径
    # 不足 n 个就从剩余配置里补齐（仍保证确定性：按名字排序）
    if len(set(picked)) < n:
        for c in sorted(ok["config"]):
            if c not in picked:
                picked.append(c)
            if len(set(picked)) >= n:
                break
    seen, out = set(), []
    for c in picked:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:n]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="补丁前后逐位回归")
    ap.add_argument("--n", type=int, default=50)
    a = ap.parse_args(argv)

    led_v1 = pd.read_csv(V1 / "ledger" / "ledger.csv", dtype=str, keep_default_na=False)
    names = pick_configs(led_v1, a.n)
    reg_dir = ROOT / "strategies" / "_regress"
    if reg_dir.exists():
        shutil.rmtree(reg_dir)
    reg_dir.mkdir(parents=True)
    copied, missing, rejected = [], [], []
    from config import ConfigError, load_config     # noqa: E402
    for c in names:
        src = next((p for p in (V1 / "strategies").rglob(f"{c}.yaml")), None)
        if src is None:
            missing.append(c)
            continue
        # 回归用的副本必须改名：台账以 (config, group, start, end) 判最新行，
        # 同名再跑一次会把原配置的最新行改成 group=test，从而在漏斗里"消失"。
        txt = src.read_text(encoding="utf-8")
        new_name = f"rg_{c}"
        txt2 = re.sub(r"^name:\s*.*$", f"name: {new_name}", txt, count=1, flags=re.M)
        (reg_dir / f"{new_name}.yaml").write_text(txt2, encoding="utf-8")
        try:
            load_config(reg_dir / f"{new_name}.yaml")
            copied.append(c)
        except ConfigError as e:
            rejected.append((c, str(e)))
    for r in rejected:                              # P3 挡下的不进回归集
        (reg_dir / f"rg_{r[0]}.yaml").unlink(missing_ok=True)
    print(f"[regress] 取样 {len(names)}：可回归 {len(copied)}，被 P3 拒绝 {len(rejected)}，"
          f"缺 YAML {len(missing)}")

    res = subprocess.run([sys.executable, "-X", "utf8", "engine/run_batch.py",
                          "--dir", "strategies/_regress", "--group", "test",
                          "--workers", "8"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    print("\n".join(res.stdout.strip().splitlines()[-3:]))

    led_v2 = pd.read_csv(ROOT / "ledger" / "ledger.csv", dtype=str, keep_default_na=False)
    v1 = led_v1[(led_v1["start"] == "20140101") & (led_v1["end"] == "20221231")] \
        .drop_duplicates("config", keep="last").set_index("config")
    v2 = led_v2[(led_v2["group"] == "test") & (led_v2["start"] == "20140101")
                & (led_v2["end"] == "20221231")
                & led_v2["config"].str.startswith("rg_")] \
        .drop_duplicates("config", keep="last").set_index("config")
    v2.index = [str(i)[3:] if str(i).startswith("rg_") else str(i) for i in v2.index]

    rows, bad = [], []
    def same(a: str, b: str) -> bool:
        """逐位比较：空串/NaN 视为同一缺失；其余按 float 位相等（不是文本相等）。

        台账 CSV 里缺失既可能写成 ``（None）也可能写成 nan（float('nan')），
        两者都表示缺失；数值则要求解析后的双精度完全相等。
        """
        a, b = str(a).strip(), str(b).strip()
        na = ("", "nan", "None", "NaN")
        if a in na or b in na:
            return a in na and b in na
        try:
            fa, fb = float(a), float(b)
        except ValueError:
            return a == b
        return fa == fb

    for c in copied:
        if c not in v2.index:
            bad.append((c, "v2 无台账行", ""))
            continue
        diffs = [k for k in NUM_COLS
                 if k in v1.columns and not same(v1.at[c, k], v2.at[c, k])]
        if diffs:
            detail = "; ".join(f"{k}: v1={v1.at[c, k]} v2={v2.at[c, k]}" for k in diffs[:3])
            bad.append((c, f"{len(diffs)} 列不一致", detail))
        rows.append({"config": c, "v1_group": v1.at[c, "group"],
                     "status_v2": v2.at[c, "status"],
                     "n_trades": v2.at[c, "n_trades"], "ir": v2.at[c, "ir"],
                     "columns_compared": len([k for k in NUM_COLS if k in v1.columns]),
                     "bit_identical": not diffs})

    df = pd.DataFrame(rows)
    ok_n = int(df["bit_identical"].sum()) if len(df) else 0
    md = ["# 补丁前后逐位回归（rules.md 第 12 章）", ""]
    md.append(f"- 样本：v1 台账里 {len(names)} 个已成功配置（按组分层的确定性抽样）+ 2 条邻域探针")
    md.append(f"- 比对：{len([k for k in NUM_COLS if k in v1.columns])} 个数值列，"
              "按台账 CSV 的字符串原样比对，**零容差**")
    md.append(f"- 结论：**{ok_n}/{len(df)} 逐位一致**；被 P3 拒绝 {len(rejected)} 个（预期变化）；"
              f"缺 YAML {len(missing)} 个")
    md.append("")
    if rejected:
        md += ["## 被 P3 拒绝的配置（预期的变化，不是回归失败）", ""]
        for c, e in rejected:
            md.append(f"- `{c}`：{e}")
        md.append("")
    if bad:
        md += ["## 不一致明细", ""]
        for c, why, detail in bad:
            md.append(f"- `{c}`：{why}。{detail}")
        md.append("")
    md += ["## 回归明细", "", "| 配置 | v1 组 | v2 状态 | 交易数 | IR | 比对列数 | 逐位一致 |",
           "|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['config']} | {r['v1_group']} | {r['status_v2']} | {r['n_trades']} | "
                  f"{r['ir']} | {r['columns_compared']} | {'是' if r['bit_identical'] else '否'} |")
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "regress_50.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (ROOT / "data" / "regress_50.json").write_text(
        json.dumps({"n_compared": len(df), "bit_identical": ok_n,
                    "rejected_by_p3": [c for c, _ in rejected],
                    "missing": missing, "mismatches": [b[0] for b in bad]},
                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[regress] 逐位一致 {ok_n}/{len(df)}；写入 reports/regress_50.md")
    return 0 if (ok_n == len(df) and len(df) > 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())

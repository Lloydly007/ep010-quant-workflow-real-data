r"""报告数字核对：把 研究结果.md 里写的关键数字，逐条回源到 JSON/台账。

本次研究最大的风险不是算错，而是**报告与产物漂移**：改了一遍流程，报告里的
数字没跟着改。这个脚本就是那道机器门。

用法：
  python tools/verify_report.py            # 核对，全过 exit 0，有差异 exit 1
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import meta  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "研究结果.md"


def load_json(rel: str) -> dict:
    p = ROOT / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def ledger() -> pd.DataFrame:
    d = pd.read_csv(ROOT / "ledger" / "ledger.csv")
    d = d[d["group"].astype(str) != "test"]           # test 不计入研究组 N（rules.md）
    d = d.sort_values("ts").drop_duplicates(subset=["config", "start", "end"], keep="last")
    d["config"] = d["config"].astype(str)
    d["group"] = d["group"].astype(str)
    return d


def main() -> int:
    if not REPORT.exists():
        print("[verify] 报告不存在")
        return 1
    text = REPORT.read_text(encoding="utf-8").replace("\u2212", "-").replace("\uff0d", "-")  # 统一负号
    d = ledger()
    layers = load_json("data/funnel_layers.json")
    sealed = load_json("data/sealed_eval.json")
    ok, bad = [], []

    def chk(name: str, cond: bool, detail: str = "") -> None:
        (ok if cond else bad).append(f"{name} {detail}")

    # ---- 1. 漏斗数字
    tracks = (layers.get("tracks") or {})
    for t in ("A", "B"):
        payload = tracks.get(t) or {}
        layers_map = payload.get("layers", payload) if isinstance(payload, dict) else payload
        for k in ("l1", "l2", "l6", "l7", "l8"):
            v = layers_map.get(k)
            n = len(v) if isinstance(v, list) else v
            if n is None:
                continue
            # 报告里该轨道的表格行应出现这个数字
            chk(f"漏斗 {t}.{k.upper()}", str(int(n)) in text, f"(产物 {n})")

    # ---- 2. L2 通过率（score 型 vs 全体）
    ai = d[(d["group"].isin(meta.AI_GROUPS)) & (d["status"] == "ok")]
    base = ai[~ai["config"].str.contains("__")]
    score = base[base["config"].str.match(r"^[ab]_r[3-6]_")]
    for arm in ("A", "B"):
        x = score[score["group"] == arm]
        if len(x):
            rate = (x["funnel_l2"] == 1).mean() * 100
            chk(f"score 型 {arm} 路 L2 率 {rate:.1f}%", f"{rate:.1f}%" in text, "")
    mon = d[d["group"].str.startswith("monkey") & (d["status"] == "ok")]
    if len(mon):
        rate = (mon["funnel_l2"] == 1).mean() * 100
        chk(f"随机 L2 率 {rate:.1f}%", f"{rate:.1f}%" in text, "")

    # ---- 3. 封存期数字
    groups = (sealed.get("groups") or {})
    for g, payload in groups.items():
        for name, it in (payload.get("candidates") or {}).items():
            if not isinstance(it, dict):
                continue
            ann = float(it.get("ann_ret") or 0) * 100
            chk(f"封存 {name} 年化 {ann:.2f}%", f"{ann:.2f}%" in text, "")
    pf = ((groups.get("AI") or {}).get("portfolio") or {}).get("sealed") or {}
    pfd = pf.get("portfolio") or {}
    if pfd:
        chk("AI 组合年化", f"{float(pfd.get('ann_ret', 0))*100:.2f}%" in text,
            f"(产物 {float(pfd.get('ann_ret', 0))*100:.2f}%)")

    # ---- 4. 封存窗口天数（424 / 436 不许混）
    chk("报告写了 424 个交易日", "424 个交易日" in text, "")
    if "436 个交易日" in text:
        chk("436 只出现在组合语境", "组合因 ETF 数据延长" in text, "")

    # ---- 5. 基准不能混名
    chk("未把 510300 说成池等权", "510300 池等权" not in text, "")

    # ---- 6. 三席相关性
    if "0.992" not in text:
        bad.append("三席相关性结论缺失")

    # ---- 输出
    print(f"[verify] 通过 {len(ok)} 项")
    for b in bad:
        print(f"  ✗ {b}")
    if bad:
        print(f"[verify] 有 {len(bad)} 项与产物不一致")
        return 1
    print("[verify] 报告数字与产物一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())

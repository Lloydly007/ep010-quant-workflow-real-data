# -*- coding: utf-8 -*-
"""
engine/gates.py —— 把"研究纪律"变成代码闸门（会被 run_batch / sealed_eval 调用）

为什么需要它：本项目第 1~2 轮 10 个 agent 全部把策略写成 rule 型（买卖规则），
而原项目 92%~98% 是 score 型（横截面打分选股）。结果 A 路 L2 通过率 0%~6%，
两轮 200 份配置作废。当时流程写在文档里，没有任何东西强制它——
**跳过不报错，跑完才发现**。

本模块提供两个门：

1. `require_form_gate(dir)`：配置目录若属于 strategies/{A,B}/roundN，
   要求 score 型占比 ≥ 阈值，否则拒绝回测（可用 --force-form 显式绕过并留痕）。
2. `freeze_matches()`：开封前必须先把名单冻结成 SHA256；开封时校验名单没被改。

所有门只读文件、不写台账，失败时返回非零码而不是抛异常，便于 CLI 处理。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FREEZE_PATH = ROOT / "reports" / "名单冻结.json"

# 目标形态：score 型占比下限。研究口径见 docs/因子清单_真实数据.md 的「口径修正」。
FORM_MIN_SCORE = 0.80
ROUND_RE = re.compile(r"strategies[\\/]([AB])[\\/]round(\d+)$", re.I)


def form_ratio(cfg_dir: Path) -> tuple[int, int, dict[str, int]]:
    """返回 (score 份数, 总份数, 分布)。解析失败的文件计入 'unparsable'。"""
    files = sorted([p for p in cfg_dir.iterdir() if p.suffix.lower() in (".yaml", ".yml")])
    dist: dict[str, int] = {}
    for p in files:
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            k = str(raw.get("type", "missing"))
        except Exception:                                # noqa: BLE001
            k = "unparsable"
        dist[k] = dist.get(k, 0) + 1
    return dist.get("score", 0), len(files), dist


def require_form_gate(cfg_dir: Path, min_score: float = FORM_MIN_SCORE,
                      force: bool = False) -> tuple[int, str]:
    """只对 strategies/{A,B}/roundN 生效；返回 (退出码, 说明)。"""
    m = ROUND_RE.search(str(cfg_dir).replace("/", "\\"))
    if not m:
        return 0, ""
    arm, rnd = m.group(1).upper(), m.group(2)
    n_score, n_total, dist = form_ratio(cfg_dir)
    if n_total == 0:
        return 0, ""
    ratio = n_score / n_total
    if ratio >= min_score:
        return 0, f"[gate] 形态门通过：{arm}/round{rnd} score {n_score}/{n_total} = {ratio*100:.0f}%"
    msg = (f"[gate] 形态门未通过：{arm}/round{rnd} score {n_score}/{n_total} = {ratio*100:.0f}%"
           f"（门槛 {min_score*100:.0f}%，分布 {dist}）")
    if force:
        return 0, msg + "  —— 已用 --force-form 显式绕过，本次结果须在报告里标注为非常规形态"
    return 3, msg + "  —— 拒绝回测。先重写配置单，或确认要绕过时加 --force-form"


def sha256_of(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_freeze(groups: tuple[tuple[str, str], ...] = (("AI", "data/shortlist_AI.json"),
                                                        ("monkey_43", "data/shortlist_monkey_43.json"))) -> dict:
    """开封前调用：把当前入围名单与哈希写成冻结记录。"""
    rec: dict = {"frozen_at": None, "note": "名单冻结：开封前记录，开封后不得修改", "groups": {}}
    import datetime
    rec["frozen_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    for g, rel in groups:
        p = ROOT / rel
        if not p.exists():
            rec["groups"][g] = {"file": rel, "missing": True}
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        rec["groups"][g] = {"file": rel, "names": d.get("shortlist", []), "sha256": sha256_of(p)}
    FREEZE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FREEZE_PATH.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def freeze_matches() -> tuple[bool, str]:
    """开封前校验：冻结记录存在，且当前名单哈希与冻结时一致。"""
    if not FREEZE_PATH.exists():
        return False, f"没有冻结记录 {FREEZE_PATH.name}；先运行 python tools/pipeline.py freeze"
    rec = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    for g, info in (rec.get("groups") or {}).items():
        if info.get("missing"):
            return False, f"{g} 在冻结时数据缺失"
        p = ROOT / info["file"]
        if not p.exists():
            return False, f"{g} 的名单文件不见了：{info['file']}"
        now = sha256_of(p)
        if now != info.get("sha256"):
            return False, (f"{g} 的名单在冻结后被改过（{info['sha256'][:12]}… → {now[:12]}…）；"
                           f"开封前不允许改名单，先回滚")
    return True, "冻结记录有效，名单未被改动"

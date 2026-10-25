# -*- coding: utf-8 -*-
"""校验 strategies/A/round3 下 a_r3_s4_* 全部配置单（A 路第 4 组 / 路径与波动）。

检查项：load_config 通过、type=score、holdings=30、rebalance 合法、neut_industry=true、
无 rule 专有键、只用零件白名单（禁死列 / 禁 etf_above_ma_n / 禁 circ_mv）、
至少一个带 n 的因子（否则 L5 邻域为 0）、size_ln 负权、vol_n|ulcer_n 至少一个负权、
build_neighbor_set 非空、desc 一句中文且不引用 2023+、因子规格无重复。
用法： python tools/check_a_r3_s4.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

import yaml  # noqa: E402

from config import ALLOWED_WINDOWS, load_config  # noqa: E402
from funnel import build_neighbor_set  # noqa: E402

D = ROOT / "strategies" / "A" / "round3"
BANNED = {"roe", "or_yoy", "netprofit_yoy", "fc_type_code", "fc_chg_mid", "fc_days",
          "ex_yoy", "ex_days", "ind_median_fc_chg_mid", "inst_netbuy", "margin_ratio",
          "margin_chg_n", "hk_ratio", "hk_chg_n", "fc_demean_ind", "top_list_n",
          "etf_above_ma_n", "circ_mv"}
RULE_KEYS = {"buy", "sell", "rank", "max_hold_days", "stop_loss", "max_positions"}
WHITELIST = {"size_ln", "pb", "ps_ttm", "pe_ttm", "turn_ma_n", "vol_n", "ret_n",
             "close_over_ma_n", "ts_pct", "xsec_pct", "ind_rank", "ulcer_n"}


def main() -> int:
    files = sorted(D.glob("a_r3_s4_*.yaml"))
    fail = 0
    rows = []
    sigs: dict[str, list[str]] = {}
    for p in files:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        try:
            c = load_config(p)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL-CONFIG {p.name}: {e}")
            fail += 1
            continue
        errs = []
        if c["type"] != "score":
            errs.append("type!=score")
        if c["holdings"] != 30:
            errs.append("holdings!=30")
        if c["rebalance"] not in ("weekly_first_trade_day", "monthly_first_trade_day"):
            errs.append("rebalance")
        if not c["neut_industry"]:
            errs.append("neut_industry!=true")
        if RULE_KEYS & set(raw):
            errs.append(f"rule keys {sorted(RULE_KEYS & set(raw))}")
        for fd in c["factors"]:
            if fd["op"] in BANNED:
                errs.append(f"banned op {fd['op']}")
            if fd["op"] not in WHITELIST:
                errs.append(f"off-whitelist op {fd['op']}")
            base = fd.get("of") or {}
            if base:
                if base.get("op") in BANNED:
                    errs.append(f"banned of {base['op']}")
                if base.get("op") not in WHITELIST:
                    errs.append(f"off-whitelist of {base['op']}")
        has_n = any(fd.get("n") in ALLOWED_WINDOWS
                    or (fd.get("of") or {}).get("n") in ALLOWED_WINDOWS
                    for fd in c["factors"])
        if not has_n:
            errs.append("no window factor -> L5 empty")
        sz = [fd["weight"] for fd in c["factors"] if fd["op"] == "size_ln"]
        if not sz or any(w >= 0 for w in sz):
            errs.append("size_ln missing/positive")
        risk = [fd["weight"] for fd in c["factors"]
                if fd["op"] in ("vol_n", "ulcer_n")
                or (fd.get("of") or {}).get("op") in ("vol_n", "ulcer_n")]
        if not risk:
            errs.append("no vol_n/ulcer_n factor")
        elif all(w > 0 for w in risk):
            errs.append("vol/ulcer not negatively weighted")
        nb = build_neighbor_set(raw)
        if not nb:
            errs.append("L5 neighbors == 0")
        d = raw.get("desc", "")
        if not d or d[-1] not in "。":
            errs.append("desc not a sentence")
        for bad in ("2023", "2024", "2025", "验证期", "封存"):
            if bad in d:
                errs.append(f"desc mentions {bad}")
        sig = json.dumps(
            [[fd["op"], fd.get("n"), (fd.get("of") or {}).get("op"),
              (fd.get("of") or {}).get("n"), fd["weight"]] for fd in c["factors"]],
            ensure_ascii=False)
        sigs.setdefault(sig, []).append(p.name)
        rows.append((p.name, c["rebalance"], len(c["factors"]), len(nb)))
        if errs:
            fail += 1
        print(f"{'OK ' if not errs else 'BAD'} {p.name:38s} "
              f"reb={c['rebalance'][:7]:7s} neut_sz={str(c['neut_size']):5s} "
              f"nf={len(c['factors'])} neighbors={len(nb):2d} "
              + ("; ".join(errs)))

    print()
    print(f"files={len(files)} fail={fail}")
    dup = {k: v for k, v in sigs.items() if len(v) > 1}
    print("duplicate factor-spec groups:", dup if dup else "none")
    print("neighbor total:", sum(r[3] for r in rows),
          "min:", min(r[3] for r in rows), "max:", max(r[3] for r in rows))
    print("weekly:", sum(1 for r in rows if r[1].startswith("weekly")),
          "monthly:", sum(1 for r in rows if r[1].startswith("monthly")))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())

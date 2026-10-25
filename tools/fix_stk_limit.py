r"""修正 stk_limit：把「一律 ±10%」的派生值改成按板块档位。

为什么要修
----------
`engine/backtest.py` 第 5~6 行写明：涨跌停价直接用供应商 `up_limit/down_limit`，
**不自己推算**（rules.md 第 2 节）。本研究拿不到 Tushare 的 stk_limit，改成派生，
但原先一律用「前收 ±10%」，对以下两类是错的：

  * 创业板(300/301)、科创板(688/689)：**±20%**（创业板 2020-08-24 起改 20%）
  * ST 股：**±5%**

后果：引擎把「涨了 11%」当成涨停而拒买、「跌了 11%」当成跌停而拒卖，
相当于系统性地屏蔽了双创板的大幅波动日。

本脚本按档位重算并覆盖 data/{raw,sealed}/stk_limit.parquet，原文件备份为
stk_limit_legacy.parquet（旧口径：一律 ±10%），便于做修正前后对照。

用法：
  python tools/fix_stk_limit.py            # 重算并覆盖
  python tools/fix_stk_limit.py --dry-run  # 只统计受影响行数
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
GEM_REFORM = "20200824"          # 创业板涨跌幅 10% → 20%


def band_of(code: str, is_st: bool, date: str) -> float:
    """返回该股票该日的涨跌幅档位（0.10 / 0.20 / 0.05 / 0.30）。

    注意 BaoStock 的代码格式是 `sz.300010`，数字在点号**后面**。
    """
    num = code.split(".")[-1]
    if is_st:
        return 0.05
    if num.startswith(("688", "689")):
        return 0.20
    if num.startswith(("300", "301")):
        return 0.20 if date >= GEM_REFORM else 0.10
    if num.startswith(("8", "4", "92")):          # 北交所
        return 0.30
    return 0.10


def st_keys(base: Path) -> set[tuple[str, str]]:
    """从 namechange 反推 ST 日期集合（(ts_code, YYYYMMDD)）。"""
    p = base / "namechange.parquet"
    if not p.exists():
        return set()
    d = pd.read_parquet(p)
    d = d[d["name"].astype(str).str.contains("ST", na=False)]
    keys: set[tuple[str, str]] = set()
    for _, r in d.iterrows():
        s = str(r["start_date"]).replace("-", "")[:8]
        e = str(r["end_date"]).replace("-", "")[:8]
        if not (len(s) == 8 and s.isdigit()):
            continue
        if not (len(e) == 8 and e.isdigit()):
            e = "20991231"
        if e < s:
            s, e = e, s
        days = pd.date_range(s, e, freq="D")
        for day in days.strftime("%Y%m%d"):
            keys.add((str(r["ts_code"]), day))
    return keys


def r2(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build(side: str, dry: bool) -> dict:
    base = DATA / side
    daily = pd.read_parquet(base / "daily.parquet",
                            columns=["ts_code", "trade_date", "pre_close", "close"])
    lim = pd.read_parquet(base / "stk_limit.parquet")
    lim["ts_code"] = lim["ts_code"].astype(str)
    lim["trade_date"] = lim["trade_date"].astype(str)

    merged = lim.merge(daily, on=["ts_code", "trade_date"], how="left", suffixes=("", "_d"))
    # ST 状态由 namechange 的 ST 区间反推（daily/daily_basic 都没落 isST）
    stk = st_keys(base)
    is_st = [(str(c), str(d)) in stk for c, d in
             zip(merged["ts_code"], merged["trade_date"])]
    merged["is_st"] = is_st

    pre = pd.to_numeric(merged["pre_close"], errors="coerce")
    bands = [band_of(str(c), bool(s), str(d))
             for c, s, d in zip(merged["ts_code"], merged["is_st"], merged["trade_date"])]
    merged["band"] = bands
    new_up = [r2(p0 * (1 + b)) if pd.notna(p0) else None for p0, b in zip(pre, bands)]
    new_dn = [r2(p0 * (1 - b)) if pd.notna(p0) else None for p0, b in zip(pre, bands)]

    old_up = pd.to_numeric(merged["up_limit"], errors="coerce")
    diff = pd.Series(new_up) - old_up
    changed = int((diff.abs() > 0.005).sum())
    stat = {
        "side": side,
        "rows": len(merged),
        "changed": changed,
        "changed_pct": round(changed / max(len(merged), 1) * 100, 1),
        "band_20": sum(1 for b in bands if b == 0.20),
        "band_10": sum(1 for b in bands if b == 0.10),
        "band_5": sum(1 for b in bands if b == 0.05),
        "pre_close_missing": int(pre.isna().sum()),
    }

    if not dry:
        legacy = base / "stk_limit_legacy.parquet"
        if not legacy.exists():
            lim.to_parquet(legacy, index=False)
        out = merged[["ts_code", "trade_date", "up_limit", "down_limit", "pre_close",
                      "band"]].copy()
        out["up_limit"] = new_up
        out["down_limit"] = new_dn
        out.drop(columns=["pre_close"]).to_parquet(base / "stk_limit.parquet", index=False)
    return stat


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    for side in ("raw", "sealed"):
        if not (DATA / side / "stk_limit.parquet").exists():
            print(f"[fix] 跳过 {side}（无 stk_limit）")
            continue
        st = build(side, a.dry_run)
        print(f"[fix] {st['side']}: {st['rows']:,} 行，"
              f"档位变化 {st['changed']:,} 行（{st['changed_pct']}%）；"
              f"20%档 {st['band_20']:,}、10%档 {st['band_10']:,}、5%档 {st['band_5']:,}；"
              f"pre_close 缺失 {st['pre_close_missing']}")

    if a.dry_run:
        print("[fix] --dry-run，未写盘")
        return 0
    cache = DATA.parent / "cache"
    if cache.exists():
        removed = 0
        for f in cache.glob("panel*"):
            f.unlink(missing_ok=True)
            removed += 1
        print(f"[fix] 已清除面板缓存 {removed} 个文件（下次回测会重建）")
    print("[fix] 完成。旧口径备份为 stk_limit_legacy.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())

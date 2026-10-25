r"""补业绩预告：akshare 东财业绩预告 → engine 的 forecast 表。

引擎需要的列：forecast: ts_code, ann_date, end_date, type, p_change_min, p_change_max
东财接口给的：预告类型（预增/预减/首亏…）、业绩变动幅度（单值 %）、公告日期。

口径：
  * p_change_min = p_change_max = 业绩变动幅度（接口只给一个幅度，不拆区间）；
  * 同一 (ts_code, end_date) 保留**公告日最早**的一条（首次预告，避免用修正稿）；
  * 按 ann_date >= 20250101 切 raw / sealed。

用法：python tools/fetch_forecast.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEALED_MIN = "20250101"


def to_ts_code(c: str) -> str:
    s = str(c).zfill(6)
    if s[0] in "69":
        return f"sh.{s}"
    if s[0] in "03":
        return f"sz.{s}"
    return f"bj.{s}"


def quarters() -> list[str]:
    return [f"{y}{m}" for y in range(2014, 2027) for m in ("0331", "0630", "0930", "1231")
            if f"{y}{m}" <= "20260630"]


def main() -> int:
    import akshare as ak

    qs = quarters()
    print(f"[fc] {len(qs)} 个报告期", flush=True)
    parts, fails = [], []
    t0 = time.time()
    for i, q in enumerate(qs, 1):
        try:
            d = ak.stock_yjyg_em(date=q)
        except Exception as ex:                          # noqa: BLE001
            fails.append((q, repr(ex)[:60]))
            continue
        if d is None or not len(d):
            continue
        need = {"股票代码", "预告类型", "业绩变动幅度", "公告日期"}
        if not need.issubset(set(d.columns)):
            fails.append((q, f"缺列 {need - set(d.columns)}"))
            continue
        d = d[["股票代码", "预告类型", "业绩变动幅度", "公告日期"]].copy()
        d["end_date"] = q
        parts.append(d)
        if i % 10 == 0 or i == len(qs):
            print(f"[fc] {i}/{len(qs)} 累计 {sum(len(x) for x in parts):,} 行 "
                  f"{time.time()-t0:.0f}s", flush=True)

    if not parts:
        print("[fc] 一行都没拿到")
        return 2

    d = pd.concat(parts, ignore_index=True)
    d["ts_code"] = d["股票代码"].map(to_ts_code)
    d["ann_date"] = pd.to_datetime(d["公告日期"], errors="coerce").dt.strftime("%Y%m%d")
    d = d.dropna(subset=["ann_date"])
    d["type"] = d["预告类型"].astype(str)
    d["chg"] = pd.to_numeric(d["业绩变动幅度"], errors="coerce")
    d["p_change_min"] = d["chg"]
    d["p_change_max"] = d["chg"]
    d["end_date"] = d["end_date"].astype(str)
    d = d.sort_values(["ts_code", "end_date", "ann_date"])
    d = d.drop_duplicates(subset=["ts_code", "end_date"], keep="first")
    out_cols = ["ts_code", "ann_date", "end_date", "type", "p_change_min", "p_change_max"]
    d = d[out_cols].reset_index(drop=True)

    mask = d["ann_date"] >= SEALED_MIN
    for side, sub in (("raw", d[~mask]), ("sealed", d[mask])):
        (DATA / side).mkdir(parents=True, exist_ok=True)
        sub.to_parquet(DATA / side / "forecast.parquet", index=False)
        print(f"[fc] {side}/forecast.parquet：{len(sub):,} 行 / "
              f"{sub['ts_code'].nunique()} 只 / {sub['end_date'].nunique()} 期", flush=True)

    if fails:
        print(f"[fc] {len(fails)} 期失败，前 3：{fails[:3]}")
    print(f"[fc] 完成，用时 {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

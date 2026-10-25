r"""补财务指标：akshare 东财业绩报表 → engine 的 fina_indicator 表。

为什么用它
----------
引擎的 `roe` 算子要求 **严格按 ann_date 对齐**（engine/prices.py），否则就是
用还没公告的财报做交易（前视偏差）。逐股接口 `stock_financial_analysis_indicator`
只给报告期、不给公告日，只能拍脑袋往后挪；而市场级接口

    ak.stock_yjbb_em(date="YYYYMMDD")   # 业绩报表，全A一次拿完
    列含：净资产收益率、营业总收入-同比增长、净利润-同比增长、**最新公告日期**

一次 9 秒就能拿到一个报告期全市场的 ROE 与**真实公告日**，约 50 个季度
（2014Q1~2026Q2）≈ 8 分钟。这是目前最干净的一条路。

引擎需要的列（tools/fetch_baostock.py 里的空表定义）：
    fina_indicator: ts_code, ann_date, end_date, roe, or_yoy, netprofit_yoy

口径：
  * 最新公告日期 缺失的行直接丢弃（宁可少，不用假日期）；
  * >=20250101 的公告进 data/sealed，其余进 data/raw；
  * 同一 (ts_code, end_date) 保留公告日最早的一条（首次披露口径）。

用法：
  python tools/fetch_fina.py                 # 2014Q1 ~ 2026Q2
  python tools/fetch_fina.py --start 2024-01-01 --end 2024-12-31
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEALED_MIN = "20250101"
COLMAP = {"股票代码": "code6", "最新公告日期": "ann_date",
          "净资产收益率": "roe", "营业总收入-同比增长": "or_yoy",
          "净利润-同比增长": "netprofit_yoy", "每股收益": "eps",
          "每股净资产": "bps", "销售毛利率": "gross_margin"}


def to_ts_code(c: str) -> str:
    s = str(c).zfill(6)
    if s[0] in "69":
        return f"sh.{s}"
    if s[0] in "03":
        return f"sz.{s}"
    return f"bj.{s}"


def quarters(start: str, end: str) -> list[str]:
    out = []
    for y in range(int(start[:4]), int(end[:4]) + 1):
        for md in ("0331", "0630", "0930", "1231"):
            d = f"{y}{md}"
            if start.replace("-", "") <= d <= end.replace("-", ""):
                out.append(d)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2014-01-01")
    ap.add_argument("--end", default="2026-06-30")
    a = ap.parse_args(argv)

    import akshare as ak

    qs = quarters(a.start, a.end)
    print(f"[fina] {a.start} ~ {a.end}：{len(qs)} 个报告期", flush=True)

    parts, fails = [], []
    t0 = time.time()
    for i, q in enumerate(qs, 1):
        try:
            d = ak.stock_yjbb_em(date=q)
        except Exception as ex:                          # noqa: BLE001
            fails.append((q, repr(ex)[:70]))
            continue
        if d is None or not len(d):
            continue
        keep = [c for c in COLMAP if c in d.columns]
        if "股票代码" not in keep or "最新公告日期" not in keep:
            fails.append((q, "缺关键列"))
            continue
        d = d[keep].rename(columns=COLMAP)
        d["end_date"] = q
        parts.append(d)
        print(f"[fina] {i}/{len(qs)} {q} {len(d):,} 行  {time.time()-t0:.0f}s", flush=True)

    if not parts:
        print("[fina] 一行都没拿到")
        return 2

    d = pd.concat(parts, ignore_index=True)
    d["ts_code"] = d["code6"].map(to_ts_code)
    d["ann_date"] = pd.to_datetime(d["ann_date"], errors="coerce").dt.strftime("%Y%m%d")
    d = d.dropna(subset=["ann_date"])
    for c in ("roe", "or_yoy", "netprofit_yoy"):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d["end_date"] = d["end_date"].astype(str)
    d = d.sort_values(["ts_code", "end_date", "ann_date"])
    d = d.drop_duplicates(subset=["ts_code", "end_date"], keep="first")   # 首次披露
    cols = ["ts_code", "ann_date", "end_date", "roe", "or_yoy", "netprofit_yoy"]
    d = d[[c for c in cols if c in d.columns]].reset_index(drop=True)

    mask = d["ann_date"] >= SEALED_MIN
    for side, sub in (("raw", d[~mask]), ("sealed", d[mask])):
        base = DATA / side
        base.mkdir(parents=True, exist_ok=True)
        sub.to_parquet(base / "fina_indicator.parquet", index=False)
        print(f"[fina] {side}/fina_indicator.parquet：{len(sub):,} 行 / "
              f"{sub['ts_code'].nunique()} 只 / {sub['end_date'].nunique()} 个报告期", flush=True)

    if fails:
        print(f"[fina] {len(fails)} 个报告期失败，前 3：{fails[:3]}")
    print(f"[fina] 完成，用时 {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

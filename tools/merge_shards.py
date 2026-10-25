"""把分片抓取的结果合并回 data/raw 与 data/sealed。

背景：单会话抓 BaoStock 实测 20.5s/股，1545 只要 8.8 小时；改为 8 分片并行后
每片约 5.5s/股、总耗时约 18 分钟。分片各写 data/shard_<i>/{raw,sealed}/，
本脚本按表做并集（同表跨片 concat + 全行去重），覆盖写回 data/raw 与 data/sealed。

两条纪律：
  1. 分片没产出的表（例如 index_members：分片用 --codes-file 跳过了成分快照）
     一律保留 data/raw 里已有的那份，绝不用空表覆盖。
  2. 合并后必须复核：股票数、行数、19 张表齐不齐、sealed 只含 >=20250101。

用法：
  python tools/merge_shards.py --check      # 只体检，不写
  python tools/merge_shards.py              # 合并并写回
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
SEALED = DATA / "sealed"
SEALED_MIN = "20250101"

TABLES = [
    "daily", "daily_basic", "adj_factor", "stk_limit", "stock_basic", "trade_cal",
    "suspend_d", "namechange", "index_members", "index_member_all", "fina_indicator",
    "forecast", "express", "top_list", "top_inst", "margin_detail", "hk_hold",
    "moneyflow_hsgt", "fund_daily", "fund_adj",
]
DATE_COL = {"daily": "trade_date", "daily_basic": "trade_date", "adj_factor": "trade_date",
            "stk_limit": "trade_date", "suspend_d": "trade_date", "index_members": "trade_date",
            "index_member_all": "trade_date", "namechange": "start_date", "trade_cal": "cal_date",
            "fund_daily": "trade_date", "fund_adj": "trade_date"}


def shard_dirs() -> list[Path]:
    return sorted(p for p in DATA.glob("shard_*") if p.is_dir())


def collect(side: str, name: str) -> pd.DataFrame | None:
    """把各分片 side/name.parquet 并起来；一个都没有就返回 None。"""
    parts = []
    for d in shard_dirs():
        f = d / side / f"{name}.parquet"
        if f.exists() and f.stat().st_size > 0:
            df = pd.read_parquet(f)
            if len(df):
                parts.append(df)
    if not parts:
        return None
    out = pd.concat(parts, ignore_index=True)
    return out.drop_duplicates(ignore_index=True)


def report(df: pd.DataFrame | None, name: str, side: str) -> str:
    if df is None:
        return f"{side}/{name}: 分片无产出"
    extra = ""
    if "ts_code" in df.columns:
        extra = f"，股票 {df['ts_code'].nunique()}"
    dcol = DATE_COL.get(name)
    if dcol and dcol in df.columns:
        extra += f"，{df[dcol].min()}~{df[dcol].max()}"
    return f"{side}/{name}: {len(df):,} 行{extra}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只体检不写")
    a = ap.parse_args(argv)

    ds = shard_dirs()
    print(f"[merge] 发现 {len(ds)} 个分片目录：{[d.name for d in ds]}")
    if not ds:
        print("[merge] 没有分片，退出")
        return 1

    merged: dict[tuple[str, str], pd.DataFrame] = {}
    for side in ("raw", "sealed"):
        for name in TABLES:
            df = collect(side, name)
            if df is not None:
                merged[(side, name)] = df
            print("  " + report(df, name, side))

    # ---- 体检
    daily = merged.get(("raw", "daily"))
    if daily is None or not len(daily):
        print("[merge] [FAIL] raw/daily 为空，拒绝合并")
        return 1
    rows, stocks = len(daily), daily["ts_code"].nunique()
    days = daily["trade_date"].nunique()
    print(f"\n[merge] 合并后 raw/daily：{rows:,} 行 / {stocks} 只 / {days} 个交易日 "
          f"（{daily['trade_date'].min()}~{daily['trade_date'].max()}）")

    sealed_daily = merged.get(("sealed", "daily"))
    if sealed_daily is not None and len(sealed_daily):
        leak = sealed_daily[sealed_daily["trade_date"].astype(str) < SEALED_MIN]
        print(f"[merge] sealed/daily：{len(sealed_daily):,} 行 / "
              f"{sealed_daily['ts_code'].nunique()} 只；早于 {SEALED_MIN} 的行 {len(leak)}")
        if len(leak):
            print("[merge] [FAIL] sealed 里混入了非封存期数据，拒绝合并")
            return 1

    if rows < 2_000_000:
        print(f"[merge] [FAIL] 只有 {rows:,} 行，远低于 1545 只应有量级，拒绝合并")
        return 1
    if stocks < 1400:
        print(f"[merge] [FAIL] 只有 {stocks} 只股票（应接近 1545），拒绝合并")
        return 1

    if a.check:
        print("[merge] --check：只体检，未写盘")
        return 0

    # ---- 写回
    print("\n[merge] 写回……")
    old_index_members = RAW / "index_members.parquet"
    keep_idx = pd.read_parquet(old_index_members) if old_index_members.exists() else None

    for (side, name), df in merged.items():
        out_dir = RAW if side == "raw" else SEALED
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.parquet").unlink(missing_ok=True)
        df.to_parquet(out_dir / f"{name}.parquet", index=False)

    # 分片跳过了成分快照：保留原文件
    if keep_idx is not None and len(keep_idx):
        keep_idx.to_parquet(old_index_members, index=False)
        print(f"[merge] 保留原 index_members：{len(keep_idx):,} 行 / "
              f"{keep_idx['con_code'].nunique()} 只成分股")

    # 补空表（分片可能因故没写某张）
    for side, base in (("raw", RAW), ("sealed", SEALED)):
        for name in TABLES:
            p = base / f"{name}.parquet"
            if not p.exists():
                print(f"[merge] [warn] {side}/{name} 缺失，写成 0 行空表（报告须标注不可得）")
                pd.DataFrame({"ts_code": pd.Series(dtype="string"),
                              "trade_date": pd.Series(dtype="string")}).to_parquet(p, index=False)

    manifest = {
        "generator": "tools/fetch_baostock.py + tools/merge_shards.py",
        "real": True,
        "provider": "BaoStock（日线/估值/ST/停牌/成分/行业）+ 新浪（ETF）",
        "split_date": "2024-12-31",
        "research_cutoff": "2026-09-30",
        "universe": "沪深300 ∪ 中证500 月末快照并集（2013-12~2024-12），中证1000 不纳入",
        "shards": len(ds),
        "tables": {},
    }
    for side, base in (("raw", RAW), ("sealed", SEALED)):
        for name in TABLES:
            p = base / f"{name}.parquet"
            if p.exists():
                d = pd.read_parquet(p)
                manifest["tables"][f"{side}/{name}"] = {
                    "rows": int(len(d)),
                    "stocks": int(d["ts_code"].nunique()) if "ts_code" in d.columns else 0,
                }
    (DATA / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"[merge] 完成：raw {len(list(RAW.glob('*.parquet')))} 张表 / "
          f"sealed {len(list(SEALED.glob('*.parquet')))} 张表 / MANIFEST 已写")
    return 0


if __name__ == "__main__":
    sys.exit(main())

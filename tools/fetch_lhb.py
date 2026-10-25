r"""补龙虎榜：akshare 东财龙虎榜明细 → engine 的 top_list 表。

引擎需要（engine/prices.py:439）：
    top_list: ts_code, trade_date, l_amount
    —— l_amount 是「该次上榜的龙虎榜成交额（元）」，用作 inst_netbuy 的分母；
       top_list_n 算子只用 (ts_code, trade_date) 的事件标记，所以只要能上榜就有值。

数据源：ak.stock_lhb_detail_em(start_date, end_date)，一次可取一段区间，
        实测 2.7 秒/10 天，全区间约 150 次调用、约 8 分钟。

注意：
  * 同一股票同一日可能有多条「上榜原因」，全部保留（引擎按 max(l_amount) 取分母）。
  * 代码是 6 位无后缀，按首位补交易所后缀。
  * >=20250101 进 data/sealed，其余进 data/raw（与主流程切分一致）。
  * top_inst（机构席位明细）需要按日接口，约 2,900 次调用，本次不抓，保持空表。

用法：
  python tools/fetch_lhb.py                 # 抓 2014-01-01 ~ 2026-09-30
  python tools/fetch_lhb.py --start 2024-01-01 --end 2024-03-31
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
COLMAP = {"代码": "code6", "上榜日": "trade_date", "龙虎榜成交额": "l_amount",
          "龙虎榜买入额": "l_buy", "龙虎榜卖出额": "l_sell",
          "龙虎榜净买额": "net_amount", "上榜原因": "reason"}


def to_ts_code(code6: str) -> str:
    c = str(code6).zfill(6)
    if c[0] in "69":
        return f"{c}.SH"
    if c[0] in "03":
        return f"{c}.SZ"
    if c[0] in "48":
        return f"{c}.BJ"
    return f"{c}.SH"


def month_ranges(start: str, end: str) -> list[tuple[str, str]]:
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    out, cur = [], s
    while cur <= e:
        nxt = (cur + pd.offsets.MonthEnd(0))
        seg_end = min(nxt, e)
        out.append((cur.strftime("%Y%m%d"), seg_end.strftime("%Y%m%d")))
        cur = seg_end + pd.Timedelta(days=1)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2014-01-01")
    ap.add_argument("--end", default="2026-09-30")
    a = ap.parse_args(argv)

    import akshare as ak

    segs = month_ranges(a.start, a.end)
    print(f"[lhb] {a.start} ~ {a.end}：{len(segs)} 个月度分片", flush=True)

    parts, fails = [], []
    t0 = time.time()
    for i, (s, e) in enumerate(segs, 1):
        try:
            d = ak.stock_lhb_detail_em(start_date=s, end_date=e)
        except Exception as ex:                          # noqa: BLE001
            fails.append((s, e, repr(ex)[:80]))
            continue
        if d is None or not len(d):
            continue
        keep = [c for c in COLMAP if c in d.columns]
        d = d[keep].rename(columns=COLMAP)
        parts.append(d)
        if i % 20 == 0 or i == len(segs):
            print(f"[lhb] {i}/{len(segs)}  累计 {sum(len(x) for x in parts):,} 行  "
                  f"{time.time()-t0:.0f}s  失败 {len(fails)}", flush=True)

    if not parts:
        print("[lhb] 一行都没抓到")
        return 2

    d = pd.concat(parts, ignore_index=True)
    d["ts_code"] = d["code6"].map(to_ts_code)
    d["trade_date"] = pd.to_datetime(d["trade_date"]).dt.strftime("%Y%m%d")
    for c in ("l_amount", "l_buy", "l_sell", "net_amount"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["reason"] = d["reason"].astype(str)
    d = d[["ts_code", "trade_date", "l_amount", "l_buy", "l_sell", "net_amount", "reason"]]
    d = d.drop_duplicates().sort_values(["trade_date", "ts_code"]).reset_index(drop=True)

    mask = d["trade_date"] >= SEALED_MIN
    for side, sub in (("raw", d[~mask]), ("sealed", d[mask])):
        base = DATA / side
        base.mkdir(parents=True, exist_ok=True)
        out = base / "top_list.parquet"
        sub.to_parquet(out, index=False)
        print(f"[lhb] {side}/top_list.parquet：{len(sub):,} 行 / "
              f"{sub['ts_code'].nunique()} 只 / {sub['trade_date'].nunique()} 个交易日", flush=True)

    if fails:
        print(f"[lhb] 有 {len(fails)} 个分片失败，前 3 个：{fails[:3]}")
    print(f"[lhb] 完成，用时 {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

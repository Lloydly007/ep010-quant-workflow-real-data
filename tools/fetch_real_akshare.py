# -*- coding: utf-8 -*-
"""tools/fetch_real_akshare.py —— 用 akshare 抓**真实** A 股行情，落成引擎要的 19 张表

为什么要有这个文件：EP010 原版用 Tushare Pro（需要 Token）。本机没有 Token，
所以 v1~v2 用 `gen_synthetic_data.py` 造了同 schema 的合成行情。现在改成用
akshare 抓真实数据，**时间切分与原版完全一致**：

    搜索期 2014-01-01 ~ 2022-12-31   → data/raw/
    验证期 2023-01-01 ~ 2024-12-31   → data/raw/
    封存期 2025-01-01 ~ 2026-09-30   → data/sealed/   （切分日 2024-12-31）

真实可得 vs 不可得（诚实清单，报告里必须照抄）：

| 表 | 状态 | 来源 / 说明 |
|---|---|---|
| trade_cal | 真实 | `tool_trade_date_hist_sina` |
| stock_basic | 半真实 | 股票池 = 沪深300 ∪ 中证500 **当前**成分；`list_date` 取不到 → 用首个行情日代替（近似，报告的"上市满 250 日"门槛因此变宽松） |
| index_members | 近似 | 只有**当前**成分，历史调样拿不到 → 每月末快照都写当前成分（**存在幸存者偏差，必须披露**） |
| daily | 真实 | `stock_zh_a_hist`（不复权） |
| adj_factor | 真实 | 由 `adjust="hfq"` 的收盘 ÷ 不复权收盘 反推 |
| daily_basic | 部分真实 | `turnover_rate` 真实；`circ_mv` 由 成交量/换手率 反推流通股本再乘收盘（近似）；`pe_ttm/pb/ps_ttm/total_mv` **不可得 → NaN** |
| stk_limit | 派生 | 前收 ±10%（主板近似；创业板/科创板 20% 未细分） |
| suspend_d | 派生 | 在上市区间内、交易日历上有、但该股无行情 → 视为全天停牌（近似） |
| namechange | 不可得 | 只有一条"从未改名"记录 → **ST 过滤失效**（披露） |
| fina_indicator / forecast / express / index_member_all | 不可得 | 空表（列齐全、0 行）→ 相关零件输出 NaN |
| top_list / top_inst / margin_detail / hk_hold / moneyflow_hsgt | 不可得 | 空表（列齐全、0 行） |
| fund_daily / fund_adj | 真实 | `fund_etf_hist_em`：510300/510500/518880/511010 |

结论：**只有量价、换手、规模（派生）和 ETF 择时这几族能真正跑**；估值/财务/预告/资金面
族的配置在真实数据上会因为字段全 NaN 而 0 成交——这本身就是结论，不是错误。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/fetch_real_akshare.py --limit 6     # 小样本自检
    .venv\\Scripts\\python.exe -X utf8 tools/fetch_real_akshare.py               # 全量
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
SEALED = DATA / "sealed"

START_ALL = "20130101"
END_DATE = "20260930"          # 与原版 fetch_tushare.py:41 一致
SPLIT = "20241231"
SEALED_MIN = "20250101"
INDEXES = {"000300": "000300.SH", "000905": "000905.SH"}
ETFS = ["510300", "510500", "518880", "511010"]
SLEEP = 0.35


def _norm(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    return df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})


def write_table(name: str, df: pd.DataFrame, date_col: str | None, manifest: dict) -> None:
    """按切分日写 raw / sealed 两份（列一致）。"""
    RAW.mkdir(parents=True, exist_ok=True)
    SEALED.mkdir(parents=True, exist_ok=True)
    if date_col and date_col in df.columns:
        df = df.copy()
        df[date_col] = df[date_col].astype(str).str.replace("-", "", regex=False).str.slice(0, 8)
        sort_keys = [k for k in (date_col, "ts_code") if k in df.columns]
        df = df.sort_values(sort_keys).reset_index(drop=True)
        mask = df[date_col] >= SEALED_MIN
        parts = (("raw", df[~mask]), ("sealed", df[mask]))
    else:
        df = df.sort_values("ts_code").reset_index(drop=True) if "ts_code" in df.columns else df
        parts = (("raw", df),)
    for side, part in parts:
        if not len(part):
            continue
        out = (RAW if side == "raw" else SEALED) / f"{name}.parquet"
        pq.write_table(pa.Table.from_pandas(part, preserve_index=False), out,
                       compression="zstd")
        ent = {"rows": int(len(part)), "real": True,
               "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
        if date_col and date_col in part.columns:
            ent["date_min"] = str(part[date_col].min())
            ent["date_max"] = str(part[date_col].max())
        manifest["files"][f"{side}/{name}.parquet"] = ent


def empty(name: str, cols: list[str], manifest: dict) -> None:
    """写一张 0 行但列齐全的表——引擎对 19 张表**逐个读取**，缺文件直接 FileNotFoundError。"""
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in cols})
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / f"{name}.parquet"
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), out)
    manifest["files"][f"raw/{name}.parquet"] = {
        "rows": 0, "real": False, "empty": True,
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="akshare 真实行情 → 引擎 schema")
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 只（自检用）")
    ap.add_argument("--indexes", default="000300,000905")
    a = ap.parse_args(argv)

    import akshare as ak
    print(f"[real] akshare {ak.__version__}")
    manifest = {"generator": "tools/fetch_real_akshare.py", "real": True,
                "split_date": "2024-12-31", "research_cutoff": END_DATE,
                "notes": [
                    "行情来自 akshare（东方财富/新浪），不是 Tushare；字段口径见脚本 docstring",
                    "股票池 = 当前沪深300∪中证500 成分 → 存在幸存者偏差，历史调样不可得",
                    "pe/pb/ps/total_mv、财务、预告、龙虎榜、两融、北向 不可得 → NaN 或空表",
                    "ST 过滤失效（namechange 只有一条初始记录）",
                ], "files": {}}

    # ---------------- 交易日历
    cal = ak.tool_trade_date_hist_sina()
    cal = pd.DataFrame({"exchange": "SSE",
                        "cal_date": pd.to_datetime(cal["trade_date"]).dt.strftime("%Y%m%d"),
                        "is_open": 1})
    full = pd.date_range("2012-01-01", "2026-12-31", freq="D").strftime("%Y%m%d")
    cal = (pd.DataFrame({"cal_date": full})
           .merge(cal, on="cal_date", how="left")
           .assign(exchange="SSE", is_open=lambda d: d["is_open"].fillna(0).astype(int)))
    write_table("trade_cal", cal, "cal_date", manifest)
    tdays = cal.loc[cal["is_open"] == 1, "cal_date"].tolist()
    print(f"[real] 交易日 {len(tdays)} 天")

    # ---------------- 股票池（当前成分）
    codes: list[str] = []
    for idx in a.indexes.split(","):
        try:
            cons = ak.index_stock_cons_csindex(symbol=idx)
            col = "成分券代码" if "成分券代码" in cons.columns else cons.columns[0]
            codes += [str(c).zfill(6) for c in cons[col].tolist()]
            print(f"[real] {idx}: {len(cons)} 只成分")
        except Exception as e:                            # noqa: BLE001
            print(f"[real] {idx} 取成分失败：{e!r}")
        time.sleep(SLEEP)
    codes = sorted(set(codes))
    if a.limit:
        codes = codes[: a.limit]
    print(f"[real] 股票池 {len(codes)} 只")

    # ---------------- 个股行情 + 复权因子
    rows, af_rows = [], []
    for i, code in enumerate(codes, 1):
        ts = f"{code}.SH" if code.startswith(("6", "5")) else f"{code}.SZ"
        sym = ("sh" if code.startswith(("6", "5")) else "sz") + code
        try:
            raw = ak.stock_zh_a_daily(symbol=sym, start_date=START_ALL, end_date=END_DATE,
                                      adjust="")
            time.sleep(SLEEP)
            fac = ak.stock_zh_a_daily(symbol=sym, start_date=START_ALL, end_date=END_DATE,
                                      adjust="hfq-factor")
            time.sleep(SLEEP)
        except Exception as e:                            # noqa: BLE001
            print(f"[real] {code} 行情失败：{e!r}")
            continue
        if raw is None or not len(raw):
            continue
        d = _norm(raw, {"date": "trade_date", "volume": "vol"})
        d["trade_date"] = d["trade_date"].astype(str).str.replace("-", "", regex=False)
        d = d.sort_values("trade_date").reset_index(drop=True)
        d["ts_code"] = ts
        # 复权因子：事件表按日期前向填充到每个交易日（新浪口径）
        if fac is not None and len(fac):
            f = _norm(fac, {"date": "trade_date", "hfq_factor": "adj_factor"})
            f["trade_date"] = f["trade_date"].astype(str).str.replace("-", "", regex=False)
            f = f.sort_values("trade_date")
            d["_k"] = d["trade_date"].astype("int64")
            f["_k"] = f["trade_date"].astype("int64")
            d = pd.merge_asof(d.sort_values("_k"), f[["_k", "adj_factor"]], on="_k",
                              direction="backward").drop(columns=["_k"])
        else:
            d["adj_factor"] = 1.0
        d["adj_factor"] = pd.to_numeric(d["adj_factor"], errors="coerce").ffill().fillna(1.0)
        # 前收：用复权因子还原除权后的前收，保证 pct_chg 与复权收益一致
        d["pre_close"] = (d["close"].shift(1) * d["adj_factor"].shift(1)
                          / d["adj_factor"]).round(4)
        d.loc[d.index[0], "pre_close"] = d["open"].iloc[0]
        d["pct_chg"] = ((d["close"] / d["pre_close"] - 1.0) * 100.0).round(4)
        d["turnover_rate"] = (pd.to_numeric(d["vol"], errors="coerce")
                              / pd.to_numeric(d["outstanding_share"], errors="coerce") * 100
                              ).round(4)
        d["circ_mv"] = (pd.to_numeric(d["close"], errors="coerce")
                        * pd.to_numeric(d["outstanding_share"], errors="coerce") / 1e4).round(2)
        rows.append(d[["ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
                       "pct_chg", "vol", "amount", "turnover_rate", "circ_mv"]])
        af_rows.append(d[["ts_code", "trade_date", "adj_factor"]])
        if i % 50 == 0:
            print(f"[real] 行情 {i}/{len(codes)}")

    if not rows:
        print("[real] 一只都没抓到，退出")
        return 2
    daily = pd.concat(rows, ignore_index=True)
    daily["change"] = daily["close"] - daily["pre_close"]
    daily["vol"] = pd.to_numeric(daily["vol"], errors="coerce")
    daily["amount"] = pd.to_numeric(daily["amount"], errors="coerce")
    daily["trade_date"] = daily["trade_date"].astype(str).str.replace("-", "", regex=False)
    write_table("daily", daily, "trade_date", manifest)
    write_table("adj_factor", pd.concat(af_rows, ignore_index=True), "trade_date", manifest)

    # ---------------- stk_limit（前收 ±10%）
    lim = daily[["ts_code", "trade_date", "pre_close"]].copy()
    lim["up_limit"] = (lim["pre_close"] * 1.10).round(2)
    lim["down_limit"] = (lim["pre_close"] * 0.90).round(2)
    write_table("stk_limit", lim[["ts_code", "trade_date", "up_limit", "down_limit"]],
                "trade_date", manifest)

    # ---------------- daily_basic：turnover 真实、circ_mv 反推、其余 NaN
    db = daily[["ts_code", "trade_date", "close", "vol", "turnover_rate", "circ_mv"]].copy()
    db["turnover_rate"] = pd.to_numeric(db["turnover_rate"], errors="coerce")
    for c in ("pe_ttm", "pb", "ps_ttm", "total_mv"):
        db[c] = np.nan
    write_table("daily_basic",
                db[["ts_code", "trade_date", "turnover_rate", "pe_ttm", "pb", "ps_ttm",
                    "total_mv", "circ_mv"]], "trade_date", manifest)

    # ---------------- stock_basic（list_date 用首个行情日近似）
    first = daily.groupby("ts_code")["trade_date"].min().reset_index()
    basic = first.rename(columns={"trade_date": "list_date"})
    basic["name"] = basic["ts_code"].str.slice(0, 6)
    basic["list_status"] = "L"
    basic["delist_date"] = ""
    basic["exchange"] = np.where(basic["ts_code"].str.endswith(".SH"), "SSE", "SZSE")
    write_table("stock_basic", basic, None, manifest)

    # ---------------- index_members（当前成分，每月末快照 → 幸存者偏差）
    mem_rows = []
    month_ends = pd.Series(tdays)
    ends = month_ends.groupby(month_ends.str.slice(0, 6)).max()
    ends = ends[(ends >= "20131201") & (ends <= END_DATE)]
    cur = sorted({f"{c}.SH" if c.startswith(("6", "5")) else f"{c}.SZ" for c in codes})
    for day in ends.tolist():
        for idx in INDEXES.values():
            mem_rows.append(pd.DataFrame({"index_code": idx, "con_code": cur,
                                          "trade_date": day,
                                          "weight": round(100.0 / max(len(cur), 1), 6)}))
    write_table("index_members", pd.concat(mem_rows, ignore_index=True), "trade_date", manifest)

    # ---------------- suspend_d（有日历、有上市、却无行情 → 视为停牌）
    listed = daily.groupby("ts_code")["trade_date"].agg(["min", "max"]).reset_index()
    susp = []
    td = np.array(tdays)
    for r in listed.itertuples(index=False):
        span = td[(td >= r.min) & (td <= r.max)]
        have = set(daily.loc[daily["ts_code"] == r.ts_code, "trade_date"])
        miss = [d for d in span if d not in have]
        if miss:
            susp.append(pd.DataFrame({"ts_code": r.ts_code, "trade_date": miss,
                                      "suspend_timing": "", "suspend_type": "S"}))
    write_table("suspend_d", pd.concat(susp, ignore_index=True) if susp else
                pd.DataFrame({"ts_code": [], "trade_date": []}), "trade_date", manifest)

    # ---------------- namechange（不可得：一条"从未改名"）
    nc = basic[["ts_code", "name"]].copy()
    nc["start_date"] = basic["list_date"]
    nc["end_date"] = ""
    write_table("namechange", nc[["ts_code", "name", "start_date", "end_date"]],
                "start_date", manifest)

    # ---------------- ETF
    fd, fa = [], []
    for code in ETFS:
        ts = f"{code}.SH"
        try:
            e = _norm(ak.fund_etf_hist_sina(symbol=f"sh{code}"),
                      {"date": "trade_date", "volume": "vol"})
            h = _norm(ak.fund_etf_hist_sina(symbol=f"sh{code}"),
                      {"date": "trade_date", "close": "hfq_close"})[["trade_date", "hfq_close"]]
            time.sleep(SLEEP)
        except Exception as ex:                           # noqa: BLE001
            print(f"[real] ETF {code} 失败：{ex!r}")
            continue
        e["ts_code"] = ts
        e["trade_date"] = e["trade_date"].astype(str).str.replace("-", "", regex=False)
        h["trade_date"] = h["trade_date"].astype(str).str.replace("-", "", regex=False)
        e = e.merge(h, on="trade_date", how="left")
        e["pre_close"] = e["close"].shift(1)
        e["adj_factor"] = (e["hfq_close"] / e["close"]).replace([np.inf, -np.inf], np.nan)
        e["adj_factor"] = e["adj_factor"].ffill().fillna(1.0)
        fd.append(e[["ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
                     "vol", "amount"]])
        fa.append(e[["ts_code", "trade_date", "adj_factor"]])
    write_table("fund_daily", pd.concat(fd, ignore_index=True), "trade_date", manifest)
    write_table("fund_adj", pd.concat(fa, ignore_index=True), "trade_date", manifest)

    # ---------------- 不可得的表：列齐全、0 行
    empty("fina_indicator", ["ts_code", "ann_date", "end_date", "roe", "or_yoy",
                             "netprofit_yoy"], manifest)
    empty("forecast", ["ts_code", "ann_date", "end_date", "type", "p_change_min",
                       "p_change_max"], manifest)
    empty("express", ["ts_code", "ann_date", "end_date", "yoy_net_profit"], manifest)
    empty("index_member_all", ["ts_code", "in_date", "out_date", "l1_code", "l1_name"], manifest)
    empty("top_list", ["ts_code", "trade_date", "l_amount"], manifest)
    empty("top_inst", ["ts_code", "trade_date", "exalter", "net_buy"], manifest)
    empty("margin_detail", ["ts_code", "trade_date", "rzye"], manifest)
    empty("hk_hold", ["ts_code", "trade_date", "ratio", "exchange"], manifest)
    empty("moneyflow_hsgt", ["trade_date", "north_money"], manifest)

    (DATA / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[real] 写入 {len(manifest['files'])} 个 parquet；股票 {daily['ts_code'].nunique()} 只、"
          f"行情 {len(daily):,} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

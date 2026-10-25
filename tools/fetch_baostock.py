# -*- coding: utf-8 -*-
"""tools/fetch_baostock.py —— 真实 A 股行情主源：BaoStock（免费、无 Token）

为什么换源
----------
东财接口在本机被代理掐断；新浪能给日线+流通股本，但**没有估值、没有 ST、没有历史成分**。
BaoStock 一次调用就带回 ``turn / peTTM / pbMRQ / psTTM / isST / tradestatus``，
并且能按日期查指数成分（消灭幸存者偏差）。交叉验证见 ``reports/xval_2020_2024.md``：
与新浪 1,212 个重叠交易日，收盘最大差 0.0000、相关 1.000000。

时间切分（与原版 rules.md 第 1 节**逐字一致**，不重划）
----------------------------------------------------
    搜索期 2014-01-01 ~ 2022-12-31   → data/raw/
    验证期 2023-01-01 ~ 2024-12-31   → data/raw/
    封存期 2025-01-01 ~ 2026-09-30   → data/sealed/     （切分日 2024-12-31）

股票池（关键）
--------------
**沪深300 ∪ 中证500 的历史成分并集**：按月末快照查 ``query_hs300_stocks`` /
``query_zz500_stocks``（2013-12 ~ 2026-09），求并集 → 实测 **1,698 只**，
含后来调出与退市的。中证1000 的历史成分 BaoStock 不提供（无 query_zz1000_stocks），
按口径决定**不纳入**，报告须注明。

真实 / 派生 / 不可得
--------------------
| 表 | 状态 |
|---|---|
| trade_cal | 真实（query_trade_dates） |
| stock_basic | 真实（query_stock_basic：ipodate / outDate / status） |
| index_members | 真实（按月快照，含调出调入） |
| daily | 真实（adjustflag=3 不复权） |
| adj_factor | 派生（后复权收盘 ÷ 不复权收盘） |
| daily_basic | 真实 turn / pe_ttm / pb / ps_ttm；circ_mv 由 volume÷turn 反推流通股本再乘收盘 |
| stk_limit | 派生（前收 ±10%） |
| suspend_d | 真实（tradestatus=0 的日子单独记录，daily 里剔除） |
| namechange | **派生**：由 isST 的连续区间反推（真实 ST 状态、近似名称区间） |
| index_member_all | 真实但**证监会行业口径**（非申万），报告须注明 |
| fina_indicator / forecast / express | 不可得（逐股逐季调用成本过高）→ 空表 |
| top_list / top_inst / margin_detail / hk_hold / moneyflow_hsgt | 不可得 → 空表 |
| fund_daily / fund_adj | 新浪 ETF |

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/fetch_baostock.py --limit 30     # 自检
    .venv\\Scripts\\python.exe -X utf8 tools/fetch_baostock.py               # 全量 1,698 只
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

START_ALL = "2013-01-01"
END_DATE = "2026-09-30"
SPLIT = "20241231"
SEALED_MIN = "20250101"
INDEX_CODES = [("hs300", "000300.SH"), ("zz500", "000905.SH")]
ETFS = ["510300", "510500", "518880", "511010"]
FIELDS = ("date,code,open,high,low,close,preclose,volume,amount,turn,"
          "tradestatus,isST,peTTM,pbMRQ,psTTM")
MAX_TRIES = 3


def q(bs, fn, **kw) -> pd.DataFrame:
    """调一个 baoStock 查询，重试 3 次；返回 DataFrame。"""
    last = None
    for _ in range(MAX_TRIES):
        try:
            rs = fn(**kw)
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            if rs.error_code != "0":
                last = rs.error_msg
                time.sleep(0.5)
                continue
            return pd.DataFrame(rows, columns=rs.fields)
        except Exception as e:                          # noqa: BLE001
            last = repr(e)
            time.sleep(0.5)
    print(f"      [warn] 查询失败 {kw}: {last}")
    return pd.DataFrame()


def write_table(name: str, df: pd.DataFrame, date_col: str | None, manifest: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    SEALED.mkdir(parents=True, exist_ok=True)
    if df is None or not len(df):
        out = RAW / f"{name}.parquet"
        pq.write_table(pa.Table.from_pandas(df if df is not None else pd.DataFrame(),
                                            preserve_index=False), out)
        manifest["files"][f"raw/{name}.parquet"] = {
            "rows": 0, "empty": True,
            "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
        return
    if date_col and date_col in df.columns:
        df = df.copy()
        df[date_col] = df[date_col].astype(str).str.replace("-", "", regex=False).str.slice(0, 8)
        keys = [k for k in (date_col, "ts_code") if k in df.columns]
        df = df.sort_values(keys).reset_index(drop=True)
        mask = df[date_col] >= SEALED_MIN
        parts = (("raw", df[~mask]), ("sealed", df[mask]))
    else:
        keys = [k for k in ("ts_code",) if k in df.columns]
        df = df.sort_values(keys).reset_index(drop=True) if keys else df
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


def empty(name: str, cols: list[str], manifest: dict, note: str = "") -> None:
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in cols})
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / f"{name}.parquet"
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), out)
    manifest["files"][f"raw/{name}.parquet"] = {
        "rows": 0, "empty": True, "note": note or "源不可得",
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="BaoStock 真实行情 → 引擎 schema")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-members", action="store_true", help="跳过成分抓取（自检用）")
    ap.add_argument("--codes-file", default="",
                    help="从文本文件读取股票池（每行一个 sh.600000 形式），跳过月末成分快照")
    ap.add_argument("--shard", type=int, default=0, help="分片序号（0 基）")
    ap.add_argument("--nshards", type=int, default=1, help="分片总数；>1 时按 codes[shard::nshards] 切片")
    ap.add_argument("--outdir", default="", help="输出根目录（默认 data/），分片时各写各的")
    ap.add_argument("--bs-ip", default="", help="BaoStock 服务器地址覆盖（走 SSH 隧道时填 127.0.0.1）")
    ap.add_argument("--bs-port", type=int, default=0, help="BaoStock 端口覆盖（隧道本地端口）")
    a = ap.parse_args(argv)

    if a.bs_ip or a.bs_port:
        import baostock.common.contants as _c
        if a.bs_ip:
            _c.BAOSTOCK_SERVER_IP = a.bs_ip
            _c.BAOSTOCK_VIP_SERVER_IP = a.bs_ip
        if a.bs_port:
            _c.BAOSTOCK_SERVER_PORT = a.bs_port
        print(f"[bs] 服务器覆盖为 {a.bs_ip or '(默认)'}:{a.bs_port or '(默认)'}")

    global RAW, SEALED
    if a.outdir:
        RAW = Path(a.outdir).expanduser().resolve() / "raw"
        SEALED = Path(a.outdir).expanduser().resolve() / "sealed"
        RAW.mkdir(parents=True, exist_ok=True)
        SEALED.mkdir(parents=True, exist_ok=True)

    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        print(f"[bs] 登录失败：{lg.error_msg}")
        return 2
    print(f"[bs] 登录成功（{lg.error_code}）")

    manifest = {"generator": "tools/fetch_baostock.py", "real": True,
                "provider": "BaoStock（日线/估值/ST/停牌/成分/行业）+ 新浪（ETF）",
                "split_date": "2024-12-31", "research_cutoff": "2026-09-30",
                "universe": "沪深300 ∪ 中证500 历史成分并集（月末快照），中证1000 不纳入",
                "notes": [
                    "价格/换手/估值(isST,turn,peTTM,pbMRQ,psTTM)为供应商真值",
                    "adj_factor 由后复权收盘 ÷ 不复权收盘派生",
                    "circ_mv 由成交量÷换手率反推流通股本再乘收盘",
                    "stk_limit 为前收 ±10% 的派生值，创业板/科创板 20% 未细分",
                    "namechange 由 isST 连续区间反推（ST 状态真实，名称区间近似）",
                    "行业为证监会口径（非申万）",
                    "fina_indicator / forecast / express / top_list / top_inst / "
                    "margin_detail / hk_hold / moneyflow_hsgt 不可得，为空表",
                ], "files": {}}

    # ---------------- 交易日历
    cal = q(bs, bs.query_trade_dates, start_date="2012-01-01", end_date="2026-12-31")
    if len(cal):
        cal = pd.DataFrame({"exchange": "SSE", "cal_date": cal["calendar_date"],
                            "is_open": pd.to_numeric(cal["is_trading_day"], errors="coerce")
                            .fillna(0).astype(int)})
        write_table("trade_cal", cal, "cal_date", manifest)
        print(f"[bs] 交易日 {int(cal['is_open'].sum())} 天")

    # ---------------- 股票池 + 历史成分（月末快照）
    months = pd.date_range("2013-12-01", "2026-09-30", freq="ME").strftime("%Y-%m-%d")
    mem_rows: list[pd.DataFrame] = []
    pool: set[str] = set()
    if not a.skip_members and not a.codes_file:
        for i, day in enumerate(months, 1):
            for key, code in INDEX_CODES:
                fn = bs.query_hs300_stocks if key == "hs300" else bs.query_zz500_stocks
                df = q(bs, fn, date=day)
                if not len(df):
                    continue
                cons = [str(c) for c in df["code"].tolist()]
                pool |= set(cons)
                mem_rows.append(pd.DataFrame({"index_code": code, "con_code": cons,
                                              "trade_date": day.replace("-", ""),
                                              "weight": round(100.0 / max(len(cons), 1), 6)}))
            if i % 12 == 0:
                print(f"[bs] 成分快照 {i}/{len(months)}，累计股票池 {len(pool)}")
    else:
        df = q(bs, bs.query_hs300_stocks, date="2024-12-31")
        pool = {str(c) for c in df["code"].tolist()}
        print(f"[bs] 自检：仅当前 hs300 {len(pool)} 只，跳过成分表")
    if a.codes_file:
        codes = [ln.strip() for ln in
                 Path(a.codes_file).read_text(encoding="utf-8").splitlines() if ln.strip()]
        print(f"[bs] 股票池来自文件：{len(codes)} 只（跳过成分快照）")
    else:
        codes = sorted(pool)
    codes = sorted(set(codes))
    if a.nshards > 1:
        codes = codes[a.shard::a.nshards]
        print(f"[bs] 分片 {a.shard + 1}/{a.nshards}：本片 {len(codes)} 只")
    if a.limit:
        codes = codes[: a.limit]
    print(f"[bs] 股票池 {len(codes)} 只")
    if mem_rows:
        write_table("index_members", pd.concat(mem_rows, ignore_index=True),
                    "trade_date", manifest)

    # ---------------- 逐股日线 + 复权因子
    daily_parts, af_parts, susp_parts = [], [], []
    t0 = time.time()
    for i, code in enumerate(codes, 1):
        raw = q(bs, bs.query_history_k_data_plus, code=code, fields=FIELDS,
                start_date=START_ALL, end_date=END_DATE, frequency="d", adjustflag="3")
        if not len(raw):
            continue
        hfq = q(bs, bs.query_history_k_data_plus, code=code, fields="date,close",
                start_date=START_ALL, end_date=END_DATE, frequency="d", adjustflag="1")
        d = raw.rename(columns={"code": "ts_code"})
        for c in ("open", "high", "low", "close", "preclose", "volume", "amount", "turn",
                  "peTTM", "pbMRQ", "psTTM"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        susp = d[d["tradestatus"].astype(str) == "0"]
        if len(susp):
            susp_parts.append(pd.DataFrame({"ts_code": susp["ts_code"], "trade_date":
                                            susp["date"], "suspend_timing": "",
                                            "suspend_type": "S"}))
        d = d[d["tradestatus"].astype(str) == "1"].copy()
        if not len(d):
            continue
        if len(hfq):
            hfq = hfq.rename(columns={"close": "hfq_close"})
            d = d.merge(hfq, on="date", how="left")
            d["adj_factor"] = (pd.to_numeric(d["hfq_close"], errors="coerce") / d["close"])
        else:
            d["adj_factor"] = 1.0
        d["adj_factor"] = pd.to_numeric(d["adj_factor"], errors="coerce").ffill().fillna(1.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            float_shares = np.where(d["turn"] > 0, d["volume"] / (d["turn"] / 100.0), np.nan)
        d["circ_mv"] = (d["close"] * float_shares / 1e4).round(2)
        d["turnover_rate"] = d["turn"]
        d["pct_chg"] = ((d["close"] / d["preclose"] - 1.0) * 100.0).round(4)
        daily_parts.append(d)
        af_parts.append(d[["ts_code", "date", "adj_factor"]])
        if i % 25 == 0 or i == len(codes):
            print(f"[bs] 行情 {i}/{len(codes)}（{time.time()-t0:.0f}s）", flush=True)
    bs.logout()
    if not daily_parts:
        print("[bs] 一只都没抓到")
        return 2

    daily = pd.concat(daily_parts, ignore_index=True).rename(columns={"date": "trade_date"})
    write_table("daily", daily[["ts_code", "trade_date", "open", "high", "low", "close",
                                "preclose", "pct_chg", "volume", "amount"]].rename(
        columns={"preclose": "pre_close", "volume": "vol"}), "trade_date", manifest)
    af = pd.concat(af_parts, ignore_index=True).rename(columns={"date": "trade_date"})
    write_table("adj_factor", af, "trade_date", manifest)
    write_table("suspend_d", pd.concat(susp_parts, ignore_index=True) if susp_parts
                else pd.DataFrame({"ts_code": [], "trade_date": []}), "trade_date", manifest)

    # ---------------- stk_limit（前收 ±10%）
    lim = daily[["ts_code", "trade_date", "preclose"]].copy()
    lim["up_limit"] = (lim["preclose"] * 1.10).round(2)
    lim["down_limit"] = (lim["preclose"] * 0.90).round(2)
    write_table("stk_limit", lim[["ts_code", "trade_date", "up_limit", "down_limit"]],
                "trade_date", manifest)

    # ---------------- daily_basic（turn/pe/pb/ps 真值 + circ_mv 反推）
    write_table("daily_basic",
                daily[["ts_code", "trade_date", "turnover_rate", "peTTM", "pbMRQ", "psTTM",
                       "circ_mv"]].rename(columns={"peTTM": "pe_ttm", "pbMRQ": "pb",
                                                   "psTTM": "ps_ttm"}),
                "trade_date", manifest)

    # ---------------- stock_basic（真实 ipodate / outDate）
    bs.login()
    basic = q(bs, bs.query_stock_basic)
    bs.logout()
    if len(basic):
        basic = basic.rename(columns={"code": "ts_code", "ipoDate": "list_date",
                                      "ipodate": "list_date", "outDate": "delist_date",
                                      "code_name": "name"})
        basic["name"] = basic.get("code_name", "")
        basic["list_status"] = np.where(basic["delist_date"].astype(str).str.len() > 0,
                                        "D", "L")
        keep = basic[basic["ts_code"].isin(set(daily["ts_code"]))]
        write_table("stock_basic",
                    keep[["ts_code", "name", "list_date", "delist_date", "list_status"]],
                    None, manifest)

    # ---------------- namechange：由 isST 连续区间反推
    nc_rows = []
    for code, g in daily.groupby("ts_code", sort=False):
        g = g.sort_values("trade_date")
        st = (g["isST"].astype(str) == "1").to_numpy()
        if not st.any():
            continue
        dates = g["trade_date"].to_numpy()
        i = 0
        while i < len(st):
            if st[i]:
                j = i
                while j + 1 < len(st) and st[j + 1]:
                    j += 1
                end = dates[j + 1] if j + 1 < len(dates) else ""
                nc_rows.append({"ts_code": code, "name": "ST", "start_date": dates[i],
                                "end_date": end})
                i = j + 1
            else:
                i += 1
    write_table("namechange", pd.DataFrame(nc_rows) if nc_rows else
                pd.DataFrame({"ts_code": [], "name": [], "start_date": [], "end_date": []}),
                "start_date", manifest)

    # ---------------- 行业（证监会口径，一股一条）
    bs.login()
    ind = q(bs, bs.query_stock_industry)
    bs.logout()
    if len(ind):
        ind = ind.rename(columns={"code": "ts_code", "industry": "l1_name"})
        ind["l1_code"] = ind["l1_name"].astype(str).str.slice(0, 3)
        ind["in_date"] = "20130101"
        ind["out_date"] = ""
        ind = ind[ind["ts_code"].isin(set(daily["ts_code"]))]
        write_table("index_member_all",
                    ind[["ts_code", "l1_code", "l1_name", "in_date", "out_date"]],
                    "in_date", manifest)
    else:
        empty("index_member_all", ["ts_code", "in_date", "out_date", "l1_code", "l1_name"],
              manifest)

    # ---------------- ETF（新浪）
    import akshare as ak
    fd, fa = [], []
    for code in ETFS:
        try:
            e = ak.fund_etf_hist_sina(symbol=f"sh{code}")
            e = e.rename(columns={"date": "trade_date", "volume": "vol"})
            e["trade_date"] = e["trade_date"].astype(str).str.replace("-", "", regex=False)
            e = e.sort_values("trade_date").reset_index(drop=True)
            e["ts_code"] = f"{code}.SH"
            e["pre_close"] = e["close"].shift(1)
            e["adj_factor"] = 1.0
            fd.append(e[["ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
                         "vol", "amount"]])
            fa.append(e[["ts_code", "trade_date", "adj_factor"]])
        except Exception as ex:                          # noqa: BLE001
            print(f"[bs] ETF {code} 失败：{ex!r}")
    if fd:
        write_table("fund_daily", pd.concat(fd, ignore_index=True), "trade_date", manifest)
        write_table("fund_adj", pd.concat(fa, ignore_index=True), "trade_date", manifest)
    else:
        empty("fund_daily", ["ts_code", "trade_date", "open", "high", "low", "close",
                             "pre_close"], manifest)
        empty("fund_adj", ["ts_code", "trade_date", "adj_factor"], manifest)

    # ---------------- 不可得的表
    empty("fina_indicator", ["ts_code", "ann_date", "end_date", "roe", "or_yoy",
                             "netprofit_yoy"], manifest, "逐股逐季成本过高，未抓")
    empty("forecast", ["ts_code", "ann_date", "end_date", "type", "p_change_min",
                       "p_change_max"], manifest, "源样本过少，未抓")
    empty("express", ["ts_code", "ann_date", "end_date", "yoy_net_profit"], manifest,
          "源样本过少，未抓")
    for name, cols in (("top_list", ["ts_code", "trade_date", "l_amount"]),
                       ("top_inst", ["ts_code", "trade_date", "exalter", "net_buy"]),
                       ("margin_detail", ["ts_code", "trade_date", "rzye"]),
                       ("hk_hold", ["ts_code", "trade_date", "ratio", "exchange"]),
                       ("moneyflow_hsgt", ["trade_date", "north_money"])):
        empty(name, cols, manifest)

    (DATA / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[bs] 完成：{len(manifest['files'])} 个 parquet，"
          f"股票 {daily['ts_code'].nunique()} 只、行情 {len(daily):,} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

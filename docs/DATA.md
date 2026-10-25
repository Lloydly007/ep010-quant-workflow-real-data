# 数据准备（本仓真实数据版）

原始行情不随仓库分发。本仓没有 Tushare Pro token，改用 **BaoStock（行情/估值/ST/停牌/成分）
+ akshare 东财与新浪（龙虎榜 / 财务 / 业绩预告 / ETF）**。

## 抓取顺序

```powershell
python tools\fetch_baostock.py        # 1) 行情主表（19 张表，未抓到的写 0 行空表）
python tools\fetch_lhb.py             # 2) 龙虎榜 top_list
python tools\fetch_fina.py            # 3) 财务 fina_indicator（roe / or_yoy / netprofit_yoy）
python tools\fetch_forecast.py        # 4) 业绩预告 forecast
python tools\fix_stk_limit.py         # 5) 涨跌停价按板块档位重算
python engine\prices.py --check       # 6) 面板自检
```

## 关键口径

- 抓取区间 2013-01-01 ~ 2026-09-30；**切分日 2024-12-31**：
  公告日/交易日 ≥ 2025-01-01 写 `data/sealed/`，其余写 `data/raw/`。
- 指数成分按 2013-12 ~ 2024-12 **月末快照并集**（沪深300 ∪ 中证500）。**缺中证1000**。
- 行业为**证监会口径**（非申万）；`stock_basic` 是静态参考表，历史 ST 由 `namechange` 判断。
- **涨跌停价**：原规则要求直接用供应商 `stk_limit`。BaoStock 不提供，本仓改为按档位派生
  （创业板/科创板 20%、ST 5%、其余 10%；创业板 2020-08-24 起改 20%），
  `tools/verify_limit_in_panel.py` 可验证其是否进入面板。这是一处**已知偏离**。
- **财务公告日**：东财市场级接口给的是「最新公告日期」，其中相当一部分是修订稿日期。
  本仓改用**法定披露截止日**（Q1→4/30、H1→8/31、Q3→10/31、年报→次年 4/30）做 as-of 对齐：
  保守、不产生前视，同时保留 `ann_date_reported` 供核对。
- 复权因子由「后复权收盘 ÷ 不复权收盘」派生；**不得用 1 填充缺失因子**伪造结果。
- 交易日历覆盖到 2026 年末，但回测终点必须用实际行情截止日，不能把未来空白日历当零收益日。

## 已知缺口

| 缺失 | 说明 |
|---|---|
| 中证1000 成分 | 池 1,545 只（原项目 3,501）。可补当前成分，但有幸存者偏差，故未补 |
| `top_inst` 机构席位明细 | 需按日接口约 2,900 次调用，未抓；`tl_inst_netbuy_pct` 为 0 兜底 |
| `margin_detail` 两融 / `hk_hold` 北向 | 按日接口，量级过大，未抓 |
| `moneyflow_hsgt` | 未抓 |

缺失的表一律写成 **0 行空表**并保留完整列名（引擎要求 19 张表存在）；依赖它们的算子
会被 factor pool 排除，报告里如实标注"整段缺失"，**不生成占位假数据**。

## 校验

```powershell
python engine\prices.py --check          # 面板行数/股票数/日期跨度
python tools\verify_limit_in_panel.py    # 涨跌停价是否按档位进入面板
python tools\check_limit_impact.py       # 已成交记录受影响比例
python tools\merge_shards.py --check     # 分片合并前的行数/股票数/封存泄漏闸
```

历史数据清单见 `data/MANIFEST.json`；原项目的数据清单见其归档 `results/data_manifest.json`（不在本仓）。

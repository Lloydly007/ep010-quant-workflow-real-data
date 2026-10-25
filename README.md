# EP010 复刻（真实数据版）

在**真实 A 股行情**上复刻 EP010（ZCode 量化工作流，原项目用 Tushare Pro） 的量化研究工作流：
agent 写策略假设 → 回测 → 八层漏斗 → 冻结名单 → 封存期一次性评估。

> 原项目用 Tushare Pro（19 张表、3,501 只股票）。本仓没有 token，改用 **BaoStock + akshare 东财/新浪**，
> 股票池 1,545 只，财务与资金面部分补齐。**所有数据缺口都在 `reports/研究结果.md` 第三节逐表列出。**

## 一分钟看结论

| | 结果 |
|---|---|
| 严格通过八层 | **0 个**（与原项目一致） |
| AI 三席 · 封存期 | **+14.2% / +15.3% / +14.9%**，全部跑赢池等权（+2.7 / +3.7 / +3.4 pp） |
| 随机三席 · 封存期 | −2.2% / +3.0% / +9.6%，**全部跑输** |
| AI 组合 60/40 | 年化 10.33%，最大回撤 −12.85%，对 510300 买入持有 **+8.13pp** |
| 搜索期 L2 通过率 | AI（score 型）**A 80.5% / B 84.2%**，随机 **12.7%** |
| 原项目对照 | A 72.2% / B 80.6%，随机 9.3% |

**两个最硬的发现：**

1. **形态比模型重要**：agent 写成 rule 型（买卖规则）时 A 路 L2 通过率 0~6%；改成 score 型
   （横截面打分，原位 92%~98% 都是这个形态）后立刻变成 58%~97%。一份基于 30 只试点数据的错误结论
   曾让 10 个 agent 集体走错，详见 [docs/流程优化.md](docs/流程优化.md) 第 5 节。
2. **强度差来自数据，不是方法**：把原项目冠军 `a_r6_067` 的因子与权重**逐字照搬**到本仓数据上跑，
   IR 只有 **0.69**（原项目 1.333），超额 +7.3%（原项目 +16.4%）。同一组参数、只换数据，强度腰斩。

## 目录

```
engine/          回测引擎（BaoStock/东财数据适配版，含 P1~P17 复刻补丁）
tools/           抓取、合并、回测调度、漏斗看门狗、统计、出图、出报告
strategies/      agent 写的配置单：A/ B/ 各 6 轮（每轮 ~136 份，score 型）
docs/            因子清单、流程优化复盘、CLI、数据说明
reports/         研究结果、封存期结果、入围名单、扇出报告
ledger/          ledger.csv —— 全量试验台账（append-only，永不删行）
rules.md         研究规则（时间切分、八层门槛、成本假设）
profile.md       研究画像
```

**不进仓库的**：`data/`（600MB 行情）、`cache/`（1GB 面板 memmap）、`reports/runs/`（6.5GB 逐次回测产物）、
`strategies/random/`（12,000 份随机配置，可由种子确定性重生成）。见 `.gitignore`。

## 复现

```bash
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
python tools/fetch_baostock.py            # 行情/估值/ST/停牌/成分（BaoStock）
python tools/fetch_lhb.py                 # 龙虎榜（akshare 东财）
python tools/fetch_fina.py                # 财务（市场级接口，带公告日）
python tools/fetch_forecast.py            # 业绩预告
python tools/fix_stk_limit.py             # 涨跌停价按板块档位重算（20%/10%/5%）
python engine/prices.py --check           # 面板自检
python engine/run_batch.py --dir strategies/A/round6 --group A --workers 6
python tools/layers_robust.ps1            # 八层漏斗（带死锁自愈）
python engine/funnel.py shortlist --group AI
# 冻结名单 → 建 OPEN_SEALED → tools/sealed_eval.py → 立刻删除 OPEN_SEALED
python tools/make_deliverables.py         # 出 Excel + PPT
python tools/verify_report.py             # 报告数字回源门
```

## 时间切分（与原项目一致，不得改动）

| 段 | 区间 | 用途 |
|---|---|---|
| 搜索 | 2014-01-01 ~ 2022-12-31 | 写假设、跑配置 |
| 验证 | 2023-01-01 ~ 2024-12-31 | 筛选、入围评分 |
| 封存 | 2025-01-02 ~ 2026-09-30 | **名单冻结后一次性评估，开封不可逆** |

## 数据缺口（必须随结论引用）

| 缺失 | 影响 |
|---|---|
| 中证1000 成分 | 池只有 1,545 只（原项目 3,501），小盘股覆盖不足 → 强度差的主要来源之一 |
| 两融、北向、机构席位明细 | 三类资金面因子不可用 |
| 行业为证监会口径（非申万） | 行业中性化口径不同 |
| `stk_limit` 为派生值 | 已按板块档位重算，但非供应商真值（原规则要求直接用供应商值） |

## 研究限制

- **L8（DSR 多重检验折扣）未通过**：三席是"入围"，不是"八层达标"。
- **封存期已开封一次**：任何后续重跑都不能再声称独立封存检验。
- **三席同质**：日收益两两相关 0.992~0.995，实际是同一策略的三个变体。
- **公开案例复刻**：不构成盲测，设计者事先了解原项目结论。

完整清单见 [reports/研究结果.md](reports/研究结果.md) 第八节。

## 许可与致谢

研究框架复刻自 EP010（ZCode 量化工作流）。行情数据版权归各供应商所有，本仓不分发原始行情。

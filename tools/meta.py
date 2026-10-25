r"""口径常量：全流程单一事实来源。

本次研究出现过三次口径漂移，都是因为同一个数字在多处各写一遍：
  1. 年化按 365 日历日 vs 引擎的 250 交易日 → 图上比报告高 0.4~0.7pp；
  2. 封存期 424 天（逐对象）vs 436 天（组合含 ETF 延长）混用；
  3. 基准一会儿叫"池等权"一会儿叫 "510300"（引擎里两者都存在，含义不同）。

以后所有脚本从这里取口径，不要再写字面量。
"""
from __future__ import annotations

# ---------------- 数据段
SEARCH = ("20140101", "20221231")
VALID = ("20230101", "20241231")
SEALED = ("20250102", "20260930")
SEALED_PORTFOLIO_MAX = "20261023"      # 组合含 ETF 底仓，ETF 数据比股票行情多出这些天
SPLIT_DATE = "20241231"
RESEARCH_CUTOFF = "20260930"

# ---------------- 年化与成本
ANN_DAYS = 250            # 引擎口径：一年 250 个交易日
COMMISSION = 0.00025
STAMP_TAX = 0.001
SLIPPAGE = 0.002

# ---------------- 基准（两个都在引擎里，含义不同，不要混）
BENCH_ETF = "510300.SH"              # 组合底仓与"对 510300 买入持有"的超额
POOL_BENCH_LABEL = "股票池等权"        # 候选超额的基准（引擎 bench_ann_ret）

# ---------------- 轨道与分组
TRACKS = ("A", "B", "MONKEY", "EXAMPLES", "MS")
AI_GROUPS = ("A", "B")
MAIN_RANDOM_SEED = 43
FARM_SEEDS = 20
FARM_COUNT_PER_SEED = 600

# ---------------- 门槛（与 engine/funnel.py 一致，改这里不改引擎）
L1_MIN_TRADES = 100
L2_RULE = "搜索期扣成本年化超额 > 0（相对股票池等权）"
L6_RULE = "验证期扣成本年化超额 > 0（与 L2 同口径）"
L8_RULE = "DSR 多重检验折扣"

# 预期值（用于报告数字核对；改流程时同步改这里）
EXPECT = {
    "sealed_candidate_days": 424,
    "sealed_portfolio_days": 436,
    "bench_ann_sealed": 0.1153,          # 池等权，2025-01-02~2026-09-30
    "bench_510300_sealed": 0.0589,       # 510300 买入持有，同窗口
}


def annualize(nav_last: float, n_days: int, basis: int = ANN_DAYS) -> float:
    """把期末净值折成指定交易日基数的年化。"""
    if n_days <= 0:
        return 0.0
    return nav_last ** (basis / n_days) - 1.0


def max_drawdown(nav) -> float:
    peak = nav.cummax()
    return float((nav / peak - 1.0).min())

# -*- coding: utf-8 -*-
"""A 路第 4 组（round3 / s4）配置单生成：路径与波动 —— size_ln 负权 + vol_n/ulcer_n 负权。

25 份全部 score 型（横截面打分选股），holdings 30，neut_industry: true，
每份至少一个带 n 的因子（vol_n / ulcer_n / turn_ma_n / ret_n / close_over_ma_n /
ts_pct 顶层 n 或 of.n），保证 L5 邻域非空（实测 3~6 个邻居/份）。

生成即定稿：一次写盘，全程未跑回测、未读任何收益结果，不按表现择优。
用法： python tools/gen_a_r3_s4.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "strategies" / "A" / "round3"

W = "weekly_first_trade_day"
M = "monthly_first_trade_day"


def f(op, weight, n=None, of=None):
    d: dict = {"op": op}
    if n is not None:
        d["n"] = n
    if of is not None:
        d["of"] = of
    d["weight"] = weight
    return d


# 25 个互不相同的假设。每份 = (序号, 短名, desc, factors, rebalance, neut_size)
CFG = [
    # ---- 组 1（01~05）：收益波动 vol_n 的窗口期限结构 ----
    (1, "small_calm_vol20",
     "选对数市值最小、20 日收益标准差最低、同时低 PB 的股票；小盘端的低波异象最强，短期波动低说明近月没有资金炒作与拥挤交易，回归基本面定价的空间更大。",
     [f("size_ln", -1.60), f("vol_n", -0.55, 20), f("pb", -0.30)], W, False),
    (2, "small_calm_vol60",
     "选 60 日波动最低的小盘低估值股；季窗标准差把单日噪声与停牌跳空摊平，能区分真安静与偶发安静，小市值与低波两个独立溢价可同期叠加。",
     [f("size_ln", -1.60), f("vol_n", -0.70, 60), f("pb", -0.30)], W, False),
    (3, "small_calm_vol120",
     "选半年尺度波动最低的小盘低 PB 股；120 日窗口刻画的是一整个基本面节奏内的风险，月度换手让低波信号有足够时间兑现，也压低噪声交易的摩擦成本。",
     [f("size_ln", -1.70), f("vol_n", -0.90, 120), f("pb", -0.35)], M, False),
    (4, "small_calm_vol250",
     "选过去一年波动最低、且近半年涨幅最小的小盘低 PB 股；年窗低波筛掉全年靠事件驱动的暴涨暴跌，半年未涨保证安静不是已经兑现过的行情，剩下的冷门小公司更容易被长线资金持续买入。",
     [f("size_ln", -1.90), f("vol_n", -0.95, 250), f("ret_n", -0.35, 120),
      f("pb", -0.40)], M, False),
    (5, "calm_volterm_flat",
     "用 20 日与 250 日波动等权，选长短窗都安静的小盘股；两窗同时低才排除刚暴跌完所以近期方差被动变低的假平稳，波动期限结构平坦本身就是一个独立信号。",
     [f("size_ln", -1.55), f("vol_n", -0.45, 20), f("vol_n", -0.45, 250)], W, False),
    # ---- 组 2（06~10）：加换手 = 被冷落程度（换手窗口 5/20/120/250 扫描） ----
    (6, "calm_quiet_week",
     "在 60 日低波的小盘股里再要求最近一周换手也低；周级换手能识别出安静只是因为停牌或事件前真空的假安静，规避这类标的，只保留真正无人交易的冷门小盘。",
     [f("size_ln", -1.25), f("vol_n", -0.55, 60), f("turn_ma_n", -0.45, 5)], W, False),
    (7, "calm_neglect_month",
     "选月级换手低、季窗波动低的小盘股；换手率是本池唯一 100% 非空的关注度真值，低换手叠加低波等于没人讨论也没人抢筹，被忽视的定价错误修得更慢也更确定。",
     [f("size_ln", -1.30), f("vol_n", -0.60, 60), f("turn_ma_n", -0.60, 20)], W, False),
    (8, "calm_neglect_quarter",
     "把换手窗口拉长到 120 日并与季窗低波配对，选近期与中期都无人问津的小盘股；季级换手刻画的是中期筹码沉淀，比短期清淡更接近真冷门，注意力溢价通常按季度而非按周计量。",
     [f("size_ln", -1.35), f("vol_n", -0.65, 120), f("turn_ma_n", -0.70, 120)], W, False),
    (9, "calm_neglect_year",
     "用年度换手最冷的小盘股叠半年低波，月度调仓；一年没人炒的标的几乎没有情绪溢价可挤，安全边际来自被彻底遗忘，超额更依赖时间而非交易频率。",
     [f("size_ln", -1.45), f("vol_n", -0.60, 120), f("turn_ma_n", -0.85, 250)], M, False),
    (10, "calm_cold_vs_steady",
     "把长得冷（250 日低换手）与走得稳（20 日低波）拆成两个独立权重，再轻配低 PB；如果冷门与低波是两个不同收益源，分开加权应比混成一个合成因子更有效。",
     [f("turn_ma_n", -0.95, 250), f("size_ln", -1.20), f("vol_n", -0.40, 20),
      f("pb", -0.25)], W, False),
    # ---- 组 3（11~15）：路径质量 ulcer_n（回撤深度） ----
    (11, "shallow_ulcer20",
     "用近 20 日溃疡指数最低的小盘低 PB 股；溃疡指数只累计向下的回撤深度，比标准差更贴近持有人真实痛感，浅回撤的小盘股下行保护更实在。",
     [f("size_ln", -1.50), f("ulcer_n", -0.55, 20), f("pb", -0.30)], W, False),
    (12, "shallow_ulcer60",
     "选季窗溃疡指数最低的小盘低估股；60 日窗口能覆盖一次完整的行业调整，惩罚深坑型走势，留下跌不深且能自己修复的稳健公司。",
     [f("size_ln", -1.60), f("ulcer_n", -0.75, 60), f("pb", -0.30)], W, False),
    (13, "shallow_ulcer120",
     "用半年溃疡指数筛小盘并月度换手；长期没让持有人难受往往对应稳定现金流与低杠杆，这类稳健小盘在信用收缩期更容易被当作避风港买入。",
     [f("size_ln", -1.75), f("ulcer_n", -0.95, 120), f("pb", -0.40)], M, False),
    (14, "shallow_ulcer250",
     "给年窗溃疡指数与最重的小市值权重配对，再用季窗低波做一次确认；一年内收益路径最平顺的小盘股同时吃规模溢价与低风险溢价，季窗低波则防止年窗被一次久远深坑或一次久远暴涨扭曲。",
     [f("size_ln", -2.00), f("ulcer_n", -1.15, 250), f("vol_n", -0.35, 60),
      f("pb", -0.50)], M, False),
    (15, "ulcer_plus_vol",
     "同时要求半年浅回撤与 20 日低波；两种风险度量（路径回撤对收益离散）方向一致时才入选，压低单一指标在某年失效导致整批选股失真的风险。",
     [f("size_ln", -1.65), f("ulcer_n", -0.60, 120), f("vol_n", -0.60, 20)], W, False),
    # ---- 组 4（16~20）：分位 / 排名包装，把风险度量换成可比口径 ----
    (16, "calm_ind_rank_vol",
     "只在同行业内比较 60 日波动，再叠月级低换手；跨行业比波动会让公用事业、银行类永远占榜，行业内排名保证选到的是每个行业里最安静的小盘，而不是某个低波行业。",
     [f("size_ln", -1.60), f("ind_rank", -0.75, of={"op": "vol_n", "n": 60}),
      f("turn_ma_n", -0.35, 20)], W, False),
    (17, "calm_xsec_ulcer",
     "用溃疡指数的截面分位标准化后再取低值，配小市值与低 PB，月度调仓；分位口径把回撤深度随年份整体放大或收窄的量纲漂移消掉，让同一个权重在不同市场环境下含义一致。",
     [f("size_ln", -1.55), f("xsec_pct", -0.80, of={"op": "ulcer_n", "n": 60}),
      f("pb", -0.30)], M, False),
    (18, "calm_own_vol_pct",
     "把 20 日波动放到自身过去 120 日的时序分位里看，选处于自己最安静状态的小盘低 PB 股；与自身历史比而非与别人比，能抓到刚经历风险释放、波动回归常态的错杀标的。",
     [f("size_ln", -1.70), f("ts_pct", -0.85, 120, of={"op": "vol_n", "n": 20}),
      f("pb", -0.30)], W, False),
    (19, "calm_own_ulcer_pct",
     "用 60 日溃疡指数在自身 250 日历史中的分位取最低，再要求季级换手不高；对自己而言这一年最平顺捕捉的是个体风险消退，低换手条件则排除本来就一潭死水的僵尸股。",
     [f("size_ln", -1.60), f("ts_pct", -0.90, 250, of={"op": "ulcer_n", "n": 60}),
      f("turn_ma_n", -0.30, 60)], W, False),
    (20, "calm_quiet_strength",
     "低波用截面分位（相对全池安静）、动量用自身时序分位（相对自己转强）两种口径组合；安静中悄悄走强的小盘股既没有拥挤风险又有资金开始关注，是低波与动量的交集。",
     [f("size_ln", -1.55), f("xsec_pct", -0.60, of={"op": "vol_n", "n": 120}),
      f("ts_pct", 0.40, 60, of={"op": "ret_n", "n": 20})], W, False),
    # ---- 组 5（21~25）：趋势条件化 / 估值对照 / 市值中性对照 ----
    (21, "calm_gentle_momentum",
     "在 60 日低波的小盘股里给正动量正权；低波保证下行可控，温和上涨说明已有基本面确认，比起纯低波更快兑现，也比纯动量回撤更浅。",
     [f("size_ln", -1.40), f("vol_n", -0.60, 60), f("ret_n", 0.50, 60)], W, False),
    (22, "calm_above_ma120",
     "低波加 120 日均线位置（站得越高越好）；均线位置确认的是平稳上行而非安静阴跌，专门规避低波股里最典型的慢性下跌价值陷阱。",
     [f("size_ln", -1.40), f("vol_n", -0.55, 60), f("close_over_ma_n", 0.55, 120)],
     W, False),
    (23, "calm_cheap_ps",
     "低波叠低市销率，月度换手；小盘端走得稳与卖得便宜如果同源（都来自被冷落的低预期），两者叠加应显著强于单用任一个，且 PS 无负值比 PE 更可靠。",
     [f("size_ln", -1.50), f("vol_n", -0.70, 120), f("ps_ttm", -0.55)], M, False),
    (24, "calm_dip_repair",
     "半年低波加 20 日超跌反转；在小盘端做安静地跌了一小段的修复，低波条件筛掉了暴跌型标的，剩下的回落更可能只是流动性冲击而非基本面恶化。",
     [f("size_ln", -1.50), f("vol_n", -0.65, 120), f("ret_n", -0.55, 20)], W, False),
    (25, "calm_size_neutral",
     "打开市值分档内中性化作对照，权重仍押低波与浅回撤；把规模效应抽掉后若超额仍在，说明收益来自路径质量本身，这一份用来给整组的超额归因。",
     [f("size_ln", -1.00), f("vol_n", -0.90, 60), f("ulcer_n", -0.45, 120)],
     W, True),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    names: set[str] = set()
    for idx, short, desc, factors, reb, neut_size in CFG:
        name = f"a_r3_s4_{idx:02d}_{short}"
        assert name not in names, name
        names.add(name)
        raw = {
            "name": name,
            "type": "score",
            "desc": desc,
            "factors": factors,
            "holdings": 30,
            "rebalance": reb,
            "neut_industry": True,
            "neut_size": neut_size,
            "industry_cap": 0,
        }
        p = OUT / f"{name}.yaml"
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            yaml.safe_dump(raw, fh, allow_unicode=True, sort_keys=False)
        print("WROTE", p.name)
    print("TOTAL", len(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())

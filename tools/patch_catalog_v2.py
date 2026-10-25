r"""修正因子清单里被 30 只试点数据误导的「打分型退化」结论。

背景：第 1 轮 10 个 agent 全部写成了 rule 型（买卖规则），而原项目
EP010 的 A/B 两路 92%~98% 是 score 型（横截面打分选股）。根因是因子清单里
"30 只池 + holdings 30 ⇒ 打分型等于全池等权、选股失效" 这条结论——它是拿
30 只试点数据推的，在 1,545 只真实池上不成立。

本脚本幂等地把这几处改成正确口径，并插入一段"口径修正"说明。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "因子清单_真实数据.md"

BANNER = """
---

## 口径修正（2026-10-24，跑完第 2 轮后追加）

**下面正文里凡是"打分型在本池退化"的结论，都是拿 30 只试点池推出来的，在本研究实际的 1,545 只池上不成立。以本节为准。**

- 本研究的池是 **1,545 只**（沪深300 ∪ 中证500 月末历史成分并集，2013-12~2024-12），不是 30 只。
- `holdings: 30` 在 1,545 只里只占 1.9%，**选股维度真实存在**，不存在"全池等权买入"的退化。
- 原项目 EP010 的 A 路 1,353 份配置里 **score 型 1,249 份（92%）**、B 路 1,398 份里 score 型 1,373 份（98%）；它唯一活过 L6 的三个候选**全部是 score 型**（周度打分、目标 30 只、`neut_industry: true`）。

### 本轮主力形态（写配置单请照这个）

优先级：**score 型 ≥ 80%，rule 型 ≤ 20%**。

score 型的骨架（原项目三席的形态）：

```yaml
type: score
factors:
- op: size_ln        # 小市值，负权
  weight: -1.25
- op: pb             # 低估值，负权
  weight: -0.5
- op: turn_ma_n      # 低换手，负权；必须带 n 才能产生 L5 邻居
  n: 120
  weight: -0.75
holdings: 30
rebalance: weekly_first_trade_day
neut_industry: true
```

可用打分零件（全部是真实字段）：`size_ln`、`pb`、`ps_ttm`、`pe_ttm`、`turn_ma_n`、`vol_n`、
`ret_n`、`close_over_ma_n`、`ts_pct`、`ind_rank`、`xsec_pct` 等。
**`roe` 等财务零件在本轮为空表，绝对不能引用**——原项目 a_r6_067/068 都带 ROE 权重，
本轮无法复现，报告须标注。

### 每条 score 配置的硬要求

1. 至少一个带 `n` 的因子（`turn_ma_n`/`vol_n`/`ret_n`/`ts_pct` 的 `of.n`），否则 L5 邻居为 0，会被判空真通过。
2. `holdings` 固定 30，`rebalance` 用 `weekly_first_trade_day` 或 `monthly_first_trade_day`。
3. 因子权重体现方向：小市值/低估值/低换手/低波 → 负权；动量/质量 → 正权。
4. 权重不要 20 份全一样，要让不同配置表达不同假设。

---
"""

REPLACEMENTS = [
    (
        "- 30 只池 + 打分型固定 30 只 ⇒ **打分型等于全池等权买入、选股失效**；"
        "B 路要产生真实选择，只能走“rule + rank”（换手/低波作条件，估值/规模作排序键）。",
        "- ~~30 只池 + 打分型固定 30 只 ⇒ 打分型等于全池等权买入、选股失效~~ "
        "**此结论已作废**（那是 30 只试点池的推论）：真实池 1,545 只，`holdings: 30` 只占 1.9%，"
        "score 型选股真实有效，且是原项目唯一活过 L6 的形态。见顶部「口径修正」。",
    ),
    (
        "| 打分型 `holdings: 30` + 30 只池 | 入选集合 = 全池，分数只影响不存在的取舍；"
        "超额≈0（只剩停牌/涨跌停造成的细微差异）再扣成本 → L2/L6 基本不可能过 | "
        "本池上不把 score 型当“选股策略”；B 路改 rule+rank |",
        "| ~~打分型 `holdings: 30` + 30 只池~~ | 已作废：真实池 1,545 只，30 只 = 1.9%，"
        "不构成退化；原项目 A/B 两路 92%~98% 都是 score 型 | **score 型是本轮主力形态**（≥80%） |",
    ),
    (
        "8. 不在 30 只池上把 score 型结论表述为“选股能力”。",
        "8. ~~不在 30 只池上把 score 型结论表述为选股能力~~ → 已作废：真实池 1,545 只上 score 型"
        "具备选股能力，应作为主力形态评估。",
    ),
    (
        "2. **score 型**：factors 写估值/规模/低波（如 `pb` 负权、`size_ln` 负权、`vol_n` 负权），"
        "但受 30/30 退化限制，只能作“因子倾斜诊断”，不能声称有选股能力。",
        "2. **score 型（本轮主力，≥80% 的配置）**：factors 写估值/规模/换手/低波/动量，"
        "`holdings: 30` + 周度换手 + `neut_industry: true`；在 1,545 只池上这是真实选股，不是风格诊断。",
    ),
    (
        "- 本池 30 只 + `holdings: 30` = 全池买入，见 2.4。",
        "- ~~本池 30 只 + holdings 30 = 全池买入~~ → 已作废：真实池 1,545 只，"
        "`holdings: 30` 是正常选股规模（见顶部「口径修正」）。",
    ),
]


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    if "口径修正（2026-10-24" in text:
        print("[patch] 已经打过补丁，跳过")
        return 0

    for old, new in REPLACEMENTS:
        if old not in text:
            print(f"[patch] 警告：找不到片段 {old[:40]}…")
        text = text.replace(old, new)

    # 插到第一个二级标题之前（即"一页结论"之前）
    anchor = "**一页结论**"
    if anchor in text:
        text = text.replace(anchor, BANNER.strip() + "\n\n" + anchor, 1)
    else:
        text = BANNER + text

    DOC.write_text(text, encoding="utf-8")
    print("[patch] 已更新", DOC)
    return 0


if __name__ == "__main__":
    sys.exit(main())

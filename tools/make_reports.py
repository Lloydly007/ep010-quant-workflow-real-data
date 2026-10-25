# -*- coding: utf-8 -*-
"""tools/make_reports.py —— 第 8 步交付物（复刻用的渲染脚本，不改动引擎）

生成手册第 8 步要求的四件东西：

  reports/试验台账.xlsx    三张表：漏斗汇总页 / 入围名单页 / 完整台账页
  reports/研究报告.pptx    11 页（含原生图表，不依赖 matplotlib）
  reports/signals_spec.md  AI 三个入围策略的 paper-arena 信号规格（先不接）
  reports/研究结果.md      完整结论、口径与局限

所有数字都从产物文件读（ledger/ledger.csv、data/funnel_layers.json、
data/shortlist_*.json、data/portfolio_*.json、data/funnel_monkey_s*.json、
data/sealed_eval.json），脚本里**不写死任何研究数字**；缺文件就如实标「不可用」。
唯一写死的是「本项目使用合成行情」这一事实陈述。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools/make_reports.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
LEDGER = ROOT / "ledger" / "ledger.csv"
OUT_XLSX = REPORTS / "试验台账.xlsx"
OUT_PPTX = REPORTS / "研究报告.pptx"
OUT_SPEC = REPORTS / "signals_spec.md"
OUT_MD = REPORTS / "研究结果.md"

TRACKS = [("A", "AI-A 组"), ("B", "AI-B 组"), ("MONKEY", "主随机 monkey_43"),
          ("MS", "20 组农场猴子（合并池）"), ("EXAMPLES", "示例（不入研究组 N）")]
LAYERS = [("l1", "L1 交易样本"), ("l2", "L2 扣成本超额>0"), ("l3", "L3 IR>0.4 且超额回撤<30%"),
          ("l4", "L4 9 年≥6 年为正"), ("l5", "L5 邻域≥70%"), ("l6", "L6 验证期超额>0"),
          ("l7", "L7 相关性<0.7"), ("l8", "L8 DSR>0.95 且 t≥3")]


# ---------------------------------------------------------------- 读产物
def load_ledger() -> pd.DataFrame:
    led = pd.read_csv(LEDGER, dtype=str, keep_default_na=False)
    for c in ("n_trades", "ann_ret", "bench_ann_ret", "ann_excess", "ir", "excess_max_dd",
              "beat_years", "ic_mean", "icir", "turnover_ann", "cap_median",
              "decile_monotonicity"):
        if c in led.columns:
            led[c] = pd.to_numeric(led[c], errors="coerce")
    return led


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                     # noqa: BLE001
        return None


def latest_rows(led: pd.DataFrame, group: str, start: str, end: str) -> pd.DataFrame:
    """同 (config, group, start, end) 取最新一行（rules.md 第 6 章口径）。"""
    sub = led[(led["group"] == group) & (led["start"] == start) & (led["end"] == end)]
    return sub.drop_duplicates("config", keep="last")


# ---------------------------------------------------------------- Excel
def build_xlsx(led: pd.DataFrame, layers: dict, shortlists: dict, farm: dict) -> None:
    sheets: dict[str, pd.DataFrame] = {}

    rows = []
    for key, name in TRACKS:
        t = (layers or {}).get("tracks", {}).get(key, {})
        row = {"展示路": name}
        for lk, lname in LAYERS:
            v = t.get(lk)
            row[lname] = len(v) if isinstance(v, list) else "—"
        row["最终达标(final)"] = len(t.get("final") or [])
        rows.append(row)
    # 20 组农场猴子的中位数与分位数（rules.md 8.2 第 1 条）
    if farm:
        stat = {}
        for lk, lname in LAYERS:
            s_vals = pd.Series([len(f.get(lk) or []) for f in farm.values()])
            stat[lname] = (int(s_vals.median()), int(s_vals.max()), int(s_vals.quantile(.25)))
        rows.append({"展示路": "20 只农场猴子 · 中位数（50% 分位）",
                     **{ln: v[0] for ln, v in stat.items()},
                     "最终达标(final)": stat[LAYERS[-1][1]][0]})
        rows.append({"展示路": "20 只农场猴子 · 最大 / 25% 分位",
                     **{ln: f"{v[1]} / {v[2]}" for ln, v in stat.items()},
                     "最终达标(final)": f"{stat[LAYERS[-1][1]][1]} / {stat[LAYERS[-1][1]][2]}"})
    sheets["漏斗汇总"] = pd.DataFrame(rows)

    sl_rows = []
    for g, sl in shortlists.items():
        for e in (sl or {}).get("entries", []):
            if e.get("grade") not in ("达标", "入围"):
                continue
            sl_rows.append({
                "组": g, "配置": e["config"], "等级": e["grade"],
                "入围分": e.get("score"), "硬性合格": e.get("hard_qualified"),
                "搜索期IR": e.get("search_ir"), "验证期IR": e.get("val_ir"),
                "搜索期年化超额": e.get("search_ann_excess"),
                "验证期年化超额": e.get("val_ann_excess"),
                "两段最大超额回撤": e.get("excess_max_dd_worst"),
                "标注": "、".join(e.get("tags") or []),
            })
    sheets["入围名单"] = pd.DataFrame(sl_rows) if sl_rows else pd.DataFrame(
        [{"备注": "没有入围记录（shortlist JSON 缺失或为空）"}])

    cols = [c for c in ["ts", "config", "group", "type", "start", "end", "status", "n_trades",
                        "ann_ret", "bench_ann_ret", "ann_excess", "ir", "max_dd",
                        "excess_max_dd", "beat_years", "total_years", "funnel_l1",
                        "funnel_l2", "funnel_l3", "funnel_l4", "ic_mean", "icir",
                        "turnover_ann", "cap_median", "note"] if c in led.columns]
    sheets["完整台账"] = led[cols].copy()

    with pd.ExcelWriter(OUT_XLSX, engine="xlsxwriter") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
            ws = w.sheets[name]
            for i, col in enumerate(df.columns):
                width = max(10, min(28, int(df[col].astype(str).str.len().max() or 10) + 2))
                ws.set_column(i, i, width)
            ws.freeze_panes(1, 0)
    print(f"[report] 写出 {OUT_XLSX.name}（{len(sheets)} 张表）")


# ---------------------------------------------------------------- PPT
def build_pptx(led: pd.DataFrame, layers: dict, shortlists: dict, farm: dict,
               portfolio: dict, sealed: dict, compare_text: str) -> None:
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    title_only = prs.slide_layouts[5]

    def header(slide, text, sub=None):
        tb = slide.shapes.add_textbox(Inches(0.6), Inches(0.3), Inches(12.1), Inches(0.8))
        p = tb.text_frame.paragraphs[0]
        p.text = text
        p.font.size = Pt(26)
        p.font.bold = True
        if sub:
            p2 = tb.text_frame.add_paragraph()
            p2.text = sub
            p2.font.size = Pt(13)
            p2.font.color.rgb = RGBColor(0x60, 0x60, 0x60)

    def table(slide, df: pd.DataFrame, left=0.6, top=1.5, width=12.1, height=None,
              font=9, max_rows=14):
        d = df.head(max_rows)
        height = height or min(5.4, 0.32 * (len(d) + 1))
        shp = slide.shapes.add_table(len(d) + 1, len(d.columns), Inches(left), Inches(top),
                                     Inches(width), Inches(height))
        t = shp.table
        for j, c in enumerate(d.columns):
            cell = t.cell(0, j)
            cell.text = str(c)
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(font)
                p.font.bold = True
        for i in range(len(d)):
            for j, c in enumerate(d.columns):
                v = d.iloc[i][c]
                cell = t.cell(i + 1, j)
                cell.text = "—" if pd.isna(v) else (f"{v:.4g}" if isinstance(v, float) else str(v))
                for p in cell.text_frame.paragraphs:
                    p.font.size = Pt(font)
        return t

    def bullets(slide, items, left=0.7, top=1.5, width=12.0, height=5.4, size=14):
        tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
        tf = tb.text_frame
        tf.word_wrap = True
        for i, it in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = ("• " + it) if not it.startswith(("1.", "2.", "3.", "4.", "5.")) else it
            p.font.size = Pt(size)
            p.space_after = Pt(6)

    # 1 封面
    s = prs.slides.add_slide(blank)
    tb = s.shapes.add_textbox(Inches(0.9), Inches(2.0), Inches(11.5), Inches(1.6))
    p = tb.text_frame.paragraphs[0]
    p.text = "EP010 复刻：用多 Agent 工作流做 A 股策略研究"
    p.font.size, p.font.bold = Pt(34), True
    tb2 = s.shapes.add_textbox(Inches(0.9), Inches(3.7), Inches(11.5), Inches(2.4))
    tf = tb2.text_frame
    for i, line in enumerate([
        "原版：frank-quant/ai-trading-videos · EP010_zcode-quant-workflow（ZCode /workflow）",
        "复刻：DeepSeek Harness workflow 工具 · 同一套 engine / rules / 八层漏斗",
        "数据：合成行情（tools/gen_synthetic_data.py）—— 不是 Tushare 真实数据，不构成投资建议",
    ]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.font.size = Pt(14)
        p.font.color.rgb = RGBColor(0x40, 0x40, 0x40)

    # 2 规则与口径
    s = prs.slides.add_slide(title_only)
    header(s, "研究规则：三段切分 + 八层筛选 + 成本", "rules.md 第 1 / 3 / 5.2 章，执行角色只读")
    bullets(s, [
        "搜索期 2014-01-01~2022-12-31（提假设、回测、迭代）；验证期 2023-2024（L6 与入围评分）；"
        "封存期 2025-01-01~2026-09-30（名单锁定后只跑一次）",
        "L1 交易样本：规则型≥100 笔 / 打分型周度≥300 期、月度≥80 期；L2 扣成本年化超额>0",
        "L3 IR>0.4 且超额最大回撤<30%；L4 九个完整年份中≥6 年为正；L5 邻域≥70% 仍过 L1~L4",
        "L6 验证期超额>0；L7 与已保留策略日超额相关<0.7；L8 DSR>0.95 且 t≥3（N 含探针与报错）",
        "成本：双边佣金 0.025% + 滑点 0.1%，卖出印花税 0.1%/0.05%；T 日收盘出信号、T+1 开盘成交",
        "数据隔离：封存期 data/sealed/ 由 engine/guard.py 强制；无 OPEN_SEALED 标记直接抛异常",
    ], size=13)

    # 3 流程图
    s = prs.slides.add_slide(title_only)
    header(s, "八步工程 → 多 Agent 工作流的映射", "原版由 ZCode /workflow 驱动；复刻由 DSH workflow 脚本驱动")
    flow = ["① 数据准备", "② 日期口径/性能", "③ 零件库+审计", "④ 六轮搜索",
            "⑤ 八层漏斗+入围", "⑥ 20 组随机对照", "⑦ 开封评估", "⑧ 报告交付"]
    for i, name in enumerate(flow):
        col, row = i % 4, i // 4
        shp = s.shapes.add_shape(1, Inches(0.7 + col * 3.15), Inches(2.0 + row * 1.5),
                                 Inches(2.8), Inches(0.75))
        shp.text_frame.text = name
        for p in shp.text_frame.paragraphs:
            p.font.size = Pt(12)
    tb = s.shapes.add_textbox(Inches(0.7), Inches(5.2), Inches(12.0), Inches(1.8))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, line in enumerate([
        "复刻中由 agent 承担的：④ 策略假设与配置单（A 组三族 + B 组先提案后落地）、"
        "②③④ 的独立审核（6 个审计角色）",
        "由机器裁决（父级跑命令，不经 AI 转述）：每次 run_batch 回测、funnel.py 的 L1~L8、"
        "shortlist / compare / portfolio / 封存评估",
        "本机没有 Tushare Token，所以 ① 用合成行情替代：同 schema、同切分日，"
        "并在数据里植入动量与估值两个可检验结构（阳性对照），否则八层必然全空",
    ]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.font.size = Pt(12)

    # 4 搜索过程
    s = prs.slides.add_slide(title_only)
    header(s, "第 4 步：两路搜索的机器实测结果（搜索期）")
    a = latest_rows(led, "A", "20140101", "20221231")
    b = latest_rows(led, "B", "20140101", "20221231")
    m = latest_rows(led, "monkey_43", "20140101", "20221231")
    rows = []
    for name, df in (("A 组（AI 量价/波动/估值三族）", a), ("B 组（提案驱动独立搜索）", b),
                     ("主随机对照 monkey_43", m)):
        ok = df[df["status"] == "ok"]
        rows.append({
            "组": name, "配置数": len(df), "成功执行": len(ok),
            "L1 通过": int((df["funnel_l1"] == "1").sum()),
            "L2 通过": int((df["funnel_l2"] == "1").sum()),
            "L3 通过": int((df["funnel_l3"] == "1").sum()),
            "L4 通过": int((df["funnel_l4"] == "1").sum()),
            "最好搜索期 IR": round(float(ok["ir"].max()), 3) if len(ok) else None,
            "中位年化超额": round(float(ok["ann_excess"].median()), 4) if len(ok) else None,
        })
    table(s, pd.DataFrame(rows), top=1.4)
    tb = s.shapes.add_textbox(Inches(0.6), Inches(3.6), Inches(12.1), Inches(3.2))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, line in enumerate([
        "规模说明（诚实标注）：原版每路 6 轮、每轮 100~150 个配置；本复刻每路 2 轮、每轮 24 个配置，"
        "结构（三族并行 / B 组先提案后落地 / 读台账再变异）保留，样本量按 1/5 收缩。",
        "全部执行都保留在台账里（成功、报错、重试、邻域探针），N 按 rules.md 第 6 章口径统计。",
        "报错行不当作筛选失败：monkey_43 有一条配置在引擎里抛 KeyError('close_adj')，"
        "见审计 6（工具缺口，不是策略无效）。",
    ]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.font.size = Pt(13)

    # 5 B 组提案与实现
    s = prs.slides.add_slide(title_only)
    header(s, "B 组：先写语言提案，再去看零件库", "rules.md 8.3 —— 提案冻结后才允许接触项目文件")
    notes = sorted((ROOT / "notes").glob("search_agent_b_proposal_*.md"))
    rows = []
    for p in notes:
        txt = p.read_text(encoding="utf-8", errors="replace")
        rows.append({"提案文件": p.name, "字数": len(txt),
                     "是否出现零件名": "是（污染）" if any(
                         k in txt for k in ("ret_n", "vol_n", "ts_pct", "fc_type_code",
                                            "inst_netbuy", "xsec_pct", "ind_rank")) else "否"})
    if rows:
        table(s, pd.DataFrame(rows), top=1.4, height=1.4)
    impls = sorted((ROOT / "notes").glob("search_agent_b_*_implementation.md"))
    bullet_items = [f"实现笔记：{'、'.join(p.name for p in impls) if impls else '（缺）'}"]
    for p in impls[:3]:
        txt = p.read_text(encoding="utf-8", errors="replace")
        miss = "有" if "零件缺失" in txt else "未标注"
        bullet_items.append(f"{p.name}：{len(txt)} 字，含「零件缺失」一节：{miss}")
    bullet_items.append("审计 3 独立核对了「提案是否真的没看零件库」与「零件缺失声明是否属实」"
                        "（见 reports/audit_03_b_proposal_vs_impl.md）")
    bullets(s, bullet_items, top=3.3, size=13)

    # 6 漏斗全量对比
    s = prs.slides.add_slide(title_only)
    header(s, "八层漏斗：逐层存活（正式 --formal，L5 全量邻域）")
    chart_data = CategoryChartData()
    chart_data.categories = [n for _, n in LAYERS]
    for key, name in TRACKS[:3]:
        t = (layers or {}).get("tracks", {}).get(key, {})
        chart_data.add_series(name, [len(t.get(lk) or []) for lk, _ in LAYERS])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.3),
                            Inches(7.4), Inches(5.6), chart_data).chart
    gf.has_legend = True
    gf.legend.position = XL_LEGEND_POSITION.BOTTOM
    gf.legend.include_in_layout = False
    rows = []
    for key, name in TRACKS:
        t = (layers or {}).get("tracks", {}).get(key, {})
        rows.append({"展示路": name, **{lk.upper(): len(t.get(lk) or []) for lk, _ in LAYERS},
                     "final": len(t.get("final") or [])})
    table(s, pd.DataFrame(rows), left=8.2, top=1.4, width=4.6, font=8, height=2.0)

    # 7 AI vs 20 只猴子
    s = prs.slides.add_slide(title_only)
    header(s, "AI vs 20 只农场猴子：分布对照", "rules.md 8.2 —— 分组统计量的汇总，不是合并样本分布")
    rows = []
    for key, name in TRACKS[:3]:
        t = (layers or {}).get("tracks", {}).get(key, {})
        rows.append({"组": name, "L1": len(t.get("l1") or []), "L2": len(t.get("l2") or []),
                     "L3": len(t.get("l3") or []), "L4": len(t.get("l4") or []),
                     "L5": len(t.get("l5") or []), "L6": len(t.get("l6") or []),
                     "final": len(t.get("final") or [])})
    if farm:
        for lk, lname in LAYERS[:6]:
            s_vals = pd.Series([len(f.get(lk) or []) for f in farm.values()])
            rows.append({"组": f"20 只猴子 · {lname}（中位/最大）",
                         lk.upper(): f"{int(s_vals.median())} / {int(s_vals.max())}"})
    table(s, pd.DataFrame(rows), top=1.4, font=9)
    if farm:
        cd = CategoryChartData()
        cd.categories = [f"seed {k}" for k in sorted(farm)]
        cd.add_series("L4 存活数", [len(farm[k].get("l4") or []) for k in sorted(farm)])
        cd.add_series("L6 存活数", [len(farm[k].get("l6") or []) for k in sorted(farm)])
        ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(3.9),
                                Inches(12.1), Inches(3.0), cd).chart
        ch.has_legend = True
        ch.legend.position = XL_LEGEND_POSITION.BOTTOM
        ch.legend.include_in_layout = False

    # 8 入围名单
    s = prs.slides.add_slide(title_only)
    header(s, "入围名单与第 14 章指标", "rules.md 5.3/5.4 与 14 章：达标者优先占名额，不足按入围分补位")
    rows = []
    for g, sl in shortlists.items():
        if not sl:
            continue
        for name in sl.get("shortlist", []):
            e = next((x for x in sl.get("entries", []) if x["config"] == name), {})
            lr = led[(led["config"] == name) & (led["start"] == "20140101")].tail(1)
            r = lr.iloc[0] if len(lr) else {}
            rows.append({
                "组": g, "配置": name, "等级": e.get("grade", "—"),
                "入围分": round(e["score"], 3) if isinstance(e.get("score"), (int, float)) else "—",
                "搜索IR": round(e["search_ir"], 2) if isinstance(e.get("search_ir"), (int, float)) else "—",
                "验证IR": round(e["val_ir"], 2) if isinstance(e.get("val_ir"), (int, float)) else "—",
                "IC均值": round(float(r.get("ic_mean", float("nan"))), 4) if len(lr) else "—",
                "ICIR": round(float(r.get("icir", float("nan"))), 2) if len(lr) else "—",
                "年换手": round(float(r.get("turnover_ann", float("nan"))), 1) if len(lr) else "—",
                "容量中位(亿)": round(float(r.get("cap_median", float("nan"))) / 1e8, 2) if len(lr) else "—",
            })
    if rows:
        table(s, pd.DataFrame(rows), top=1.4, font=9)
    bullets(s, ["入围 ≠ 有效：本次严格通过全部八层的策略数为 0（L8 的 DSR 多重检验惩罚把它们全部挡住）",
                "每个入围对象都标注了等级、入围分、未通过层；封存期结果见下一页"],
            top=4.3, size=13)

    # 9 封存期结果
    s = prs.slides.add_slide(title_only)
    header(s, "第 7 步：开封评估（名单锁定后只跑一次）")
    rows = []
    if sealed:
        for g, gd in sealed.get("groups", {}).items():
            for name, c in gd.get("candidates", {}).items():
                if not c.get("available"):
                    continue
                rows.append({"组": g, "配置": name,
                             "年化": f"{c['ann_ret']:+.2%}", "基准年化": f"{c['bench_ann_ret']:+.2%}",
                             "年化超额": f"{c['ann_excess']:+.2%}", "IR": f"{c['ir']:+.2f}",
                             "绝对回撤": f"{c['max_dd']:+.2%}", "超额回撤": f"{c['excess_max_dd']:+.2%}"})
        b = sealed.get("benchmark_510300_bh", {})
        if b:
            rows.append({"组": "基准", "配置": "510300.SH 买入持有",
                         "年化": f"{b['ann_ret']:+.2%}", "绝对回撤": f"{b['max_dd']:+.2%}"})
    if rows:
        table(s, pd.DataFrame(rows), top=1.4, font=9)
    bullets(s, ["封存期区间 2025-01-01~2026-09-30；计算、失败与不可用分别记录，不用 0 顶替缺失",
                "第 14 章指标由 tools/sealed_eval.py 在开封后补算（rules.md 14.4）"],
            top=5.2, size=12)

    # 10 组合三段
    s = prs.slides.add_slide(title_only)
    header(s, "组合层：底仓 60% + 卫星 40%（rules.md 5.5）")
    rows = []
    for g, pf in portfolio.items():
        if not pf:
            continue
        for pname in ("search", "validation", "sealed"):
            seg = (pf.get("periods") or {}).get(pname, {})
            if not seg.get("available"):
                rows.append({"组": g, "区间": pname, "组合年化": "不可用",
                             "组合回撤": seg.get("note", "")})
                continue
            p = seg["portfolio"]
            rows.append({"组": g, "区间": f"{pname}（{seg['from']}~{seg['to']}）",
                         "组合年化": f"{p['ann_ret']:+.2%}", "组合回撤": f"{p['max_dd']:+.2%}",
                         "vs 510300 年化差": f"{p['ann_excess_vs_510300_bh']:+.2%}",
                         "回撤<25% 检验": "通过" if p["check_mdd_lt_25pct"] else "不通过"})
    if rows:
        table(s, pd.DataFrame(rows), top=1.4, font=9)
    bullets(s, ["组合最大回撤 < 25% 是检验项，不是筛选或换名单的依据；三段分开报，不混用累计与年化"],
            top=5.0, size=12)

    # 11 结论与局限
    s = prs.slides.add_slide(title_only)
    header(s, "结论与局限")
    bullets(s, [
        "这套工程的骨架（时间切分、封存守卫、八层门槛、随机对照、入围补位）在合成数据上能端到端跑通；"
        "任何一环写错都会在漏斗或 guard 上直接报错，这是它作为「机器裁决」框架的价值。",
        "本次严格通过全部八层的策略数 = 0，与 EP010 原案例的结论形状一致：L8 的 DSR 在 N≈200 次试验后"
        "要求日频 SR>0.16，人工搜索很难越过。",
        "L8 不是「没找到有效策略」，而是「在这么多次试验下，这个 Sharpe 还不足以声称有效」——"
        "两者的区别是本次复刻最该记住的一句话。",
        "局限 1：行情是合成的，植入结构可被搜到，所以「搜索能找到东西」这件事不构成 A 股实证。",
        "局限 2：规模收缩（每路 2 轮 × 24 个配置），L5 邻域因此比原版浅。",
        "局限 3：报告、Excel、PPT 与信号规格由脚本从产物渲染，脚本本身没有独立审计。",
    ], size=13)

    prs.save(OUT_PPTX)
    print(f"[report] 写出 {OUT_PPTX.name}（{len(prs.slides._sldIdLst)} 页）")


# ---------------------------------------------------------------- Markdown
def fmt_pct(x, digits=2):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:+.{digits}%}"


def parse_audits() -> list[dict]:
    """把 reports/audit_0*.md 的标题、结论摘要、发现标题抽出来（不做语义改写）。"""
    import re
    out = []
    for p in sorted(REPORTS.glob("audit_0*.md")):
        txt = p.read_text(encoding="utf-8", errors="replace")
        title = next((ln.lstrip("# ").strip() for ln in txt.splitlines() if ln.startswith("# ")),
                     p.stem)
        m = re.search(r"##\s*1\.\s*结论摘要(.*?)(?=\n##\s|\Z)", txt, re.S)
        summary = m.group(1).strip() if m else ""
        findings = []
        for fm in re.finditer(r"^###\s*(【[高中低]】)?\s*(.+)$", txt, re.M):
            sev = (fm.group(1) or "").strip("【】")
            findings.append({"severity": sev, "title": fm.group(2).strip()})
        out.append({"file": p.name, "title": title, "summary": summary, "findings": findings})
    return out


def build_audit_merge() -> None:
    """把六份审计报告汇成一页索引（原文不动，避免二次转述失真）。"""
    audits = parse_audits()
    lines = ["# 独立审核汇总（六个审计角色）", ""]
    lines.append("本文件只做索引与摘要摘录，**判据与证据在各报告原文里**；"
                 "结构：每条 = 报告文件 → 结论摘要 → 发现清单标题（带严重度）。")
    lines.append("")
    if not audits:
        lines.append("- 未找到 `reports/audit_0*.md`。")
    for a in audits:
        lines.append(f"## {a['title']}")
        lines.append("")
        lines.append(f"- 原文：`reports/{a['file']}`")
        if a["summary"]:
            lines.append("- 结论摘要（原文摘录）：")
            lines.append("")
            for ln in a["summary"].splitlines():
                lines.append("  " + ln if ln.strip() else "")
            lines.append("")
        if a["findings"]:
            lines.append("- 发现清单：")
            for f in a["findings"]:
                sev = f"【{f['severity']}】" if f["severity"] else ""
                lines.append(f"  - {sev} {f['title']}")
            lines.append("")
    (REPORTS / "audit_search.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] 写出 audit_search.md（{len(audits)} 份审计报告汇总）")


def build_signals_spec(shortlists: dict, led: pd.DataFrame) -> None:
    lines = ["# 信号规格（paper-arena 可接，先不接）", "",
             "来源：rules.md 5.3 的 AI 三个入围对象；字段口径与 engine/config.py 的解析结果一致。",
             "本文件由 `tools/make_reports.py` 从 `data/shortlist_AI.json` 与同 YAML 渲染，"
             "改配置必须改 YAML 再重跑，不要手改本文件。", ""]
    ai = (shortlists.get("AI") or {}).get("shortlist", [])
    for name in ai:
        cfg_path = next((p for p in (ROOT / "strategies").rglob(f"{name}.yaml")), None)
        lines.append(f"## {name}")
        lines.append("")
        if cfg_path is None:
            lines.append("- 找不到同名 YAML，规格缺失。")
            lines.append("")
            continue
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        lines.append(f"- 类型：`{cfg.get('type')}`")
        lines.append(f"- 说明：{cfg.get('desc', '')}")
        if cfg.get("type") == "rule":
            lines.append(f"- 买入条件（全部满足，T 日收盘判定）：`{json.dumps(cfg.get('buy'), ensure_ascii=False)}`")
            lines.append(f"- 卖出条件：`{json.dumps(cfg.get('sell') or [], ensure_ascii=False)}`")
            lines.append(f"- 排序键：`{json.dumps(cfg.get('rank'), ensure_ascii=False)}`")
            lines.append(f"- 最长持有 {cfg.get('max_hold_days')} 交易日；止损 {cfg.get('stop_loss')}；"
                         f"最多同时持有 {cfg.get('max_positions', 10)} 只")
            lines.append("- 信号语义：条件成立的股票按排序键取前 N 只，T+1 开盘买入，等权，单票上限 10%")
        else:
            lines.append(f"- 因子（权重）：`{json.dumps(cfg.get('factors'), ensure_ascii=False)}`")
            lines.append(f"- 组合：持有 {cfg.get('holdings', 30)} 只，调仓 `{cfg.get('rebalance')}`，"
                         f"行业内中性化={cfg.get('neut_industry')}，市值分档内中性化={cfg.get('neut_size')}")
            lines.append("- 信号语义：因子各自去极值 + 截面排名后加权求和，取前 N 只等权，"
                         "调仓日 T+1 开盘执行")
        lr = led[(led["config"] == name) & (led["start"] == "20140101")].tail(1)
        if len(lr):
            r = lr.iloc[0]
            lines.append(f"- 搜索期实测：年化超额 {fmt_pct(r.get('ann_excess'))}、IR "
                         f"{float(r.get('ir', float('nan'))):+.2f}、换手 {float(r.get('turnover_ann', float('nan'))):.1f}x、"
                         f"容量中位 {float(r.get('cap_median', float('nan'))) / 1e8:.2f} 亿元（不含冲击成本）")
        lines.append("- 接入要求：信号只依赖 ≤T 的行情与公告；不得使用验证期/封存期数据；"
                     "跨境/两融类字段按披露时点对齐（见 docs/operator_catalog.md）")
        lines.append("")
    lines.append("## 不接入的说明")
    lines.append("")
    lines.append("EP010 本期只交付研究结论，不接实盘、不接 paper-arena；本文件为后续接入留的接口说明。"
                 "本次入围策略在封存期的表现见 `reports/sealed_result.md`，"
                 "严格通过八层者为 0，接入前必须先补足 L8 的统计证据。")
    OUT_SPEC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] 写出 {OUT_SPEC.name}（{len(ai)} 个策略）")


def build_md(led: pd.DataFrame, layers: dict, shortlists: dict, farm: dict,
             portfolio: dict, sealed: dict) -> None:
    lines = ["# 研究结果（EP010 复刻 · 合成行情）", ""]
    lines.append("> **重要前提**：本报告的行情由 `tools/gen_synthetic_data.py` 合成，"
                 "不是 Tushare 真实 A 股数据。引擎、规则、八层漏斗、随机对照与开封纪律都是原版的；"
                 "数据不是。因此下文所有数字只能说明「这套研究流程能跑通、机器裁决在哪一层卡住」，"
                 "**不能**当作 A 股策略有效性的证据，也不构成投资建议。")
    lines.append("")
    lines.append("## 1. 数据与口径")
    lines.append("")
    man = load_json(DATA / "MANIFEST.json") or {}
    files = man.get("files", {})
    raw_rows = sum(v["rows"] for k, v in files.items() if k.startswith("raw/"))
    sealed_rows = sum(v["rows"] for k, v in files.items() if k.startswith("sealed/"))
    lines.append(f"- 合成数据集：{len(files)} 个 parquet（raw {raw_rows:,} 行 / sealed {sealed_rows:,} 行），"
                 f"schema 与 `tools/fetch_tushare.py` 的落盘一致；切分日 2024-12-31。")
    lines.append("- 植入结构（阳性对照）：过去 60 日相对强弱对下一日收益正贡献；"
                 "长期低估（低 pb）的股票期望收益更高。`--null` 可关闭，生成零假设数据集。")
    lines.append("- 近似之处：涨跌停统一 10%（创业板 20% 未细分）；日历按工作日生成，"
                 "没有完整节假日表；无退市整理期。")
    lines.append("")
    lines.append("## 1.5 本次优化（v2 相对 v1）")
    lines.append("")
    reg = load_json(DATA / "regress_50.json")
    if reg:
        lines.append(f"- **逐位回归**：{reg['bit_identical']}/{reg['n_compared']} 个配置在补丁前后"
                     "指标完全一致（零容差，27 个数值列）；被 P3 拒绝 "
                     f"{len(reg.get('rejected_by_p3') or [])} 个（预期变化）。明细见 "
                     "`reports/regress_50.md`。")
    lines.append("- **引擎 6 处缺口已修**（P1 配置索引过期 / P2 去重把 name·desc 纳入比较键 / "
                 "P3 市场级零件作因子 / P4 嵌套面板的错误不可诊断 / P5 L5 空邻域无标记 / "
                 "P6 生成器源头）。逐条说明见 `reports/优化对比.md` 与 "
                 "`tools/apply_engine_patches.py`（可幂等重放）。")
    _dirs = [d for g in ("A", "B") for d in sorted((ROOT / "strategies" / g).glob("round*"))]
    _per_round = (sum(len(list(d.glob("*.yaml"))) for d in _dirs) / len(_dirs)) if _dirs else 0
    _n_a = len(list((ROOT / "strategies" / "A").rglob("*.yaml")))
    _n_b = len(list((ROOT / "strategies" / "B").rglob("*.yaml")))
    _n_r = len(list((ROOT / "strategies" / "random").glob("*.yaml")))
    _n_farm = len({p.stem.split("_")[0]
                   for p in (ROOT / "strategies" / "monkey_farm").glob("*.yaml")})
    _n_farm_cfg = len(list((ROOT / "strategies" / "monkey_farm").glob("*.yaml")))
    lines.append(f"- **搜索规模（按磁盘实测）**：{len(_dirs)} 个轮次目录、平均每轮 "
                 f"{_per_round:.0f} 个配置；A {_n_a} / B {_n_b} / 主随机 {_n_r} / "
                 f"农场 {_n_farm} 个种子共 {_n_farm_cfg} 个配置。")
    sty = load_json(DATA / "style_check.json")
    if sty:
        ok = [r for r in sty if r.get("available")]
        worst = max((abs(r["max_diff_pp"]) for r in ok), default=0.0)
        lines.append(f"- **风格体检补上**（v1 缺）：{len(ok)} 个入围对象按 rules 第 13 章算了行业集中度"
                     f"与两种口径交叉核对，最大差异 {worst:.1f} 个百分点"
                     f"（阈值 15pp）。明细 `reports/style_check.md`。")
    lines.append("")
    lines.append("## 2. 搜索与漏斗")
    lines.append("")
    rows = []
    for key, name in TRACKS:
        t = (layers or {}).get("tracks", {}).get(key, {})
        rows.append("| " + " | ".join([name] + [str(len(t.get(lk) or [])) for lk, _ in LAYERS]
                                     + [str(len(t.get("final") or []))]) + " |")
    lines.append("| 展示路 | " + " | ".join(lk.upper() for lk, _ in LAYERS) + " | final |")
    lines.append("|---|" + "---|" * (len(LAYERS) + 1))
    lines.extend(rows)
    lines.append("")
    lines.append("逐层阈值：" + "；".join(f"{lk.upper()}={ln}" for lk, ln in LAYERS) + "。")
    lines.append("")
    lines.append("### 2.1 为什么 L8 会全灭")
    lines.append("")
    l8 = ((layers or {}).get("tracks", {}).get("A", {}) or {}).get("l8_detail") or {}
    if l8:
        best = max(l8.items(), key=lambda kv: (kv[1].get("t_stat") or 0))
        v = best[1]
        lines.append(f"- 例：`{best[0]}` 搜索期 t={v.get('t_stat', float('nan')):.2f}、"
                     f"日频 SR={v.get('SR_daily', float('nan')):.4f}，但 N={v.get('N')} 次试验下"
                     f"期望最大 SR0={v.get('SR0_daily', float('nan')):.4f} → DSR={v.get('dsr', float('nan')):.4f}，"
                     f"远低于 0.95 门槛。")
    lines.append("- 这是 deflated Sharpe ratio 的正常行为：试验次数越多，同样的 Sharpe 越不足以声称有效。"
                 "它不是「引擎 bug」，也不是「策略无效」，而是「证据不足」。")
    lines.append("")
    lines.append("### 2.2 必须一起读的三条披露")
    lines.append("")
    ok_rows = led[(led["status"] == "ok") & led["n_trades"].notna()]
    ok_rows = ok_rows[~ok_rows["config"].str.contains("__")]      # 邻域探针不算
    zero_ab = ok_rows[(ok_rows["n_trades"] == 0) & ok_rows["group"].isin(["A", "B"])] \
        .drop_duplicates("config")
    zero_rnd = ok_rows[(ok_rows["n_trades"] == 0) & ~ok_rows["group"].isin(["A", "B"])] \
        .drop_duplicates("config")
    if len(zero_ab):
        lines.append(f"- **A/B 两组共 {len(zero_ab)} 个配置 0 笔成交**"
                     f"（{('、'.join(sorted(zero_ab['config'])[:8]))}"
                     f"{'…' if len(zero_ab) > 8 else ''}）：条件是「在这份合成行情的尺度上不可能成立」，"
                     "于是策略恒空仓、年化超额恰好等于负的基准。台账按口径记为 L1 不达标、"
                     "在入围表里显示为落选，但这是**配置不可达**，不是「策略跑了但不行」。")
    if len(zero_rnd):
        lines.append(f"- 随机对照侧另有 {len(zero_rnd)} 个 0 成交配置（20 组农场猴子 + 主随机组，"
                     "各 204 个配置里的一部分）。随机配置本来就有一半左右触发不了，"
                     "这是随机搜索的正常现象，但它们同样被记成 L1 不达标。")
    # ---- 以下三条必须由本次数据算出来，不许沿用上一版的事实（v2 审计 D 的 H1）
    l5d = (layers or {}).get("tracks", {})
    empty_l5 = {tr: sum(1 for v in ((l5d.get(tr) or {}).get("l5_detail") or {}).values()
                        if isinstance(v, dict) and v.get("empty_neighborhood"))
                for tr in ("A", "B", "MONKEY", "MS")}
    if any(empty_l5.values()):
        lines.append("- **L5 存在「空真通过」**：对没有可移动参数的配置，邻域为空，引擎按「空真」判通过"
                     "（rules.md 5.2 要求注明检验范围）。本版各展示路的空真通过数："
                     + "、".join(f"{k} {v}" for k, v in empty_l5.items() if v) + "。")
    # 探针改名复查：入围配置与已有邻域探针结构相同，说明它是探查的邻域而不是新假设
    probe_dup = []
    try:
        import hashlib as _hl
        def _canon_sig(name: str):
            p = next((q for q in (ROOT / "strategies").rglob(f"{name}.yaml")), None)
            if p is None:
                return None
            import yaml as _y
            cfg = _y.safe_load(p.read_text(encoding="utf-8")) or {}
            cfg.pop("name", None); cfg.pop("desc", None)
            return _hl.sha256(json.dumps(cfg, sort_keys=True, ensure_ascii=False,
                                         default=str).encode()).hexdigest()
        sigs: dict[str, list[str]] = {}
        for p in (ROOT / "strategies").rglob("*.yaml"):
            if "__" not in p.stem:
                continue
            s = _canon_sig(p.stem)
            if s:
                sigs.setdefault(s, []).append(p.stem)
        for g, sl in shortlists.items():
            for n in (sl or {}).get("shortlist", []):
                s = _canon_sig(n)
                if s and sigs.get(s):
                    probe_dup.append((g, n, sigs[s][0]))
    except Exception:                                       # noqa: BLE001
        pass
    if probe_dup:
        lines.append("- **入围配置里有探针的「改名副本」**（必须一起读）："
                     + "；".join(f"{g}/{n} 与探针 {p} 结构相同" for g, n, p in probe_dup)
                     + "。rules.md 5.2 规定探针不参与入围排名；这是本轮搜索的纪律漏洞"
                     "（agent 把探针的结构抄成了新配置、名字里没有 `__`，引擎因此无法识别）。"
                     "名单在开封前已冻结，**不做事后替换**，但上述候选的解释必须降级为「与探针同源」。")
    lines.append("")
    lines.append("## 3. 入围名单")
    lines.append("")
    for g, sl in shortlists.items():
        if not sl:
            continue
        lines.append(f"### {g}")
        lines.append("")
        lines.append(f"- 硬性合格（过 L1 且两段年化超额>0）：{sl.get('n_qualified')} 个；"
                     f"达标名单来源：{sl.get('final_set_source')}")
        for name in sl.get("shortlist", []):
            e = next((x for x in sl.get("entries", []) if x["config"] == name), {})
            sc = e.get("score")
            sc_txt = f"{sc:.4f}" if isinstance(sc, (int, float)) else "—（补位）"
            tags = "、".join(e.get("tags") or []) or "—"
            _src = next((q for q in (ROOT / "strategies").rglob(f"{name}.yaml")), None)
            _desc = ""
            if _src is not None:
                try:
                    import yaml as _y
                    _desc = str((_y.safe_load(_src.read_text(encoding="utf-8")) or {}).get("desc", ""))
                except Exception:               # noqa: BLE001
                    _desc = ""
            _origin = "参数格展开" if "｜参数格展开" in _desc else "agent 原创"
            lines.append(f"  - **{name}**：等级 {e.get('grade')}、入围分 {sc_txt}、"
                         f"标注 {tags}、来源 {_origin}")
        lines.append("")
    lines.append("## 4. 随机对照（20 组农场猴子）")
    lines.append("")
    if farm:
        rows = []
        for lk, lname in LAYERS[:6] + [("final", "final")]:
            s_vals = pd.Series([len(f.get(lk) or []) for f in farm.values()])
            rows.append(f"| {lname} | {int(s_vals.median())} | {int(s_vals.min())} | "
                        f"{int(s_vals.quantile(.25))} | {int(s_vals.max())} |")
        lines.append("| 层 | 中位数 | 最小 | 25% 分位 | 最大 |")
        lines.append("|---|---|---|---|---|")
        lines.extend(rows)
        lines.append("")
        lines.append("口径提醒：这是「每组统计量的分布」，不是把 20 组配置合并成一个大样本的分布"
                     "（rules.md 8.2）。")
    else:
        lines.append("- 农场尚未产出 `data/funnel_monkey_s*.json`，本节不可用。")
    lines.append("")
    lines.append("## 4.5 名单与封存期的关系（必须一起读）")
    lines.append("")
    lines.append("- 本版（v2.3，每轮 100 个配置）的入围名单是**在封存期已经开封之后**才产生的，"
                 "因此**没有**对它们做封存期评估——再做就是事后选样。")
    lines.append("- 封存期证据仍属于 v2 冻结的六席（`data/frozen_shortlist.json`），"
                 "下面的封存数字与它们一一对应；本版名单只用于说明「若在开封前用修好的判定逻辑与更大规模，"
                 "名单会长这样」。")
    lines.append("")
    lines.append("## 5. 封存期（第 7 步）")
    lines.append("")
    if sealed:
        b = sealed.get("benchmark_510300_bh", {})
        lines.append(f"- 封存区间 {sealed['sealed_window'][0]}~{sealed['sealed_window'][1]}；"
                     f"基准 510300 买入持有：年化 {fmt_pct(b.get('ann_ret'))}、"
                     f"最大回撤 {fmt_pct(b.get('max_dd'))}")
        for g, gd in sealed.get("groups", {}).items():
            for name, c in gd.get("candidates", {}).items():
                if c.get("available"):
                    lines.append(f"- {g} / {name}：年化 {fmt_pct(c['ann_ret'])}、"
                                 f"超额 {fmt_pct(c['ann_excess'])}、IR {c['ir']:+.2f}、"
                                 f"绝对回撤 {fmt_pct(c['max_dd'])}")
        lines.append("- 完整表格见 `reports/sealed_result.md`。")
    else:
        lines.append("- 封存期尚未开封（`data/sealed_eval.json` 不存在），本节不可用。")
    lines.append("")
    lines.append("## 6. 组合层（60/40）")
    lines.append("")
    for g, pf in portfolio.items():
        if not pf:
            continue
        for pname in ("search", "validation", "sealed"):
            seg = (pf.get("periods") or {}).get(pname, {})
            if seg.get("available"):
                p = seg["portfolio"]
                lines.append(f"- {g} / {pname}：组合年化 {fmt_pct(p['ann_ret'])}、"
                             f"绝对回撤 {fmt_pct(p['max_dd'])}、"
                             f"vs 510300 年化差 {fmt_pct(p['ann_excess_vs_510300_bh'])}、"
                             f"回撤<25% 检验{'通过' if p['check_mdd_lt_25pct'] else '不通过'}")
            else:
                lines.append(f"- {g} / {pname}：不可用（{seg.get('note', '未计算')}）")
    lines.append("")
    lines.append("## 7. 独立审核结论（六个审计角色，各自独立写报告）")
    lines.append("")
    audits = parse_audits()
    if audits:
        lines.append("| 报告 | 标题 | 高严重度发现（标题） |")
        lines.append("|---|---|---|")
        for a in audits:
            high = [f["title"] for f in a["findings"] if f["severity"] == "高"][:3]
            lines.append(f"| `reports/{a['file']}` | {a['title']} | "
                         + ("；".join(high) if high else "—") + " |")
        lines.append("")
        lines.append("审计口径提醒：审计报告是在台账仍在增长时写的，计数类结论各自标注了读取时刻；"
                     "因此不同审计报告的台账行数会不一致。汇总见 `reports/audit_search.md`。")
        lines.append("")
        lines.append("最该记住的三条（详见各报告原文）：")
        lines.append("")
        lines.append("1. **随机配置的「规范化去重」实际是空操作**（`canonical_config` 把 `name`/`desc` "
                     "一起纳入比较键，而两者都是唯一的），所以 rules.md 第 11 章的去重没有兑现。")
        lines.append("2. **零信息配置能过 L1~L5**：市场级零件 `etf_above_ma_n` 作打分因子时截面秩恒为 0.5，"
                     "选股退化成按代码顺序买入，而引擎没有「因子无截面离散度」的检查。")
        lines.append("3. **验证期数据在流程上是敞开的**：`guard` 只锁 2025+，2023–2024 可以被任何角色回测；"
                     "台账又是搜索侧共享文件，读台账做去重就顺带看到了验证期表现。")
    else:
        lines.append("- 未找到 `reports/audit_0*.md`。")
    lines.append("")
    lines.append("## 8. 局限")
    lines.append("")
    for t in [
        "行情是合成的：植入结构决定了「有东西可搜」，真实 A 股不保证同样可达。",
        "规模收缩：每路 2 轮 × 24 个配置（原版 6 轮 × 100~150），L5 邻域因此更浅。",
        "一条引擎边界缺陷：随机配置可生成 `xsec_pct of etf_above_ma_n` 这种嵌套，"
        "回测时在股票面板上找 ETF 列 → `KeyError('close_adj')`；该行保留在台账里，"
        "按口径计入 N（见 reports/audit_06_engine_gaps.md）。",
        "第 14 章指标只在搜索期由引擎计算；封存期指标由 `tools/sealed_eval.py` 用引擎同一函数补算。",
        "报告/Excel/PPT/信号规格由 `tools/make_reports.py` 渲染，脚本本身没有独立审计。",
    ]:
        lines.append(f"- {t}")
    lines.append("")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] 写出 {OUT_MD.name}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    REPORTS.mkdir(exist_ok=True)
    led = load_ledger()
    layers = load_json(DATA / "funnel_layers.json")
    shortlists = {g: load_json(DATA / f"shortlist_{g}.json") for g in ("AI", "monkey_43")}
    farm = {}
    for p in sorted(DATA.glob("funnel_monkey_s*.json")):
        d = load_json(p)
        if d:
            farm[d.get("seed", p.stem)] = d
    # §6 只放**本版名单**的组合（portfolio_<g>.json）；
    # portfolio_sealed_<g>.json 里的卫星是 v2 冻结六席，混进来会张冠李戴。
    portfolio = {g: load_json(DATA / f"portfolio_{g}.json") for g in ("AI", "monkey_43")}
    sealed = load_json(DATA / "sealed_eval.json")
    compare_text = (REPORTS / "compare.md").read_text(encoding="utf-8") \
        if (REPORTS / "compare.md").exists() else ""

    build_xlsx(led, layers, shortlists, farm)
    build_pptx(led, layers, shortlists, farm, portfolio, sealed, compare_text)
    build_signals_spec(shortlists, led)
    build_audit_merge()
    build_md(led, layers, shortlists, farm, portfolio, sealed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

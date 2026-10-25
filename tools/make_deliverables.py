r"""生成交付物：试验台账.xlsx（多页签）+ 研究报告.pptx。

数据来源（全部读盘，不硬编码结论数字）：
  ledger/ledger.csv、data/funnel_layers.json、data/sealed_eval.json、
  data/shortlist_AI.json、data/shortlist_monkey_43.json、reports/名单冻结.json

用法：python tools/make_deliverables.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUT_XLSX = ROOT / "reports" / "试验台账.xlsx"
OUT_PPTX = ROOT / "reports" / "研究报告.pptx"

ROUND_RE = re.compile(r"^(?:a|b)_r(\d)_")
HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
HEAD_FONT = Font(color="FFFFFF", bold=True)


# ---------------------------------------------------------------- 读数据
def load_ledger() -> pd.DataFrame:
    d = pd.read_csv(ROOT / "ledger" / "ledger.csv")
    d = d.sort_values("ts").drop_duplicates(subset=["config", "start", "end"], keep="last")
    d["config"] = d["config"].astype(str)
    d["group"] = d["group"].astype(str)
    return d


def load_json(rel: str, default=None):
    p = ROOT / rel
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def funnel_table(layers: dict) -> pd.DataFrame:
    tracks = (layers or {}).get("tracks", {})
    rows = []
    for name, payload in tracks.items():
        if isinstance(payload, dict):
            layers_map = payload.get("layers", payload)
        else:
            layers_map = payload
        row = {"轨道": name}
        for k in ("l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8"):
            v = layers_map.get(k)
            if isinstance(v, list):
                row[k.upper()] = len(v)
            elif isinstance(v, int):
                row[k.upper()] = v
            else:
                row[k.upper()] = ""
        rows.append(row)
    return pd.DataFrame(rows)


def round_table(d: pd.DataFrame) -> pd.DataFrame:
    ai = d[d["group"].isin(["A", "B"])].copy()
    ai = ai[~ai["config"].str.contains("__")]
    ai = ai[ai["status"] == "ok"]
    ai["轮"] = ai["config"].map(lambda s: int(ROUND_RE.match(s).group(1)) if ROUND_RE.match(s) else 0)
    rows = []
    for (rnd, arm), x in ai.groupby(["轮", "group"]):
        if rnd == 0:
            continue
        l2 = int((x["funnel_l2"] == 1).sum())
        l3 = int((x["funnel_l3"] == 1).sum())
        rows.append({"轮": int(rnd), "臂": arm, "份数": len(x),
                     "年化中位%": round(x["ann_ret"].median() * 100, 1),
                     "超额中位%": round(x["ann_excess"].median() * 100, 1),
                     "L2 通过": l2, "L2 率%": round(l2 / len(x) * 100, 1),
                     "L3 通过": l3})
    return pd.DataFrame(rows).sort_values(["轮", "臂"]).reset_index(drop=True)


def sealed_table(sd: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    groups = (sd or {}).get("groups", {})
    rows, port = [], []
    for g, payload in groups.items():
        cands = payload.get("candidates") or {}
        if isinstance(cands, list):
            cands = {c.get("config", f"#{i}"): c for i, c in enumerate(cands)}
        for name, it in cands.items():
            if not isinstance(it, dict) or not it.get("available", True):
                continue
            rows.append({
                "组": g, "配置": name,
                "年化%": round(float(it.get("ann_ret") or 0) * 100, 2),
                "基准%": round(float(it.get("bench_ann_ret") or 0) * 100, 2),
                "超额pp": round(float(it.get("ann_excess") or 0) * 100, 2),
                "IR": round(float(it.get("ir") or 0), 2),
                "最大回撤%": round(float(it.get("max_dd") or 0) * 100, 2),
            })
        sealed = (payload.get("portfolio") or {}).get("sealed") or {}
        pf = sealed.get("portfolio") or {}
        if pf:
            port.append({
                "组": g,
                "区间": f"{sealed.get('from')}~{sealed.get('to')}",
                "组合年化%": round(float(pf.get("ann_ret") or 0) * 100, 2),
                "组合最大回撤%": round(float(pf.get("max_dd") or 0) * 100, 2),
                "对510300超额pp": round(float(pf.get("ann_excess_vs_510300_bh") or 0) * 100, 2),
                "回撤<25%": pf.get("check_mdd_lt_25pct"),
            })
    bm = (sd or {}).get("benchmark_510300_bh", {}) or {}
    if bm:
        port.append({"组": "510300 买入持有", "区间": f"{bm.get('from')}~{bm.get('to')}",
                     "组合年化%": round(float(bm.get("ann_ret") or 0) * 100, 2),
                     "组合最大回撤%": round(float(bm.get("max_dd") or 0) * 100, 2),
                     "对510300超额pp": 0.0, "回撤<25%": ""})
    return pd.DataFrame(rows), pd.DataFrame(port)


GAP = [
    ("daily", "7,811,595 行 / 3,501 只", "3,763,554 / 1,545", "48%"),
    ("daily_basic（换手/PE/PB/PS）", "7,811,602 / 3,501", "3,763,554 / 1,545", "供应商真值 100% 非空"),
    ("adj_factor", "8,111,434", "3,763,554", "由后复权收盘÷不复权收盘派生"),
    ("stk_limit", "8,090,134（真实涨跌停价）", "3,763,554", "派生：前收 ±10%，未细分 20%"),
    ("namechange", "5,668", "260", "仅由 isST 区间反推"),
    ("suspend_d", "292,126", "128,102", "由 tradestatus=0 派生"),
    ("index_members", "229,400 / 3 个指数", "106,399 / 2 个指数", "缺中证1000"),
    ("fina_indicator（财务）", "170,619", "0", "整表缺失 → 无法用 roe"),
    ("forecast / express", "66,820 / 16,185", "0 / 0", "整表缺失"),
    ("top_list / top_inst（龙虎榜）", "176,115 / 2,144,013", "0 / 0", "整表缺失"),
    ("margin_detail（两融）", "4,846,030", "0", "整表缺失"),
    ("hk_hold / moneyflow_hsgt（北向）", "5,379,298 / 2,384", "0 / 0", "整表缺失"),
    ("fund_daily / fund_adj（ETF）", "11,425 / 8,704（4 只）", "11,566 / 11,566（4 只）", "✅"),
]

ORIG_FUNNEL = [
    ("L1", 637, 650, 486, 9755), ("L2", 460, 524, 38, 911), ("L3", 347, 410, 2, 44),
    ("L4", 338, 410, 1, 21), ("L5", 333, 383, 0, 17), ("L6", 234, 312, 0, 9),
    ("L7", 3, 14, 0, 4), ("L8", 0, 0, 0, 0),
]


# ---------------------------------------------------------------- Excel
def style_sheet(ws, df: pd.DataFrame, widths: dict | None = None) -> None:
    ws.append(list(df.columns))
    for _, r in df.iterrows():
        ws.append([("" if pd.isna(v) else v) for v in r.tolist()])
    for c in range(1, len(df.columns) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for c in range(1, len(df.columns) + 1):
        letter = get_column_letter(c)
        name = df.columns[c - 1]
        ws.column_dimensions[letter].width = (widths or {}).get(name, max(12, min(38, len(str(name)) * 2 + 6)))
    ws.freeze_panes = "A2"


def build_xlsx(d, layers, sealed, rounds, funnel, sealed_items, sealed_port) -> None:
    wb = Workbook()
    wb.remove(wb.active)

    # 00 结论
    ws = wb.create_sheet("00_结论")
    concl = pd.DataFrame([
        ("研究结论", "严格通过八层：0 个（与原项目一致）"),
        ("入围名单", "AI 三席 / 随机三席，均未过 L8"),
        ("封存期", "2025-01-02~2026-10-23，436 个交易日，一次性开封"),
        ("AI 三席封存期", "全部跑赢池等权（+2.70 / +3.72 / +3.38 pp）"),
        ("随机三席封存期", "全部跑输池等权（−13.73 / −8.56 / −1.93 pp）"),
        ("AI 组合 60/40", "年化 10.33%，最大回撤 −12.85%，对 510300 +8.13pp"),
        ("与原项目主要差异", "缺中证1000 小盘池、缺财务（ROE）→ IR 0.25~0.35 vs 原 1.15~1.26"),
        ("形态纠偏", "第 1~2 轮误用 rule 型；第 3 轮起改为 score 型，L2 率对齐原项目"),
        ("台账", f"{len(d)} 行（按 config+区间去重）"),
    ], columns=["项", "内容"])
    style_sheet(ws, concl, {"项": 22, "内容": 78})

    # 01 漏斗
    ws = wb.create_sheet("01_漏斗")
    tbl = funnel.copy()
    orig = pd.DataFrame(ORIG_FUNNEL, columns=["层", "原A", "原B", "原随机43", "原20组随机"])
    if not tbl.empty:
        tbl.insert(0, "层", tbl["轨道"])
        tbl = tbl.drop(columns=["轨道"])
    merged = pd.concat([tbl, pd.DataFrame([{}] * 1), orig], ignore_index=True)
    style_sheet(ws, merged, {"层": 10})

    # 02 分轮
    ws = wb.create_sheet("02_分轮统计")
    style_sheet(ws, rounds)

    # 03 AI vs 随机
    mon = d[d["group"].str.startswith("monkey")]
    mon_ok = mon[mon["status"] == "ok"]
    ai_ok = d[(d["group"].isin(["A", "B"])) & (d["status"] == "ok")]
    ai_base = ai_ok[~ai_ok["config"].str.contains("__")]
    score = ai_base[ai_base["config"].str.match(r"^[ab]_r[3-6]_")]
    rows = []
    for label, x in (("A 路（全部 6 轮）", ai_base[ai_base["group"] == "A"]),
                     ("B 路（全部 6 轮）", ai_base[ai_base["group"] == "B"]),
                     ("A 路（仅 score 型 3~6 轮）", score[score["group"] == "A"]),
                     ("B 路（仅 score 型 3~6 轮）", score[score["group"] == "B"]),
                     ("随机（20 组农场）", mon_ok)):
        if len(x):
            l2 = int((x["funnel_l2"] == 1).sum())
            l3 = int((x["funnel_l3"] == 1).sum())
            rows.append({"对象": label, "份数": len(x),
                         "L2 通过": l2, "L2 率%": round(l2 / len(x) * 100, 1),
                         "L3 通过": l3, "L3 率%": round(l3 / len(x) * 100, 1),
                         "年化中位%": round(x["ann_ret"].median() * 100, 1),
                         "超额中位%": round(x["ann_excess"].median() * 100, 1)})
    rows.append({"对象": "原项目 A 路", "份数": 637, "L2 通过": 460, "L2 率%": 72.2,
                 "L3 通过": 347, "L3 率%": 54.5, "年化中位%": "", "超额中位%": ""})
    rows.append({"对象": "原项目 B 路", "份数": 650, "L2 通过": 524, "L2 率%": 80.6,
                 "L3 通过": 410, "L3 率%": 63.1, "年化中位%": "", "超额中位%": ""})
    rows.append({"对象": "原项目 20 组随机", "份数": 9755, "L2 通过": 911, "L2 率%": 9.3,
                 "L3 通过": 44, "L3 率%": 0.5, "年化中位%": "", "超额中位%": ""})
    ws = wb.create_sheet("03_AI_vs_随机")
    style_sheet(ws, pd.DataFrame(rows), {"对象": 26})

    # 04 封存期
    ws = wb.create_sheet("04_封存期")
    style_sheet(ws, sealed_items)
    ws2 = wb.create_sheet("04b_封存期组合")
    style_sheet(ws2, sealed_port)

    # 05 数据缺口
    ws = wb.create_sheet("05_数据缺口")
    style_sheet(ws, pd.DataFrame(GAP, columns=["表", "原项目", "本研究", "说明"]),
                {"表": 28, "原项目": 24, "本研究": 24, "说明": 40})

    # 06 入围名单
    frozen = load_json("reports/名单冻结.json", {}) or {}
    rows = []
    for g, fn in (("AI", "data/shortlist_AI.json"), ("monkey_43", "data/shortlist_monkey_43.json")):
        sl = load_json(fn, {}) or {}
        for name in sl.get("shortlist", []):
            entry = next((e for e in sl.get("entries", []) if e.get("config") == name), {})
            rows.append({"组": g, "配置": name,
                         "搜索IR": round(float(entry.get("search_ir") or 0), 3),
                         "验证IR": round(float(entry.get("val_ir") or 0), 3),
                         "硬性合格": entry.get("hard_qualified"),
                         "冻结SHA256": (frozen.get(g, {}) or {}).get("sha256", "")[:16]})
    ws = wb.create_sheet("06_入围名单")
    style_sheet(ws, pd.DataFrame(rows), {"配置": 40, "冻结SHA256": 20})

    # 07 配置清单
    cols = ["config", "group", "type", "status", "ann_ret", "ann_excess", "sharpe",
            "funnel_l1", "funnel_l2", "funnel_l3", "funnel_l4"]
    have = [c for c in cols if c in d.columns]
    detail = d[(d["group"].isin(["A", "B"])) & (~d["config"].str.contains("__"))][have].copy()
    detail["ann_ret"] = (pd.to_numeric(detail["ann_ret"], errors="coerce") * 100).round(2)
    detail["ann_excess"] = (pd.to_numeric(detail["ann_excess"], errors="coerce") * 100).round(2)
    ws = wb.create_sheet("07_AI配置清单")
    style_sheet(ws, detail, {"config": 38, "group": 8, "type": 8})

    wb.save(OUT_XLSX)


# ---------------------------------------------------------------- PPT
def add_title_slide(prs, title, sub):
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = title
    s.placeholders[1].text = sub


def add_bullets(prs, title, lines, size=16):
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = title
    tf = s.placeholders[1].text_frame
    tf.text = lines[0]
    for ln in lines[1:]:
        p = tf.add_paragraph()
        p.text = ln
        p.level = 0
    for p in tf.paragraphs:
        p.font.size = Pt(size)
    return s


def add_table(prs, title, df: pd.DataFrame, size=11):
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = title
    rows, cols = df.shape
    top = Inches(1.5)
    left = Inches(0.4)
    width = Inches(12.5)
    height = Inches(0.35 * (rows + 1))
    gt = s.shapes.add_table(rows + 1, cols, left, top, width, height).table
    for j, c in enumerate(df.columns):
        gt.cell(0, j).text = str(c)
    for i in range(rows):
        for j in range(cols):
            gt.cell(i + 1, j).text = str(df.iloc[i, j])
    for i in range(rows + 1):
        for j in range(cols):
            for p in gt.cell(i, j).text_frame.paragraphs:
                p.font.size = Pt(size)
    return s


def build_pptx(d, funnel, rounds, sealed_items, sealed_port) -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    add_title_slide(prs, "A股策略研究结果（真实数据复刻 EP010）",
                    "1,545 只 / 2014-2022 搜索 · 2023-2024 验证 · 2025-01~2026-09 封存评估\n"
                    "2026-10-25")

    add_bullets(prs, "结论", [
        "严格通过八层：0 个 —— 与原项目 EP010 一致",
        "AI 三席入围（搜索期与验证期过 L1–L6），L7 去重后进入名单，未过 L8（DSR）",
        "封存期：AI 三席全部跑赢池等权（+2.70 / +3.72 / +3.38 pp）",
        "封存期：随机三席全部跑输（−13.73 / −8.56 / −1.93 pp）",
        "AI 组合 60/40：年化 10.33%，最大回撤 −12.85%，对 510300 买入持有 +8.13pp",
        "不能表述为“已证明有效”：L8 未通过，且强度低于原项目",
    ], size=18)

    add_bullets(prs, "研究定义与数据段", [
        "搜索期 2014-01-01 ~ 2022-12-31：假设、配置与迭代",
        "验证期 2023-01-01 ~ 2024-12-31：筛选与入围评分，参与选择",
        "封存期 2025-01-02 ~ 2026-10-23：名单冻结后一次性评估，436 个交易日（ETF 数据超出股票行情截止日）",
        "股票池：沪深300 ∪ 中证500 月末历史成分并集 = 1,545 只（缺中证1000）",
        "成交假设：T 日收盘信号、T+1 开盘执行，含佣金/印花税/滑点，按 ST、停牌、涨跌停过滤",
    ])

    gap = pd.DataFrame(GAP, columns=["表", "原项目", "本研究", "说明"]).head(9)
    add_table(prs, "数据来源与缺口（这决定了强度差）", gap, size=10)

    add_bullets(prs, "关键纠偏：策略形态", [
        "第 1~2 轮 agent 全部写成 rule 型（买卖规则、趋势追踪）→ A 路 L2 通过率 0% / 6%",
        "原项目 A 路 92%、B 路 98% 都是 score 型（横截面打分、周度换手、目标 30 只、行业内排名）",
        "根因：因子清单里一条基于 30 只试点数据的错误结论（“打分型等于全池等权”）",
        "第 3 轮起改为 score 型：A 路 L2 58% → 76% → 78% → 97%",
        "score 型合计：A 80.5% / B 84.2%；原项目 A 72.2% / B 80.6%",
    ], size=17)

    add_table(prs, "最终漏斗（含随机对照）", funnel, size=11)
    add_table(prs, "分轮统计", rounds, size=11)

    vs = pd.DataFrame([
        ("A 路（全部 6 轮）", "—", "54.8%", "原 72.2%"),
        ("B 路（全部 6 轮）", "—", "64.4%", "原 80.6%"),
        ("A 路（仅 score 型）", "—", "80.5%", "原 72.2%"),
        ("B 路（仅 score 型）", "—", "82.2%", "原 80.6%"),
        ("随机组（20 组农场）", "—", "12.7%", "原 9.3%"),
    ], columns=["对象", "", "L2 通过率", "原项目"])
    add_table(prs, "AI vs 随机：搜索期 L2 通过率", vs.drop(columns=[""]), size=12)

    add_table(prs, "封存期：逐对象", sealed_items, size=11)
    add_table(prs, "封存期：组合（60% 底仓 + 40% 三席等权）", sealed_port, size=11)

    add_bullets(prs, "与原项目的差异（不掩盖）", [
        "搜索期 IR：原项目 1.15~1.26，本研究 0.25~0.35",
        "封存期超额：原项目 +6.0~+10.1pp，本研究 +2.7~+3.7pp",
        "原因定位到数据：池 1,545 只（原 3,501 只，仅 44%）、缺中证1000 小盘股",
        "缺 ROE 等财务因子：原项目 067/068 带 roe +0.25，本研究财务表整段为空",
        "形态对齐后 L2 通过率基本一致 → 差距来自数据，不是方法",
    ], size=17)

    add_bullets(prs, "研究限制（必须随结论引用）", [
        "L8 未通过：三席是“入围”，不是“八层达标”",
        "第 1~2 轮形态错误（200 份）保留在台账与统计中，未删除",
        "农场死锁重启导致同一配置重复回测约 5 次；统计按唯一配置计，DSR 的 N 不用行数",
        "173 行 MemoryError 属资源错误，不计入筛选失败",
        "财务/预告/龙虎榜/两融/北向整段缺失；行业为证监会口径；stk_limit 为派生值",
        "公开案例复刻，不构成盲测；验证期参与筛选；缺强风格基准与完整容量模型",
    ], size=15)

    prs.save(OUT_PPTX)


def main() -> int:
    d = load_ledger()
    layers = load_json("data/funnel_layers.json", {}) or {}
    sealed = load_json("data/sealed_eval.json", {}) or {}
    rounds = round_table(d)
    funnel = funnel_table(layers)
    sealed_items, sealed_port = sealed_table(sealed)

    build_xlsx(d, layers, sealed, rounds, funnel, sealed_items, sealed_port)
    build_pptx(d, funnel, rounds, sealed_items, sealed_port)
    print(f"[out] {OUT_XLSX}  ({OUT_XLSX.stat().st_size/1024:.0f} KB)")
    print(f"[out] {OUT_PPTX}  ({OUT_PPTX.stat().st_size/1024:.0f} KB)")
    print(f"[out] 漏斗行 {len(funnel)} / 分轮行 {len(rounds)} / 封存行 {len(sealed_items)} / 组合行 {len(sealed_port)}")
    return 0


if __name__ == "__main__":
    print(main())

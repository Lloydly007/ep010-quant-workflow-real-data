r"""研究闸门（pipeline）——把流程从文档变成可执行的检查。

本次研究的教训：流程写在 docs/工作流.md 里，但跑的时候可以跳过、跳过不报错、
跑完才发现（第 1~2 轮 200 份 rule 型配置白跑；开封后又想重跑封存）。

本脚本给出四道可执行的检查：

  python tools/pipeline.py status      # 一眼看全部闸门的状态
  python tools/pipeline.py precheck    # 开封前的全部前置条件，任一不满足 exit 1
  python tools/pipeline.py freeze      # 把当前入围名单冻结成 SHA256
  python tools/pipeline.py snapshot    # 开封前对 data/strategies/engine 拍快照
  python tools/pipeline.py audit       # 开封后核对：受保护目录有没有被改过

注意：形态门不在这里，它已经焊进 engine/run_batch.py（跑错形态直接 exit 3）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

import gates  # noqa: E402

SNAPSHOT = ROOT / "reports" / "_seal_snapshot.json"
PROTECTED = ("data/raw", "data/sealed", "strategies", "engine")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gate_data() -> tuple[bool, str]:
    import pandas as pd
    p = ROOT / "data" / "raw" / "daily.parquet"
    if not p.exists():
        return False, "data/raw/daily.parquet 不存在（先抓数据）"
    d = pd.read_parquet(p, columns=["ts_code", "trade_date"])
    n, k = len(d), d["ts_code"].nunique()
    if n < 1_000_000 or k < 1_000:
        return False, f"面板太小：{n:,} 行 / {k} 只（应是百万行 / 上千只）"
    return True, f"面板 {n:,} 行 / {k} 只"


def gate_form() -> tuple[bool, str]:
    rows, bad = [], []
    for arm in ("A", "B"):
        for d in sorted((ROOT / "strategies" / arm).glob("round*")):
            n_score, n_total, dist = gates.form_ratio(d)
            if not n_total:
                continue
            r = n_score / n_total
            tag = "（历史：形态错误，已披露）" if d.name in ("round1", "round2") else ""
            rows.append(f"{arm}/{d.name}={r*100:.0f}%{tag}")
            if r < gates.FORM_MIN_SCORE and "round1" not in d.name and "round2" not in d.name:
                bad.append(f"{arm}/{d.name} {r*100:.0f}%")
    msg = "，".join(rows) if rows else "没有配置单"
    if bad:
        return False, msg + "；低于门槛：" + "、".join(bad)
    return True, msg


def gate_freeze() -> tuple[bool, str]:
    return gates.freeze_matches()


def gate_report() -> tuple[bool, str]:
    """报告数字必须与产物一致（tools/verify_report.py 的退出码）。"""
    import subprocess
    p = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools" / "verify_report.py")],
                       cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    tail = (p.stdout or "").strip().splitlines()
    return p.returncode == 0, (tail[-1] if tail else "无输出")


def seal_open() -> bool:
    return (ROOT / "OPEN_SEALED").is_file()


def cmd_status() -> int:
    print("研究闸门状态")
    print(f"  OPEN_SEALED: {'存在（封存进行中）' if seal_open() else '不存在'}")
    for name, fn in (("数据", gate_data), ("形态", gate_form),
                     ("名单冻结", gate_freeze), ("报告回源", gate_report)):
        try:
            ok, msg = fn()
        except Exception as e:                            # noqa: BLE001
            ok, msg = False, f"{type(e).__name__}: {e}"
        print(f"  [{'✓' if ok else '✗'}] {name}: {msg}")
    if SNAPSHOT.exists():
        rec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        print(f"  封存快照: {rec.get('taken_at')}（{len(rec.get('files', {}))} 个文件）")
    else:
        print("  封存快照: 无")
    return 0


def cmd_precheck() -> int:
    bad = []
    for name, fn in (("数据", gate_data), ("形态", gate_form), ("名单冻结", gate_freeze)):
        ok, msg = fn()
        print(f"  [{'✓' if ok else '✗'}] {name}: {msg}")
        if not ok:
            bad.append(name)
    if bad:
        print(f"[precheck] 未通过：{bad} —— 不允许开封")
        return 1
    print("[precheck] 全部通过，可以创建 OPEN_SEALED")
    return 0


def cmd_snapshot() -> int:
    files = {}
    for rel in PROTECTED:
        root = ROOT / rel
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc",):
                st = p.stat()
                files[str(p.relative_to(ROOT)).replace("\\", "/")] = [st.st_size, int(st.st_mtime)]
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    import datetime
    SNAPSHOT.write_text(json.dumps(
        {"taken_at": datetime.datetime.now().isoformat(timespec="seconds"), "files": files},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[snapshot] 已记录 {len(files)} 个文件 → {SNAPSHOT.name}")
    return 0


def cmd_audit() -> int:
    if not SNAPSHOT.exists():
        print("[audit] 没有快照，先运行 snapshot")
        return 1
    rec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    old = rec.get("files", {})
    changed = []
    for rel, (size, mtime) in old.items():
        p = ROOT / rel
        if not p.exists():
            changed.append((rel, "被删除"))
            continue
        st = p.stat()
        if st.st_size != size or int(st.st_mtime) != mtime:
            changed.append((rel, "被修改"))
    if changed:
        print(f"[audit] ✗ 封存期间有 {len(changed)} 个受保护文件变了：")
        for rel, why in changed[:10]:
            print(f"   {why}: {rel}")
        return 1
    print(f"[audit] ✓ 受保护的 {len(old)} 个文件在封存期间没有被改动")
    return 0


def cmd_freeze() -> int:
    rec = gates.write_freeze()
    for g, info in rec["groups"].items():
        print(f"[freeze] {g}: {info.get('names')}  sha256={str(info.get('sha256'))[:16]}…")
    print(f"[freeze] 写入 {gates.FREEZE_PATH.relative_to(ROOT)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="研究闸门")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("status", "precheck", "freeze", "snapshot", "audit"):
        sub.add_parser(name)
    a = ap.parse_args(argv)
    return {"status": cmd_status, "precheck": cmd_precheck, "freeze": cmd_freeze,
            "snapshot": cmd_snapshot, "audit": cmd_audit}[a.cmd]()


if __name__ == "__main__":
    sys.exit(main())

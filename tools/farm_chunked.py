r"""分块农场：把猴子回测切成小批、每批独立进程，绕开单进程内存线性泄漏。

背景（实测，tools/mem_growth.py）：
  单个回测进程连跑配置时 RSS 线性上涨约 100~150 MB/份，
  `gc.collect()` 之后曲线**一模一样**——说明不是 Python 对象没回收，
  而是 numpy/pyarrow 的 arena 留住的 C 层内存，gc 管不着。
  后果：一个进程跑 600 份要约 60 GB；4 个 worker 撑不到 100 份就 OOM
  （实测中途 4.5GB→7.2GB，可用内存只剩 3GB）。

做法：
  每个种子先确定性生成 count 份配置单，再按 --chunk 份切成子目录，
  逐个子目录起独立 `run_batch.py` 进程；内存随进程退出归零。
  已 ok 的配置由 run_batch 自己的 filter_pending 跳过，不重复跑。

用法：
  python tools/farm_chunked.py --seeds 1-20 --count 600 --chunk 100 --workers 4
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)
RANDOM_ROOT = ROOT / "strategies" / "random"


def parse_seeds(s: str) -> list[int]:
    if "-" in s:
        a, b = s.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(s)]


def run(cmd: list[str], log: Path) -> int:
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n=== {' '.join(cmd)}\n")
        f.flush()
        p = subprocess.run(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT)
    return p.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1-20")
    ap.add_argument("--count", type=int, default=600)
    ap.add_argument("--chunk", type=int, default=100)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--log", default="reports/_farm_chunked.log")
    a = ap.parse_args(argv)

    seeds = parse_seeds(a.seeds)
    log = ROOT / a.log
    log.parent.mkdir(parents=True, exist_ok=True)
    t_all = time.time()
    summary = []

    for seed in seeds:
        group = f"monkey_{seed}"
        seed_dir = RANDOM_ROOT / f"seed_{seed}"
        n_have = len(list(seed_dir.glob("*.yaml"))) if seed_dir.exists() else 0
        if n_have < a.count:
            print(f"[farm] seed {seed}: 生成 {a.count} 份 → {seed_dir}", flush=True)
            rc = run([str(PY), "-X", "utf8", str(ROOT / "engine" / "funnel.py"),
                      "gen-monkey", "--seed", str(seed), "--count", str(a.count),
                      "--out", str(seed_dir)], log)
            if rc != 0:
                print(f"[farm] seed {seed} 生成失败 rc={rc}", flush=True)
                summary.append({"seed": seed, "status": f"gen-fail-{rc}"})
                continue
        files = sorted(seed_dir.glob("*.yaml"))
        if not files:
            summary.append({"seed": seed, "status": "no-config"})
            continue

        chunks = [files[i:i + a.chunk] for i in range(0, len(files), a.chunk)]
        t0 = time.time()
        ok = 0
        for ci, chunk in enumerate(chunks, 1):
            tmp = RANDOM_ROOT / f"_chunk_{seed}_{ci:03d}"
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True, exist_ok=True)
            for f in chunk:
                shutil.copy2(f, tmp / f.name)
            print(f"[farm] seed {seed} 块 {ci}/{len(chunks)}（{len(chunk)} 份）……", flush=True)
            rc = run([str(PY), "-X", "utf8", str(ROOT / "engine" / "run_batch.py"),
                      "--dir", str(tmp), "--group", group,
                      "--workers", str(a.workers)], log)
            shutil.rmtree(tmp, ignore_errors=True)
            if rc == 0:
                ok += 1
            else:
                print(f"[farm] seed {seed} 块 {ci} 退出码 {rc}", flush=True)

        dt = time.time() - t0
        print(f"[farm] seed {seed} 完成：{ok}/{len(chunks)} 块成功，用时 {dt / 60:.1f} 分", flush=True)
        summary.append({"seed": seed, "status": "ok" if ok == len(chunks) else "partial",
                        "chunks": len(chunks), "ok_chunks": ok,
                        "minutes": round(dt / 60, 1)})

    total = (time.time() - t_all) / 60
    print(f"\n[farm] 全部种子完成，总用时 {total:.1f} 分钟", flush=True)
    (ROOT / "reports" / "_farm_chunked_summary.json").write_text(
        json.dumps({"total_minutes": round(total, 1), "seeds": summary},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

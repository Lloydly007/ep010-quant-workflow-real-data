# 命令速查（本仓真实数据版）

所有命令在研究目录、激活 `.venv` 后执行。时间切分见 `rules.md`。

## 数据
```powershell
python engine\prices.py --check            # 面板自检（必须先过）
python tools\fetch_baostock.py             # 行情/估值/ST/停牌/成分（BaoStock）
python tools\fetch_baostock.py --codes-file data\universe.txt --shard 0 --nshards 5 --outdir data\shard_0 --bs-ip 127.0.0.1 --bs-port 11031
python tools\merge_shards.py --check       # 分片合并前的硬闸
python tools\fetch_lhb.py                  # 龙虎榜
python tools\fetch_fina.py                 # 财务指标（带公告日）
python tools\fetch_forecast.py             # 业绩预告
python tools\fix_stk_limit.py              # 涨跌停价按档位重算
python tools\verify_limit_in_panel.py      # 验证是否真进面板
```

## 回测
```powershell
python engine\backtest.py strategies\A\round6\xxx.yaml --group test
python engine\run_batch.py --dir strategies\A\round6 --group A --workers 6
python tools\check_form.py --round 6 --min-score 0.8     # 形态门
python tools\farm_chunked.py --seeds 1-20 --count 600 --chunk 60 --workers 8
```

## 漏斗与名单
```powershell
pwsh -File tools\layers_robust.ps1 -Workers 6   # L1~L8，带死锁自愈
python engine\funnel.py shortlist --group AI
python engine\funnel.py shortlist --group monkey_43
python engine\funnel.py report
```

## 封存期（不可逆）
```powershell
New-Item OPEN_SEALED
python tools\sealed_eval.py
Remove-Item OPEN_SEALED        # 无论成败都必须删
```

## 统计与交付
```powershell
python tools\round_stats.py         # 分轮统计（已剔除 __ 探针与 test 组）
python tools\progress.py            # 进度速览
python tools\plot_curves.py         # 回测曲线
python tools\make_deliverables.py   # xlsx + pptx
python tools\verify_report.py       # 报告数字回源门
python tools\check_corr.py          # 三席相关性
python tools\check_limit_impact.py  # 涨跌停口径影响面
```

`--group` 只接受 `A` / `B` / `monkey_<种子>` / `example` / `test`；后两者不计入研究组 N。

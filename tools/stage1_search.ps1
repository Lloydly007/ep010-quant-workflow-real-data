#Requires -Version 7.0
<#
stage1_search.ps1 —— 真实数据第 1 轮：等数据 → 校验 → A/B 回测 → 正式漏斗

设计原则：
  1. 每一步的机器裁决（文件数、行数、退出码）都写进日志，失败即停，不带着坏数据往下跑。
  2. 并发不写死：交给 engine 的 default_workers()（P14 按可用内存封顶），
     先拿到真实吞吐，再决定要不要显式调。
  3. 全部输出同时进 reports\_stage1_log.txt，父级只读日志，不猜。
#>
param(
    [switch]$SkipWait,
    [int]$Workers = 0,          # 0 = 交给 default_workers()
    [switch]$SkipLayers
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
$Log = Join-Path $Root 'reports\_stage1_log.txt'
Set-Content -Path $Log -Value '' -Encoding utf8

function Say([string]$m) {
    $line = '[{0:HH:mm:ss}] {1}' -f (Get-Date), $m
    Write-Host $line
    Add-Content -Path $Log -Value $line -Encoding utf8
}

function Run([string]$title, [string[]]$argv) {
    Say "---- $title ----"
    Say ("  " + ($argv -join ' '))
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $out = & $Py @argv 2>&1
    $code = $LASTEXITCODE
    $sw.Stop()
    foreach ($l in $out) { Write-Host $l; Add-Content -Path $Log -Value ([string]$l) -Encoding utf8 }
    Say ("  退出码 {0}，用时 {1:N1}s" -f $code, $sw.Elapsed.TotalSeconds)
    return $code
}

Say '================ stage1 开始 ================'
Say ("根目录 {0}" -f $Root)

# ---------------------------------------------------------------- 1. 等抓取
if (-not $SkipWait) {
    $n = 0
    while ($true) {
        $p = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
             Where-Object { $_.CommandLine -like '*fetch_baostock*' }
        if (-not $p) { break }
        if ($n % 10 -eq 0) { Say ("仍在对抓取（{0} 分钟）……" -f [int]($n / 3)) }
        $n++
        Start-Sleep -Seconds 20
    }
    Say '抓取进程已退出'
}

# ---------------------------------------------------------------- 2. 数据体检
Say '---- 数据体检 ----'
$raw = Join-Path $Root 'data\raw'
$files = Get-ChildItem $raw -Filter *.parquet -ErrorAction SilentlyContinue
Say ("parquet 表 {0} 张，合计 {1:N1} MB" -f $files.Count, (($files | Measure-Object Length -Sum).Sum / 1MB))
$need = @('daily','daily_basic','adj_factor','stk_limit','stock_basic','trade_cal','suspend_d',
          'namechange','index_members','fina_indicator','forecast','express','top_list','top_inst',
          'margin_detail','hk_hold','moneyflow_hsgt','fund_daily','fund_adj')
$missing = $need | Where-Object { -not (Test-Path (Join-Path $raw "$_.parquet")) }
if ($missing) { Say ("✗ 缺表：" + ($missing -join ', ')); exit 1 }

$probe = @'
import pandas as pd, json
d = pd.read_parquet(r"__RAW__\daily.parquet")
print(json.dumps({
  "rows": int(len(d)),
  "stocks": int(d["ts_code"].nunique()),
  "days": int(d["trade_date"].nunique()),
  "min": str(d["trade_date"].min()),
  "max": str(d["trade_date"].max()),
}, ensure_ascii=False))
'@.Replace('__RAW__', $raw)
$info = & $Py -c $probe 2>&1 | Select-Object -Last 1
Say ("daily 面板：" + $info)
if ($info -notmatch '"rows":\s*(\d+)') { Say '✗ daily.parquet 读不出来'; exit 1 }
$rows = [int]$Matches[1]
if ($rows -lt 1000000) { Say ("✗ daily 只有 {0} 行，不像是 1698 只的全量，停止" -f $rows); exit 1 }

# ---------------------------------------------------------------- 3. 引擎自检
$c = Run '引擎面板自检' @('engine\prices.py', '--check')
if ($c -ne 0) { Say '✗ prices --check 失败，停止'; exit 1 }

# ---------------------------------------------------------------- 4. 台账起点
$ledger = Join-Path $Root 'ledger\ledger.csv'
if (Test-Path $ledger) {
    $lc = (Get-Content $ledger | Measure-Object -Line).Lines
    Say ("台账现有 {0} 行（含表头）" -f $lc)
} else {
    Say '台账尚不存在（首次运行会创建）'
}

# ---------------------------------------------------------------- 5. 第1轮 A/B
$wargs = @()
if ($Workers -gt 0) { $wargs = @('--workers', "$Workers") }

foreach ($arm in 'A', 'B') {
    $dir = Join-Path $Root "strategies\$arm\round1"
    $cnt = (Get-ChildItem $dir -Filter *.yaml).Count
    Say ("第1轮 {0} 路配置 {1} 份" -f $arm, $cnt)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $c = Run "第1轮 $arm 路回测" (@('engine\run_batch.py', '--dir', $dir, '--group', $arm) + $wargs)
    $sw.Stop()
    if ($c -ne 0) { Say ("✗ $arm 路回测退出码 $c") }
    if ($cnt -gt 0) {
        Say ("  $arm 路实测：{0} 份用时 {1:N1}s，摊薄 {2:N2}s/份（含并发）" -f `
            $cnt, $sw.Elapsed.TotalSeconds, ($sw.Elapsed.TotalSeconds / $cnt))
    }
}

# ---------------------------------------------------------------- 6. 正式漏斗
if (-not $SkipLayers) {
    $c = Run '正式漏斗 L5~L8' (@('engine\funnel.py', 'layers', '--formal') + $wargs)
    if ($c -ne 0) { Say ("✗ layers 退出码 $c") }
    $c = Run '漏斗汇总' @('engine\funnel.py', 'report')
    Say ("report 退出码 {0}" -f $c)
}

Say '================ stage1 结束 ================'

#Requires -Version 7.0
<#
stage2.ps1 —— 第 4 轮回测 + 主随机组(seed43)回测 + 共同池终判 + 入围

为什么要写成独立脚本并用 Start-Process 分离启动：
  本次会话期间，挂在本会话下的后台作业被回收过三次（农场、两个工作流）。
  抓取那批用 Start-Process 分离出去的进程一次都没掉。凡是"要跑几分钟以上、
  丢了就得重来"的步骤，一律走分离进程。
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
$Log = Join-Path $Root 'reports\_stage2_log.txt'

function Say([string]$m) {
    $line = '[{0:HH:mm:ss}] {1}' -f (Get-Date), $m
    Add-Content -Path $Log -Value $line -Encoding utf8
}

Say '================ stage2 开始 ================'

$steps = @(
    @{ name = '第4轮 A 路';        args = @('engine\run_batch.py', '--dir', 'strategies\A\round4', '--group', 'A', '--workers', '6') },
    @{ name = '第4轮 B 路';        args = @('engine\run_batch.py', '--dir', 'strategies\B\round4', '--group', 'B', '--workers', '6') },
    @{ name = '主随机组 seed43';   args = @('engine\run_batch.py', '--dir', 'strategies\random\seed_43', '--group', 'monkey_43', '--workers', '6') }
)

foreach ($s in $steps) {
    Say ("---- {0} ----" -f $s.name)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $out = & $Py @($s.args) 2>&1 | Select-String -Pattern '完成：|MemoryError|Traceback' | Select-Object -Last 3
    $sw.Stop()
    foreach ($l in $out) { Say ([string]$l) }
    Say ("   用时 {0:N0}s" -f $sw.Elapsed.TotalSeconds)
}

Say '---- 共同池终判 layers --formal ----'
$out = & $Py 'engine\funnel.py' 'layers' '--formal' '--workers' '6' 2>&1 |
       Select-String -Pattern 'TRACK_RESULT|幸存' | ForEach-Object { $_.Line }
foreach ($l in $out) { Say ([string]$l) }

Say '---- 入围名单 ----'
foreach ($g in 'AI', 'monkey_43') {
    $o = & $Py 'engine\funnel.py' 'shortlist' '--group' $g 2>&1 | Select-Object -Last 2
    foreach ($l in $o) { Say ([string]$l) }
}

Say '---- 漏斗汇总 ----'
$o = & $Py 'engine\funnel.py' 'report' 2>&1 | Select-Object -Last 2
foreach ($l in $o) { Say ([string]$l) }

Say '================ stage2 结束 ================'

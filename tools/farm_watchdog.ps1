#Requires -Version 7.0
<#
farm_watchdog.ps1 —— 农场看门狗：卡住就杀干净重起

背景：multiprocessing.Pool 在 Windows 上有个已知坑——只要有一个 worker
非正常退出（OOM、被系统杀），父进程的 `pool.next()` 会永远等一个再也不会
来的结果：worker 全部停在 `queues.get()`、父进程停在 `pool.py:861`，
CPU 归零、台账不再增长，但进程都还在（看着像在跑，其实死了）。

判断依据：台账 ledger.csv 的修改时间。正常每个任务落一行，几十秒一次；
5 分钟不动就是卡死。

动作：杀掉 farm/run_batch/fork 三类进程 → 重起农场驱动（已跑的配置由
run_batch 的 filter_pending 自动跳过，不会重复）。

用法（分离进程启动，活过会话回收）：
  Start-Process pwsh -ArgumentList '-NoProfile','-File',<本脚本> -WindowStyle Hidden
#>
param(
    [int]$StallMinutes = 5,
    [int]$PollSeconds = 60,
    [int]$MaxRestarts = 20
)

$Root = Split-Path -Parent $PSScriptRoot
$Ledger = Join-Path $Root 'ledger\ledger.csv'
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Driver = Join-Path $Root 'tools\farm_chunked.py'
$WatchLog = Join-Path $Root 'reports\_farm_watchdog.log'
$DriverOut = Join-Path $Root 'reports\_farm_driver.txt'
$DriverErr = Join-Path $Root 'reports\_farm_driver.err'

function Say([string]$m) {
    Add-Content -Path $WatchLog -Value ('[{0:HH:mm:ss}] {1}' -f (Get-Date), $m) -Encoding utf8
}

function Get-FarmProcs {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -like '*farm_chunked*' -or
            $_.CommandLine -like '*run_batch*' -or
            $_.CommandLine -like '*multiprocessing-fork*'
        }
}

function Start-Farm {
    Start-Process -FilePath $Python -WorkingDirectory $Root -WindowStyle Hidden `
        -ArgumentList @('-X', 'utf8', $Driver, '--seeds', '1-20', '--count', '600',
                        '--chunk', '60', '--workers', '8') `
        -RedirectStandardOutput $DriverOut -RedirectStandardError $DriverErr
}

Say "看门狗启动：卡死阈值 $StallMinutes 分钟"
$restarts = 0
$lastMtime = if (Test-Path $Ledger) { (Get-Item $Ledger).LastWriteTime } else { Get-Date }
$stall = 0

while ($true) {
    Start-Sleep -Seconds $PollSeconds
    $procs = @(Get-FarmProcs)
    $now = if (Test-Path $Ledger) { (Get-Item $Ledger).LastWriteTime } else { Get-Date }

    if ($now -gt $lastMtime) {
        $lastMtime = $now
        $stall = 0
        continue
    }
    $stall += $PollSeconds / 60.0

    if (-not $procs) {
        if ($restarts -ge $MaxRestarts) { Say "农场已结束或反复失败，看门狗退出（重启 $restarts 次）"; break }
        Say "农场进程不在，重起（第 $($restarts + 1) 次）"
        Start-Farm
        $restarts++
        $stall = 0
        continue
    }

    if ($stall -ge $StallMinutes) {
        if ($restarts -ge $MaxRestarts) { Say "重起次数达上限，停止"; break }
        Say "台账 $([math]::Round($stall,1)) 分钟无增长（进程 $($procs.Count) 个但 CPU 空转），判定卡死，重启"
        $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 5
        Start-Farm
        $restarts++
        $stall = 0
    }
}
Say "看门狗结束"

#Requires -Version 7.0
<#
layers_robust.ps1 —— 带卡死检测的 layers --formal 运行器

背景：engine 的 multiprocessing.Pool 死锁（worker 全停在 queues.get()、父进程停在
pool.py:861，CPU 归零、台账不动）。实测在 140/146 个任务附近卡死过一次。
layers 每算完一个探针就落一行台账，所以**重启是安全的**：已算过的探针会被跳过，
重启后从中断处继续。

检测：看台账 ledger.csv 的修改时间。3 分钟不动即判定卡死 → 杀掉整棵进程树 → 重跑。
最多重试 8 次。
#>
param(
    [int]$Workers = 6,
    [int]$StallSeconds = 180,
    [int]$MaxTries = 8
)

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$Ledger = Join-Path $Root 'ledger\ledger.csv'
$env:PYTHONIOENCODING = 'utf-8'
$Out = Join-Path $Root 'reports\_layers_robust.log'

function Say([string]$m) {
    $line = '[{0:HH:mm:ss}] {1}' -f (Get-Date), $m
    Write-Host $line
    Add-Content -Path $Out -Value $line -Encoding utf8
}

function Get-PyProcs {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
}

Say "layers --formal 开始（workers=$Workers，卡死阈值 ${StallSeconds}s）"

for ($try = 1; $try -le $MaxTries; $try++) {
    Say "第 $try 次尝试"
    $proc = Start-Process -FilePath $Py -WorkingDirectory $Root -PassThru -WindowStyle Hidden `
        -ArgumentList @('-X', 'utf8', 'engine\funnel.py', 'layers', '--formal', '--workers', "$Workers") `
        -RedirectStandardOutput (Join-Path $Root 'reports\_layers_run.txt') `
        -RedirectStandardError (Join-Path $Root 'reports\_layers_run.err')

    $last = (Get-Item $Ledger).LastWriteTime
    $stall = 0
    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 20
        $now = (Get-Item $Ledger).LastWriteTime
        if ($now -gt $last) { $last = $now; $stall = 0 } else { $stall += 20 }
        if ($stall -ge $StallSeconds) {
            Say "台账 $([math]::Round($stall/60,1)) 分钟未动，判定卡死，杀进程重来"
            Get-PyProcs | Where-Object { $_.ProcessId -ne $PID } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Start-Sleep -Seconds 5
            break
        }
    }

    if ($proc.HasExited -and $proc.ExitCode -eq 0) {
        Say "layers 正常结束（退出码 0）"
        Get-Content (Join-Path $Root 'reports\_layers_run.txt') |
            Select-String -Pattern 'TRACK_RESULT|幸存' | ForEach-Object { Say $_.Line }
        break
    }
}

Say 'layers --formal 结束'

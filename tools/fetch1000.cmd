@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set LOG=reports\_csi1000.log
echo [start] %DATE% %TIME% > %LOG%
for %%i in (0 1 2 3 4) do (
  start "" /b .venv\Scripts\python.exe -X utf8 tools\fetch_baostock.py --codes-file data\universe_csi1000.txt --shard %%i --nshards 5 --outdir data\shard1000_%%i --bs-ip 127.0.0.1 --bs-port 1103%%i >> %LOG% 2>&1
)
echo [launched 5 shards] >> %LOG%
:wait
timeout /t 30 /nobreak >nul
powershell -NoProfile -Command "if ((Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*universe_csi1000*' } | Measure-Object).Count -eq 0) { exit 0 } else { exit 1 }"
if errorlevel 1 goto wait
echo [all shards done] %TIME% >> %LOG%

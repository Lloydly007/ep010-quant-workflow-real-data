@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set LOG=reports\_r5.log
echo [start] %DATE% %TIME% >> %LOG%
.venv\Scripts\python.exe -X utf8 engine\run_batch.py --dir strategies\A\round5 --group A --workers 6 >> %LOG% 2>&1
echo [A done] %TIME% >> %LOG%
.venv\Scripts\python.exe -X utf8 engine\run_batch.py --dir strategies\B\round5 --group B --workers 6 >> %LOG% 2>&1
echo [B done] %TIME% >> %LOG%
.venv\Scripts\python.exe -X utf8 engine\funnel.py layers --formal --workers 6 >> %LOG% 2>&1
echo [layers done] %TIME% >> %LOG%
.venv\Scripts\python.exe -X utf8 engine\funnel.py shortlist --group AI >> %LOG% 2>&1
.venv\Scripts\python.exe -X utf8 engine\funnel.py shortlist --group monkey_43 >> %LOG% 2>&1
echo [all done] %TIME% >> %LOG%

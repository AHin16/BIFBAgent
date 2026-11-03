@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
echo BIFB 智能科研助手网页模式: http://127.0.0.1:8000
call conda run --no-capture-output -n BIFBAgent python run.py
pause

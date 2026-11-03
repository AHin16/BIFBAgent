@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
echo 正在打开 BIFB 智能科研助手独立窗口...
call conda run --no-capture-output -n BIFBAgent python desktop.py
if errorlevel 1 pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
call conda run --no-capture-output -n dbxm python run.py
pause

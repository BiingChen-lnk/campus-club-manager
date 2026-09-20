@echo off
chcp 65001 >nul
cd /d "%~dp0"
call conda env create -f environment.yml
pause

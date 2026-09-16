@echo off
title Alibaba Cloud DirectMail Agent
cd /d "%~dp0"
echo ======================================================================
echo Starting Alibaba Cloud DirectMail Automation Agent...
echo ======================================================================
echo URL: http://localhost:8000
echo.

start http://localhost:8000

python run.py
pause

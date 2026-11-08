@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Teste do gerente
python gerente.py
echo.
pause

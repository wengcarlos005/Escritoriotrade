@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Resultados da Agencia
python rodar.py resumo
echo.
pause

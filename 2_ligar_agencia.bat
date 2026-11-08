@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Agencia de Trade - deixe esta janela aberta
python rodar.py simular
pause

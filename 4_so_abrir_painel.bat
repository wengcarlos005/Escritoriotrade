@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Painel da Agencia
python rodar.py painel
pause

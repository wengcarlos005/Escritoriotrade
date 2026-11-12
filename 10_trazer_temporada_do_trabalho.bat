@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Trazer a temporada do trabalho
echo.
echo  Refaz aqui a temporada que comecou no PC do trabalho (10/11 as 12h):
echo  os traders tomam as MESMAS decisoes, vela por vela, ate agora.
echo.
echo  Feche a agencia antes (Ctrl+C na janela dela).
echo.
pause
python rodar.py reconstruir --inicio "2026-11-10 12:00"
echo.
pause

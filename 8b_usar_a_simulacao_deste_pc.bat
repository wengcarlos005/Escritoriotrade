@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Usar a simulacao deste PC
echo.
echo  Isto faz a simulacao DESTE PC valer em todos os seus PCs.
echo  (A que estiver na nuvem e substituida. Os outros PCs guardam uma copia de seguranca da deles.)
echo.
echo  Feche a agencia antes (Ctrl+C na janela dela).
echo.
pause
python rodar.py sincronia --usar-este
echo.
pause

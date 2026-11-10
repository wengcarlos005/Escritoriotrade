@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Conectar a conta da Binance
echo.
echo  Conecta a conta de FUTUROS da Binance pra copiar a agencia.
echo  A chave e digitada AQUI (nunca mande a chave pra ninguem, nem pro Claude).
echo  Rode este arquivo SO no PC que vai operar.
echo.
python rodar.py binance
echo.
pause

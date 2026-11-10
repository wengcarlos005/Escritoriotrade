@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Sincronizar a agencia entre PCs
where git >nul 2>nul || (echo Falta instalar o Git: https://git-scm.com/download/win & pause & exit /b)
echo.
echo  Isto liga a SINCRONIA: a mesma simulacao no PC do trabalho, no de casa, em qualquer um.
echo  (Rode este arquivo uma vez em cada PC.)
echo.
echo  1) So na PRIMEIRA vez: crie no GitHub um repositorio PRIVADO e VAZIO chamado escritoriotrade-dados.
echo     Vou abrir a pagina: deixe o nome, marque "Private" e clique em "Create repository".
echo     (Se ja criou antes, so feche a pagina.)
echo.
start "" "https://github.com/new?name=escritoriotrade-dados&visibility=private"
pause
echo.
echo  2) Ligando a sincronia neste PC...
python rodar.py sincronia
echo.
pause

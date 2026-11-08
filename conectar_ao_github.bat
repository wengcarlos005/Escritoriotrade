@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Conectar esta pasta ao GitHub
where git >nul 2>nul
if errorlevel 1 goto semgit
if exist ".git" goto jatem
echo Feche a janela da agencia antes de continuar.
pause
echo Conectando esta pasta ao GitHub...
echo Na primeira vez o navegador abre pra voce entrar na sua conta do GitHub.
git init -q
git remote add origin https://github.com/wengcarlos005/Escritoriotrade.git
git fetch origin main
if errorlevel 1 goto erro
if exist config.json ren config.json config_antigo.json
git checkout -f -B main --track origin/main
if errorlevel 1 goto erro
echo.
echo Pronto! Esta pasta agora atualiza pelo GitHub e seus dados continuam aqui.
echo Daqui pra frente, pra atualizar: atualizar.bat
echo Agora abra o 2_ligar_agencia.bat
pause
exit /b
:semgit
echo Falta instalar o Git. Vou abrir a pagina de download.
echo Instale com as opcoes padrao e rode este arquivo de novo.
start https://git-scm.com/download/win
pause
exit /b
:jatem
echo Esta pasta ja esta conectada ao GitHub. Use o atualizar.bat.
pause
exit /b
:erro
echo.
echo Nao consegui conectar. Mande uma foto desta tela pro Claude.
pause

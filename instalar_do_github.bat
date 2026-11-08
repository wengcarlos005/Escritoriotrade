@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalar a Agencia do GitHub
where git >nul 2>nul
if errorlevel 1 goto semgit
if exist "Escritoriotrade\.git" goto jatem
echo Baixando a agencia do GitHub...
echo Na primeira vez o navegador abre pra voce entrar na sua conta do GitHub.
echo.
git clone https://github.com/wengcarlos005/Escritoriotrade.git Escritoriotrade
if errorlevel 1 goto erro
if exist "agencia-de-trade\dados" xcopy /E /I /Y "agencia-de-trade\dados" "Escritoriotrade\dados" >nul
if exist "agencia-de-trade\dados" echo Seus dados da pasta antiga foram copiados: temporada, chave do gerente e historico.
echo.
echo Pronto! Na pasta Escritoriotrade, de dois cliques em 2_ligar_agencia.bat
echo Para atualizar no futuro: atualizar.bat
explorer Escritoriotrade
pause
exit /b
:semgit
echo Falta instalar o Git. Vou abrir a pagina de download.
echo Instale com as opcoes padrao e rode este arquivo de novo.
start https://git-scm.com/download/win
pause
exit /b
:jatem
echo A pasta Escritoriotrade ja existe. Use o atualizar.bat dentro dela.
pause
exit /b
:erro
echo.
echo Nao consegui baixar. Mande uma foto desta tela pro Claude.
pause

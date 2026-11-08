@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Atualizar a Agencia
where git >nul 2>nul || (echo Falta instalar o Git: https://git-scm.com/download/win & pause & exit /b)
echo Feche a janela da agencia antes de atualizar.
echo.
echo Baixando a versao mais nova do GitHub...
git pull --ff-only
if errorlevel 1 (
  echo.
  echo Algo deu errado. Mande uma foto desta tela pro Claude.
) else (
  echo.
  echo Pronto! Agora abra o 2_ligar_agencia.bat
)
pause

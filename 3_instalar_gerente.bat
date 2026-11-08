@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Instalando a biblioteca do Claude (gerente)...
python -m pip install --upgrade anthropic truststore
echo.
echo Pronto! Agora feche e abra a agencia de novo (2_ligar_agencia.bat).
echo Se quiser testar: 5_testar_gerente.bat
pause

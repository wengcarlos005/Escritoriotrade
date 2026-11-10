@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM Libera o escritorio (portas 8000-8019) no firewall do Windows SO para aparelhos da sua propria rede (celular no Wi-Fi de casa).
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Pedindo permissao de administrador...
  powershell -Command "Start-Process '%~f0' -Verb RunAs"
  exit /b
)
netsh advfirewall firewall delete rule name="Agencia de Trade (celular)" >nul 2>&1
netsh advfirewall firewall add rule name="Agencia de Trade (celular)" dir=in action=allow protocol=TCP localport=8000-8019 remoteip=localsubnet profile=any
echo.
echo Pronto! Agora ligue a agencia (2_ligar_agencia.bat) e abra no celular o endereco que aparece na janela.
echo (So aparelhos da sua rede local conseguem abrir, e pelo celular e so pra olhar.)
pause

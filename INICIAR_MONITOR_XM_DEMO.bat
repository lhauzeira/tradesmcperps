@echo off
setlocal
chcp 65001 >nul
title SMC Trading Agent - MONITOR DEMO SEM ORDENS
cd /d "%~dp0"

echo ===============================================================
echo  SMC TRADING AGENT - XM GOLD / SOMENTE CONTA DEMO
echo  Leitura do MT5. NUNCA envia ordens ou mensagens Telegram.
echo ===============================================================
echo.
echo  Deixe o MetaTrader 5 aberto e conectado a XMGlobal-MT5 5.
echo  O navegador mostrara a analise local e atualizara a cada 30s.
echo.

set "RUNPY="
py -3.11 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if not errorlevel 1 set "RUNPY=py -3.11"
if defined RUNPY goto PY_FOUND

py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if not errorlevel 1 set "RUNPY=py -3"
if defined RUNPY goto PY_FOUND

python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if not errorlevel 1 set "RUNPY=python"
if defined RUNPY goto PY_FOUND

echo  PYTHON 3.11 ou superior nao foi encontrado.
echo  Instale pelo site oficial: https://www.python.org/downloads/windows/
echo  Durante a instalacao, habilite "Add python.exe to PATH".
echo  Depois volte a executar este arquivo.
goto END

:PY_FOUND
echo  Interpretador: %RUNPY%
%RUNPY% -c "import MetaTrader5" >nul 2>&1
if not errorlevel 1 goto START_MONITOR

echo.
echo  Falta a biblioteca MetaTrader5 para ler os precos da plataforma.
echo  Instalar pacote do Python agora? (Requer Internet.)
choice /C SN /M "S=instalar, N=cancelar"
if errorlevel 2 goto END
%RUNPY% -m pip install --user MetaTrader5
if errorlevel 1 goto INSTALL_ERROR

:START_MONITOR
echo.
echo  Iniciando... o arquivo MONITOR_LOCAL_DEMO.html abrira no navegador.
echo  Esta janela deve permanecer aberta para continuar monitorando.
echo  Para encerrar o monitor: Ctrl+C, depois confirme se solicitado.
echo.
%RUNPY% -m smc_agent.monitor_local --intervalo 30
goto END

:INSTALL_ERROR
echo.
echo  Nao foi possivel instalar o conector MT5.
echo  Confira a Internet e sua versao do Python e tente novamente.
goto END

:END
echo.
echo  Encerrado. NENHUMA ORDEM FOI EXECUTADA PELO AGENTE.
pause
endlocal

@echo off
setlocal
chcp 65001 >nul
title SMC Agent - MULTIATIVOS XM CONTA DEMO
cd /d "%~dp0"
echo ==============================================================
echo SMC TRADING AGENT - MULTIATIVOS - XM MT5 DEMO
echo Somente leitura / Sem ordens / Sem envio ao Telegram
echo ==============================================================
echo.
echo Edite ATIVOS_DEMO.txt para escolher os instrumentos disponiveis.
echo Deixe o MT5 aberto na conta DEMO do XMGlobal-MT5 5.
echo.
py -3.11 -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 goto NO_CONNECTOR
py -3.11 -m smc_agent.multi_monitor --intervalo 30
goto DONE
:NO_CONNECTOR
echo Nao encontrei Python 3.11 + conector MetaTrader5.
echo Volte ao monitor de GOLD e conclua a instalacao do conector.
:DONE
echo.
echo Monitor finalizado. Nenhuma ordem foi enviada.
pause
endlocal

@echo off
setlocal
chcp 65001 >nul
title SMC AGENT - GERENCIADOR DE RISCO 0.14 OFFLINE
cd /d "%~dp0"
echo ==============================================================
echo SMC AGENT v0.14 - TESTE DE RISCO MULTIATIVOS
echo SOMENTE DADOS FICTICIOS / SEM CONSULTAR CONTA / ZERO ORDENS
echo ==============================================================
echo.
py -3.11 -m smc_agent.multi_risk
if errorlevel 1 goto FAILED
echo.
echo TESTE FICTICIO DE RISCO CONCLUIDO.
echo Execute TESTAR_CODIGO_OFFLINE.bat para validar todos os testes.
goto END
:FAILED
echo.
echo ERRO: envie a mensagem sem credenciais.
:END
echo.
pause
endlocal

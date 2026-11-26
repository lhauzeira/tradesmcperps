@echo off
setlocal
chcp 65001 >nul
title SMC AGENT - ENSAIO FICTICIO DE ABERTURA E FECHAMENTO
cd /d "%~dp0"
echo ==============================================================
echo SMC AGENT - ENSAIO DE ORDENS SOMENTE FICTICIAS
echo SEM ACESSO AO MT5 E SEM ORDENS REAIS NEM DEMO
echo NENHUM RESULTADO EM DINHEIRO
echo ==============================================================
echo.
py -3.11 -m smc_agent.paper_execution
if errorlevel 1 goto FAILED
echo.
echo Fim do ensaio sintetico. Para teste com MT5, use o monitor DEMO.
goto END
:FAILED
echo.
echo Falha no ensaio. Envie a mensagem exibida, sem credenciais.
:END
echo.
pause
endlocal

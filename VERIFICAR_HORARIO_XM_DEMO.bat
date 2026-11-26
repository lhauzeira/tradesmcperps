@echo off
setlocal
chcp 65001 >nul
title SMC Agent - VERIFICAR HORARIO XM DEMO
cd /d "%~dp0"
echo ============================================================
echo  SMC AGENT - DIAGNOSTICO DE HORARIO (XM GOLD DEMO)
echo  Somente leitura. Nao envia ordens. Nao mostra dados da conta.
echo ============================================================
echo.
echo Mantenha o MetaTrader 5 aberto e conectado na conta DEMO.
echo.
py -3.11 --version >nul 2>&1
if errorlevel 1 goto NO_PYTHON
py -3.11 -m smc_agent.clock_diagnostic
goto END

:NO_PYTHON
echo O Python 3.11 nao foi localizado pelo comando py -3.11.
echo Nao e preciso instalar o Python novamente sem verificarmos.
echo Envie uma captura desta janela, sem numero de conta.

:END
echo.
echo Envie uma captura de tela apenas do resultado deste diagnostico.
echo Evite incluir dados pessoais ou numero de conta na imagem.
pause
endlocal

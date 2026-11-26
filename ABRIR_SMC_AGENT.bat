@echo off
setlocal
chcp 65001 >nul
title SMC TRADING AGENT - PACOTE UNIFICADO
cd /d "%~dp0"
:MENU
cls
echo ==============================================================
echo           SMC TRADING AGENT - PACOTE UNIFICADO
echo ==============================================================
echo 1 - VALIDAR TUDO: testes + paper ficticio + risco ficticio
echo 2 - INICIAR MONITOR MT5 DEMO MULTIATIVOS: SEM ORDENS
echo 3 - VERIFICAR O QUE O AGENTE FAZ E O QUE AINDA NAO FAZ
echo 4 - DIAGNOSTICO DOS CONTRATOS XM DEMO (SOMENTE LEITURA)
echo 5 - SAIR
echo.
echo ATENCAO: o modo de ordens automaticas NAO esta habilitado.
echo.
choice /C 12345 /N /M "Escolha uma opcao (1 a 5): "
if errorlevel 5 goto END
if errorlevel 4 goto DIAGNOSTIC
if errorlevel 3 goto STATUS
if errorlevel 2 goto MONITOR
if errorlevel 1 goto TEST
goto END
:TEST
echo.
echo Rodando TODOS os testes e ensaios offline. Aguarde...
if not exist "monitoramento_privado" mkdir "monitoramento_privado"
set "TEST_LOG=%CD%\monitoramento_privado\resultado_testes_unificados.txt"
py -3.11 -m smc_agent.unified --validar-tudo > "%TEST_LOG%" 2>&1
set "TEST_EXIT=%ERRORLEVEL%"
type "%TEST_LOG%"
echo.
echo Resultado salvo SOMENTE neste computador:
echo "%TEST_LOG%"
if not "%TEST_EXIT%"=="0" goto FAILED
echo.
echo Para iniciar o monitor, volte ao menu e escolha opcao 2.
pause
goto MENU
:MONITOR
echo.
echo Monitor somente leitura. Mantenha MT5 DEMO e esta janela abertos.
echo Para parar o monitor, use Ctrl+C ou feche esta janela.
echo Nenhuma ordem sera enviada.
echo.
py -3.11 -m smc_agent.unified --monitor-demo --intervalo 30
echo.
pause
goto MENU
:STATUS
echo.
py -3.11 -m smc_agent.unified --status
echo.
pause
goto MENU
:DIAGNOSTIC
echo.
echo Inventario de instrumentos XM DEMO: conta e especificacoes, ZERO ORDENS.
py -3.11 -m smc_agent.unified --diagnostico-demo
echo.
pause
goto MENU
:FAILED
echo.
echo ALGUM TESTE FALHOU. NAO INICIE OPERACOES.
echo Envie a mensagem completa sem dados pessoais.
pause
goto MENU
:END
echo.
echo Encerrando o painel unificado. Zero ordens enviadas.
endlocal

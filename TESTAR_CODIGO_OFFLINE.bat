@echo off
setlocal
chcp 65001 >nul
title SMC Agent - TESTE OFFLINE SEM ORDENS
cd /d "%~dp0"
echo ===============================================================
echo  SMC TRADING AGENT - TESTES AUTOMATICOS LOCAIS
echo  Sem abrir conta MT5, sem chaves e sem enviar ordens.
echo ===============================================================
echo.
py -3.11 --version >nul 2>&1
if errorlevel 1 goto NO_PYTHON
echo Rodando testes sinteticos, sem acessar a corretora...
py -3.11 -m unittest discover -s tests -q
if errorlevel 1 goto TEST_FAILED
echo.
echo  TESTES OFFLINE CONCLUIDOS COM SUCESSO.
echo  Isso NAO comprova conexao real, eficacia ou lucro do robô.
goto END
:TEST_FAILED
echo.
echo  ALGUM TESTE FALHOU. Envie a mensagem, omitindo dados pessoais.
goto END
:NO_PYTHON
echo  Python 3.11 nao localizado pelo comando py -3.11.
:END
echo.
pause
endlocal

# SMC Trading Agent — Builders Prototype

**Status:** experimental, deterministic trading-research prototype. **No real or simulated brokerage orders are sent.** No returns or pass rates are claimed.

A proof-of-concept that transforms selected Smart Money Concepts (SMC) rules into reproducible Python analysis:
- macro structure using confirmed fractal highs/lows;
- candle-close break of structure (BOS);
- full-wick order block (OB) with 50% mitigation;
- candle-close confirmation for entry proposals;
- conservative per-trade risk gate;
- separate read-only adapters for MT5 (XM) and MyFundedPerps sandbox.

This is a compact implementation. Additional experiments with ATR-confirmed ZigZag, liquidity and volume confluences are maintained separately and still need to be reconciled.

## Diagnóstico de horário XM / MT5 (v0.9 em revisão)

A primeira integração na conta DEMO revelou um alerta legítimo de segurança:
o timestamp do último candle M5 parece estar **no futuro** em relação
ao horário UTC informado pelo computador. Ainda não está claro se a causa
é a convenção de tempo do servidor XM, o sistema operacional ou a
interpretação da API Python.

**Não desative o bloqueio e não force GMT+3.**

Com o MetaTrader 5 aberto na conta DEMO, rode por duplo clique
`VERIFICAR_HORARIO_XM_DEMO.bat`. O script compara apenas os tempos
brutos de M5, H1 e tick com o relógio do computador e os imprime para
diagnóstico, sem exibir número de conta ou saldo. Os horários exibidos
como UTC são **interpretações provisórias** dos valores retornados, não
confirmação do fuso real.

O monitor também passa a indicar explicitamente o provável problema
de comparação de horários e continua recusando novos sinais enquanto
o horário não for validado. Uma futura correção de fuso deverá ser
evidenciada em amostras atuais e históricas, sem alterar indevidamente
o horário de publicação dos sinais.

## Teste prático no Windows com MT5 / conta DEMO (v0.8 em revisão)

O experimento agora tem um **monitor local** para o ouro da XMGlobal-MT5 5.
Consulte [COMO_TESTAR_NO_WINDOWS.txt](COMO_TESTAR_NO_WINDOWS.txt).

1. Abra o MetaTrader 5 da XM na conta **DEMO** e selecione GOLD.
2. Baixe esta branch como ZIP, extraia a pasta inteira e tenha
   Python 3.11+ disponível (o script informa como instalar).
3. Dê dois cliques em **INICIAR_MONITOR_XM_DEMO.bat**.
4. Confirme a instalação opcional do pacote oficial MetaTrader5 para Python
   (somente se não estiver instalado).
5. Veja **MONITOR_LOCAL_DEMO.html** abrir no navegador. O monitor
   acompanha candles fechados M5 e H1, mostra o viés e eventuais propostas
   SMC. Mantenha a janela do programa aberta; Ctrl+C encerra.

O software bloqueia contas reais, servidores inesperados e dados sem
frescor. Todos os registros ficam **apenas no PC** em monitoramento_privado,
pasta excluída pelo Git. Não acessa histórico privado do Telegram.
Nenhuma ordem é enviada; nenhum retorno é calculado nem prometido.
O teste de integração com a instalação XM real do usuário **ainda não foi
executado**; os testes automatizados usam um terminal simulado.

## Demonstration

Requires Python 3.11+ and no third-party packages:

    python -m unittest discover -s tests -v
    python -m smc_agent.demo

The CLI demo reports deterministic metrics about **synthetic candles**, and expressly confirms that zero orders were sent and that no real market data was used.

The same commands run in [GitHub Actions](https://github.com/lhauzeira/tradesmcperps/actions). See [detailed demo instructions](builders/DEMO.md).

## Integrations

**MetaTrader 5 (XM):** The adapter provides a local terminal-based historical candle reader. Requires Windows, an MT5 terminal, and a separately installed MetaTrader5 Python package. It has not been tested against a personal account.

**MyFundedPerps:** The sandbox adapter is read-only, requires an API key beginning in fp_test_, and intentionally rejects live keys. The API is in beta; verify endpoint stability and your actual access before connecting. **Never commit API keys, passwords or personal credentials.**

**Execution methods deliberately raise exceptions.** Safety, broker contract specifications, bid/ask, costs, historical forward tests and prop-firm limits have not been validated.

## Roadmap

1. Confirm automated tests and reproduce the demo.
2. Integrate additional algorithmic features from the richer local prototype.
3. Validate time-aligned native feeds and account policies in read-only mode.
4. Perform realistic backtesting and out-of-sample analysis.
5. Design and test an idempotent sandbox execution adapter with protected exits.
6. Review risk compliance before any trading or account purchase.

Project status: [PROJECT_STATUS.md](PROJECT_STATUS.md).

*Research software only. This is not investment advice.*

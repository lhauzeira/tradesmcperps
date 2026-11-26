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

## v0.13 — Primeiro portão de segurança antes de ordens DEMO

O monitor multiativos agora exibe, em cada instrumento, um diagnóstico de
pré-execução no painel PAINEL_MULTI_DEMO.html, além dos sinais teóricos:

- Cotação Bid/Ask e horário do tick reconciliado com o computador.
- Falta de atualização, relógio incoerente, preço inválido e volatilidade.
- Spread relativo ao ATR dos últimos 14 candles M5 já fechados, calculado
  na **escala de preço de cada ativo** (não em pips/dólares fixos).
- Informações de contrato como tick size, tick value, point, volume mínimo,
  máximo, passo e modo de negociação que o MT5 informou.
- **SESSAO_OU_FERIADO_NAO_VERIFICADO** é intencional: modo de negociação
  e chegada de ticks NÃO garantem sessão aberta. Ainda precisamos validar
  os horários/feriados específicos da XM por instrumento.

O filtro experimental de spread > 25% do ATR M5 é um parâmetro de
diagnóstico para estudos; não é garantia de execução adequada, não foi
ajustado a estatísticas reais e **não altera os sinais SMC** da v0.12.

Os resultados de pesquisa são registrados por símbolo em
monitoramento_privado/analises_multi.jsonl, SEM conta, senha ou saldo.
O monitor antigo GOLD continua com seu comportamento anterior.

NÃO há ordens, fechamento de posições, envio ao Telegram, execução
simulada contabilizada como real, leitura de posições ou permissão para
operar. Em código, ReadinessReport.can_submit_orders é sempre False.
Mesmo com todas as cotações coerentes, um teste adicional de sessão
verificada não equivale a autorização para operar.

Próximos marcos antes de qualquer ordem demo: contrato real por símbolo,
horários especiais de cada CFD, risco/tamanho com moeda da conta e
margem, simulador de estados/rejeições/duplicidade, kill switch, teste
prospectivo em conta DEMO e autorização explícita do usuário.

Para testar localmente: TESTAR_CODIGO_OFFLINE.bat, seguido de
INICIAR_MONITOR_MULTIATIVOS_DEMO.bat, com XMGlobal-MT5 5 DEMO conectado.
O código **ainda não foi validado com seus dados ao vivo na v0.13**.

## Monitor multiativos + Fibonacci OTE (v0.12 experimental)

A versão 0.12 adiciona um scanner independente, **somente leitura**,
que recebe uma lista de até 12 instrumentos no arquivo ATIVOS_DEMO.txt.
O usuário não precisa editar código: basta escrever um símbolo por linha,
exatamente como aparece em Observação do Mercado do MT5 XM DEMO.
O scanner mostra viés H1, análise SMC M5, Bid, Ask, spread na escala
decimal correta de cada ativo e níveis de retração Fibonacci.

- Executável por duplo clique: INICIAR_MONITOR_MULTIATIVOS_DEMO.bat
- Painel HTML local: PAINEL_MULTI_DEMO.html
- Testes de componentes sem corretora: TESTAR_CODIGO_OFFLINE.bat
- Instruções técnicas e de segurança: builders/MULTIASSET_FIBONACCI.md

Fibonacci é calculado a partir de pivôs já confirmados, incluindo os
níveis 50%, 61,8%, 70,5% e 78,6%. A faixa 61,8–78,6% é uma hipótese
de confluência OTE e **não** comprova vantagem estatística.

A opção require_fibonacci=True no motor permite pesquisa de um filtro
mais restritivo (zona OTE com reteste e overlap de Order Block).
**Desligada por padrão**, inclusive nos monitores, para permitir
experimentos A/B sem mudar silenciosamente a estratégia GOLD já usada.

A cobertura é genérica para ativos disponíveis no terminal XM e com
cotações/timestamps válidos. Não significa compatibilidade automática
com todo instrumento de toda corretora e não aplica contratos GOLD ao
restante dos mercados. A plataforma MFP precisa de seu próprio conector
e validação. Em nenhuma hipótese há envio de ordens.

O scanner v0.12 ainda precisa ser testado no computador do usuário; o
monitor anterior GOLD foi integrado com sucesso anteriormente.

## Monitor ativo XM demo com deslocamento observado (v0.10 experimental)

O primeiro diagnóstico do usuário em 2026-11-26 encontrou **tick do GOLD
+7200 segundos** e candles M5/H1 coerentes com o mesmo relógio de exibição.
Isso justifica um tratamento **somente ao vivo** e provisório, não uma
conversão de histórico sem verificação.

`smc_agent.live_clock.reconcile_live_clock` detecta e valida a diferença
entre o tick recente, o PC UTC e os últimos candles fechados M5/H1 a cada
ciclo. Os deslocamentos possíveis (0h, +2h, +3h) são **candidatos testados**,
nunca ajustes aplicados sem uma cotação compatível. Tick antigo, relógio
futuro, barra em formação, divergência entre M5/H1 e tick ou conta não
DEMO interrompem a análise antes de emitir sinais.

O painel local indica explicitamente um **deslocamento observado,
provisório**. A data de fechamento dos eventos SMC é convertida apenas
para esse monitor ao vivo. O histórico de junho, as sessões de negociação
históricas, resultados de backtest e execução de ordens permanecem
desabilitados/não validados.

No Windows, com o MT5 na conta DEMO:

1. Baixe o ZIP da branch `feature/mt5-live-clock-v10` e extraia tudo.
2. Opcionalmente, execute `TESTAR_CODIGO_OFFLINE.bat` para os testes locais
   sem conexão com a corretora.
3. Execute `INICIAR_MONITOR_XM_DEMO.bat` (o mesmo nome anterior).
4. Observe no navegador o painel `MONITOR_LOCAL_DEMO.html`.
5. Encerre com Ctrl+C na janela do monitor.

Os testes de integração com o terminal XM real ainda dependem da próxima
execução no computador do usuário. Não operar com alertas experimentais.

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

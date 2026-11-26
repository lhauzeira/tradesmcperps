# v0.12 — Multiativos + Fibonacci SMC (PESQUISA, SEM ORDENS)

## O que muda — e o que NÃO muda

- O motor SMC H1/M5 continua o mesmo. O monitor GOLD anterior permanece
  funcionando, e Fibonacci NÃO é imposto aos sinais existentes.
- O novo scanner abre uma única sessão de leitura XM/MT5 DEMO e consulta
  até 12 símbolos escolhidos pelo usuário, independentemente.
- A configuração é ATIVOS_DEMO.txt, um símbolo como aparece no MT5
  por linha. Linhas iniciadas com # são comentários.
- GOLD é o único símbolo ativo por padrão; EURUSD, GBPUSD, USDJPY,
  US100Cash, US500Cash e BTCUSD são apenas exemplos. O nome e
  disponibilidade precisam ser confirmados no terminal XM.
- PAINEL_MULTI_DEMO.html é uma página local com Bid/Ask, spread,
  viés H1, contexto Fibonacci e sinais SMC de pesquisa.
- Cada símbolo usa sua precisão decimal (symbol_info.digits).
  NÃO usa tick, lote, tamanho de contrato ou taxas GOLD para outro ativo.
- Um mercado ausente ou sem dados recentes aparece como indisponível,
  sem interromper as análises dos demais.
- Os registros por símbolo ficam localmente em SQLite e JSONL, com IDs
  deduplicados. Sem ordens, sem mensagens Telegram nem chaves de API.
- A conta XM deve ser DEMO no servidor XMGlobal-MT5 5.

## Fibonacci: regras reproduzíveis e sem olhar para o futuro

O módulo smc_agent/fibonacci.py utiliza somente candles já fechados.
O swing é definido por pivôs/fractais com confirmação de dois candles
posteriores (wing=2). Um extremo novo não é utilizado antes de ser
confirmado.

Para compras, parte de pivô baixo confirmado para pivô alto confirmado.
Para vendas, parte de pivô alto para pivô baixo. Desconsidera impulsos
pequenos em relação ao ATR. Usa os últimos 120 candles e máximo de
80 candles de duração do impulso.

Níveis de retração:

- Alta (fundo L para topo H): H - r × (H-L)
- Baixa (topo H para fundo L): L + r × (H-L)

Níveis r = 0,50; 0,618; 0,705 e 0,786.
Zona OTE experimental = níveis de 61,8% a 78,6%.

O algoritmo distingue preço na zona, reteste recente,
aguardando retração e swing invalidado por fechamento além da origem.

O motor possui filtro opcional require_fibonacci=True:
exige impulso confirmado, toque recente da zona e interseção
dessa zona com o Order Block para aceitar sinal.
**O filtro está desligado por padrão.** Os níveis aparecem para
observação nos painéis, sem mudar sinais até validarmos a estratégia.

Confluência Fibonacci NÃO prova causalidade, resultado positivo nem
melhoria de acerto. A comparação A/B precisa usar períodos históricos
e testes prospectivos, com spread, custos, slippage, taxa de
rejeição, amostra suficiente, drawdown e resultados inconclusivos.
Proibido escolher parâmetros com base no mesmo período de avaliação.

## Como usar no Windows sem programar

1. Encerre o monitor antigo do GOLD com Ctrl+C.
2. Baixe a branch feature/multiasset-fibonacci-v12 em ZIP e Extraia Tudo.
3. Abra ATIVOS_DEMO.txt no Bloco de Notas e escreva, um por linha,
   os nomes exatos dos instrumentos que constam no seu MT5.
   Remova o # de uma linha apenas se quiser ativar o símbolo.
4. Deixe o MT5 XMGlobal-MT5 5 aberto na conta DEMO.
5. Execute TESTAR_CODIGO_OFFLINE.bat se quiser validar os testes sintéticos.
6. Dê dois cliques em INICIAR_MONITOR_MULTIATIVOS_DEMO.bat.
7. Observe PAINEL_MULTI_DEMO.html no navegador. Deixe a janela preta
   aberta; a página pode ser fechada.
8. Encerre o monitor com Ctrl+C.

**Se não existir o símbolo exato na XM, aparecerá "Não avaliado".**
Não confunda contratos CFD da XM com futuros da MFP, ainda sem integração.

## Restrições

- O scanner multiativos v0.12 ainda precisa de teste real no computador.
- O offset observado ao vivo, verificado com tick/M5/H1, NÃO normaliza
  automaticamente o histórico de junho nem outras plataformas.
- Os parâmetros financeiros e regras de risco devem ser definidos por
  instrumento e provedor, antes de calcular lotes ou resultados reais.
- Sem ordens; sem previsão comprovada; sem retornos validados.

# SMC Trading Agent — estado real do projeto

**Integração atual:** release/smc-unificado-rc1. Candidata de pesquisa,
não uma versão lucrativa comprovada e NÃO um executor de ordens.

## Componentes integrados e situação

| Módulo | Situação |
|---|---|
| MT5 XMGlobal-MT5 5 DEMO | Leitura multiativos previamente validada pelo usuário em GOLD, US100Cash, US500Cash |
| SMC H1/M5 | Gatilho teórico experimental preservado, sem execução |
| Fibonacci OTE M5 | Análise observacional; filtro opcional, desligado no monitor |
| H4/H1/M30/M15/M5 | Análise adicional de estrutura confirmada em cinco períodos; **nova nesta candidata e ainda não validada no PC do usuário** |
| Pesquisa de confluência | Registra se H4 e M30/M15/M5 concordam com a direção; ainda não pode concluir que isso melhora a expectativa |
| Relógio de corretora | Deslocamento AO VIVO provisório inferido com tick, H1 e M5; não implica fuso histórico |
| Pré-execução | Checa spread relativo a ATR, preços, tick e contrato; feriados/sessões continuam não verificados |
| Gerenciamento de risco | Orçamentos hipotéticos com preços e capital fictícios, não consulta a conta |
| Ciclo buy/sell stop/target | Ensaio fictício separado, sem conexão com o MT5 |
| Diário | JSONL e SQLite local para sinais; não representam operações reais |
| MFP | Adaptador sandbox experimental; contrato ainda não homologado |
| Abertura/fechamento no MT5 | NÃO IMPLEMENTADO / NÃO HABILITADO |
| Lucratividade | NÃO DEMONSTRADA |

## Testes

- Usuário confirmou 264 testes offline **OK** na v0.13 em 2026-11-26.
- Foram acrescentados testes offline posteriores para risco, iniciador único,
  cinco períodos e classificação de confluência.
- **Não** se deve afirmar que esses testes novos passaram: a validação
  integrada ainda está pendente. GitHub Actions tem apresentado
  falha de inicialização antes de executar os trabalhos.
- O iniciador único ABRIR_SMC_AGENT.bat executa a suíte e os
  exemplos fictícios de ciclo e orçamento de risco.

## Medição dos cinco períodos

A versão atual usa a estratégia H1/M5 original para gerar sinais de
pesquisa, preservando a comparação histórica com versões anteriores.
H4, M30, M15 e o viés estrutural M5 são observações adicionais que
ficam registradas no mesmo evento, sem alterar entrada ou stop.
Somente depois de obter resultados de sinais com timestamps
verificáveis será possível avaliar, fora da amostra, se exigir
alinhamento desses períodos melhora a expectativa líquida.

**Proteção:** o período adicional é obtido via MT5 starting position 1,
não utiliza candle em formação, não promete fuso histórico e fica
INDISPONIVEL quando o último fechamento falha nas verificações.
Indisponibilidade não equivale a tendência neutra.

## Para habilitar, no futuro, qualquer ordem DEMO

1. Validar ao vivo os cinco períodos, timezone, atrasos e períodos de negociação.
2. Reconciliar moeda da conta, tick value de perda, margem,
   comissões, swaps, regras de volume e stop level para cada ativo.
3. Construir armazenamento transacional e sincronização de ordens/
   posições da conta, com recuperação após reinício e falhas.
4. Implementar executor estritamente DEMO, desligado por padrão,
   com autorização explícita, exclusividade da conta permitida
   e verificação dos resultados reportados pelo MT5.
5. Testar recusas, execução parcial, alteração de spreads, lacunas,
   ordens duplicadas, regras de perda diária e encerramento de emergência.
6. Executar teste prospectivo em conta DEMO e analisar resultados
   líquidos/expectativa e comportamento fora da amostra.
7. MyFundedPerps: integração específica, distinta dos CFDs XM,
   somente depois de verificar API e regras atuais.

**Meta:** agente autônomo com gestão verificável. **Não confundir**
capacidade operacional com vantagem lucrativa comprovada.

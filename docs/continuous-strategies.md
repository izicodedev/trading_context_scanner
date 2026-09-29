# Simulação contínua de três hipóteses

> A seleção e a interface foram atualizadas na versão 3. Consulte
> [strategy-research.md](strategy-research.md). As regras fixas abaixo descrevem
> a versão inicial preservada para sessões legadas; os custos continuam aplicáveis.

A rota Vue `/simulator` agora apresenta somente um controle de simulação:
ativar ou parar. Não há ordens reais nem conexão com uma conta de negociação.

## Processos e persistência

1. Aplicar migrations com `python -m app.user_migrations migrate`.
2. Manter `python -m app.main` coletando candles para PostgreSQL.
3. Manter `python -m app.strategy_worker` executando. Há uma unidade systemd
   em `deploy/trading-context-strategies.service` para instalação posterior.
4. Manter a API Flask e o frontend em execução.

Todos os processos precisam do mesmo DATABASE_URL. A migration 003 adiciona
strategy_sessions por usuário, com configuração, amostra histórica, estado,
heartbeat e métricas JSONB. Nenhum deploy é realizado automaticamente.

A migration 011 separa as sessões por usuário e moeda. O worker acompanha todas
as sessões ativas de BTCUSDT e ETHUSDT independentemente da moeda exibida na
tela. Veja [multi-market.md](multi-market.md) para importação e coleta contínua.

GET/POST `/api/simulator/live` exigem autenticação e usam o usuário da sessão.
POST recebe `{"active": true}` ou `{"active": false}`. A ativação é idempotente
enquanto a sessão já estiver ativa. A parada encerra virtualmente as posições
no último candle fechado. Uma reativação começa uma nova sessão e substitui
o resumo anterior; não é uma pausa e retomada da mesma banca.

O worker consulta a cada 15 segundos, independente do navegador, e processa
novos candles fechados. A tela consulta o estado a cada 10 segundos. Os ciclos
por usuário são serializados com lock no banco. Sessões sobrevivem à reinicialização
do worker. O replay determinístico evita duplicar operações ao repetir um ciclo.
Um heartbeat atrasado ou dados desatualizados são informados na interface.

## Hipóteses fixas v1

Todas usam BTCUSDT spot da Binance em 5m, indicadores existentes, 60 candles de
warm-up e no máximo uma posição por hipótese. LONG e SHORT são simétricos.

| Hipótese | Alavancagem | Stop mínimo | Multiplicador ATR | Target | Expiração |
| --- | --- | --- | --- | --- | --- |
| Pullback de tendência | 5x | 0,6% | 1,5 | 2R | 36 candles |
| Rompimento com volume | 10x | 0,5% | 1,3 | 2R | 24 candles |
| Reversão de excesso | 15x | 0,4% | 1,2 | 2R | 18 candles |

As condições exatas estão centralizadas em strategy_lab.decision. O candle
fechado i determina o sinal; a abertura de i+1 determina a entrada. Não há
otimização retrospectiva nem seleção automática de parâmetros vencedores.

Cada banca virtual começa com US$ 1.000 e aloca 25% do saldo realizado como
margem. Notional = margem × alavancagem; quantidade = notional / entrada.
Não somar os retornos das três bancas como se fossem uma carteira compartilhada.

## Histórico e acompanhamento

Ao ativar, o histórico usa até os últimos 1.000 candles fechados armazenados.
Essa amostra curta é congelada como referência, não validação out-of-sample.
Posições pendentes na fronteira histórica são encerradas em SAMPLE_END.
O acompanhamento inicia com uma banca independente e só permite entradas em
aberturas posteriores à ativação. Os resultados ao vivo são simulações em candles
fechados, não fills em ticks de mercado: são atualizados quando o candle entra no banco.

O replay ao vivo conserva o início da amostra e suporta até 50.000 candles.
Lacunas impedem o avanço, em vez de ocultar períodos desconhecidos. O resultado
anterior permanece visível com erro. Depois de interrupções, completar o histórico
permite recuperar a sessão. O scanner tenta recompor candles fechados desde a
última abertura gravada após uma pausa; lacunas na fonte geram erro e nova
tentativa no ciclo seguinte.

## Custos e limitações

LabConfig centraliza as premissas e é salva na sessão:

- Fee de 0,045% do notional em cada ponta, sem assumir maker, descontos ou builder fee.
- Slippage fixo de 0,02% em cada ponta, cobrado separadamente do PnL de preço.
- Funding hipotético de 0,00125% por hora UTC atravessada: LONG paga, SHORT recebe.
- Manutenção de margem de 0,5% para um preço de liquidação isolada aproximado.

Fee padrão baseada na tabela pública de perpétuos da Hyperliquid:
https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees
Funding é configurável e hipotético, sem histórico real de funding:
https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding
Liquidação real depende de mark price e regras da plataforma:
https://hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations

Não se pretende reproduzir uma conta Hyperliquid. O preço de liquidação aproximado
não ajusta dinamicamente funding, tiers ou collateral; gaps executam no open e
podem produzir perdas superiores à margem isolada na estimativa conservadora.
O saldo pode ficar negativo nesse cenário e novas entradas deixam de ocorrer.
Stops e targets usam o TradeSimulator, com stop primeiro em candle ambíguo.

## Métricas

Acerto = fechadas com net_pnl positivo / total de fechadas. Empates permanecem
no denominador. Fees, funding e slippage são contabilizados nas fechadas; a
banca inclui o valor estimado de liquidação da posição aberta, com custos.
Drawdown usa essa curva marcada no fechamento dos candles, não extremos intrabar.
Profit factor sem perdas é nulo (exibido como travessão), não zero.

Retornos diários usam America/Sao_Paulo. Primeiro e último dias da amostra são
parciais e não contam para a frequência de cumprimento da meta diária. A meta de
5% é somente referência. A alavancagem amplia perdas e não altera a taxa de acerto
das barreiras; custos e liquidação podem alterar o resultado líquido das posições.

Testes: `python -m pytest -q`. Build: `npm run build` na pasta frontend.

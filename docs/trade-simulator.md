# TradeSimulator: primeira etapa

## Interface local

Com Flask na porta 5000 e Vite na porta 5173, abra
`http://127.0.0.1:5173/simulator`. A página exige a sessão existente da aplicação
e consulta candles do PostgreSQL por padrão, com seleção de ativo/timeframe,
período disponível, entrada e horizonte. JSON manual e dois exemplos sintéticos
continuam disponíveis em uma fonte separada. O formulário chama `POST /api/simulator`,
protegido pela mesma autenticação do dashboard. O limite é 5.000 candles e
2 MB por requisição. Os resultados não são persistidos. `GET /api/simulator/datasets`
lista os históricos disponíveis. POST usa `data_source=database` por padrão;
para enviar candles em JSON, informe explicitamente `data_source=manual`.

## Preparar histórico no banco

Com DATABASE_URL carregada no ambiente:

```text
python -m app.user_migrations migrate
python -m app.import_candles --symbol BTCUSDT --limit 1000
```

A migration 002 cria market_candles, separada dos sinais. A chave é
source/symbol/timeframe/open_time; a importação pode ser repetida sem duplicar
candles. A fonte inicial é binance_spot. O comando importa janelas recentes de
5m, 15m e 1h (até 1.000 candles por período, excluindo o candle ainda aberto).
Não equivale a um backfill arbitrário de 90 dias.

O scanner passa a armazenar os candles fechados dos seus ciclos quando há
DATABASE_URL. Erros de armazenamento de candles são registrados sem impedir
a persistência do sinal. A consulta do simulador não acessa a Binance e não
reconstrói OHLCV a partir dos registros de sinais. Lacunas ou início ausente
geram erro explícito; histórico que termina antes do horizonte continua
produzindo INSUFFICIENT_DATA se nenhuma barreira tiver sido tocada.

Em hospedagem do frontend Vue, o servidor precisa encaminhar `/simulator`
para o index.html da SPA, como nas demais rotas do frontend. Nenhuma mudança
de hospedagem ou deploy está incluída nesta implementação.

Motor de barreiras de preço em `app/trade_simulator.py`, independente de exchange,
indicadores, persistência e scanner. Não é chamado pelo loop de produção.
O paper trading e a avaliação legados permanecem inalterados.

## Uso

```python
import pandas as pd
from app.trade_simulator import TradeSimulator, TradeSpec, SimulationConfig

trade = TradeSpec(
    symbol="BTCUSDT", timeframe="15m", side="LONG",
    entry_price=84000, entry_time=pd.Timestamp("2026-01-01T00:00:00Z"),
    stop_price=83160, target_price=86520,
)
# candles: DataFrame histórico no formato retornado por BinanceClient.klines
result = TradeSimulator().simulate(trade, candles, SimulationConfig(max_candles=96))
```

## Contrato e premissas

- A entrada já foi executada no preço e instante informados. Stop e target são
  preços absolutos. Apenas LONG e SHORT são aceitos.
- Colunas obrigatórias: open_time, close_time, open, high, low, close.
  Volume e demais colunas do coletor são aceitos, mas não usados.
- Timestamps precisam de timezone e são normalizados para UTC. Candles devem
  estar ordenados, com aberturas únicas, intervalos sem sobreposição e OHLC
  positivo, finito e consistente. Índices do pandas não têm significado temporal.
- Candles anteriores à entrada são excluídos. Entrada exatamente na abertura
  permite usar esse candle; entrada dentro de um candle é rejeitada, pois seus
  extremos podem ter ocorrido antes da entrada. Entrada no fechamento exclui-o.
- O chamador fornece somente candles fechados e verifica completude, origem e
  timeframe do histórico. symbol/timeframe são metadados, não filtros; não há
  validação de cadência ou detecção de candles ausentes nesta etapa.
- A abertura é verificada primeiro. Gap além do stop executa no open; gap além
  do target executa no target, modelado como limite sem melhoria de preço.
  Essas são hipóteses de execução, não garantias de fills reais.
- Dentro do candle, toque exato conta. Se ambas as barreiras forem tocadas:
  conservative (padrão) escolhe STOP; optimistic escolhe TARGET; unresolved
  retorna AMBIGUOUS sem preço/retorno. Todos registram ambiguous=True.
  intrabar lança NotImplementedError; nunca há fallback silencioso.
- TIMEOUT fecha no close do último candle do horizonte max_candles.
  Se os dados terminarem antes e nenhuma barreira foi tocada, retorna
  INSUFFICIENT_DATA, sem inventar saída ou retorno realizado.
- candles_held conta os candles examinados, inclusive o da saída. Uma saída
  na primeira abertura conta um candle, embora tenha duração temporal zero.
- exit_time_basis distingue open, close e bar_close_proxy. Em toques intrabar,
  exit_time é o fechamento do candle como aproximação; duration é um limite
  superior para a duração real. AMBIGUOUS usa o mesmo marcador de candle, mas
  não representa uma execução conhecida.
- price_return_pct é percentual direcional: 3.0 significa +3%, tanto em LONG
  quanto SHORT. Não é retorno sobre margem. Sem saída, o retorno é None.
- Não há mutação da entrada, rede, relógio atual ou aleatoriedade no motor.

## Fora desta etapa

Taxas, funding, slippage adicional, posição, alavancagem, margem e liquidação
não são calculados. Não há resultado líquido nem hipótese de custo zero.
Não se deve subtrair novamente um custo de gap já refletido no preço de saída.
Uma futura liquidação deverá ser processada cronologicamente na camada de
posição, separada do resultado das barreiras do ativo.

O projeto armazena janelas recentes de OHLCV; backtests extensos ainda dependem
de backfill paginado para períodos maiores que a janela importada.
O futuro BacktestEngine deverá controlar disponibilidade temporal dos contextos,
warm-up, duplicação de oportunidades e separação discovery/validation/out-of-sample.

## Verificação

`python -m pytest tests/test_trade_simulator.py -q`

Testes cobrem LONG/SHORT, toques exatos, gaps, políticas de ambiguidade, ordem
de barreiras, timeout, falta de dados, entrada, validação e determinismo.

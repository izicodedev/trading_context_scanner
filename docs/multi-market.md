# BTC e ETH em paralelo

O seletor global alterna a visualização entre BTCUSDT e ETHUSDT nas abas Scanner,
Simulador e Hyperliquid. A preferência é salva por usuário. Alterar o seletor não
interrompe a coleta, a simulação de outra moeda nem uma sessão real já iniciada.
O executor real atual continua restrito a BTC; a aba ETH mostra a pesquisa de
estratégias de ETH, sem autorizar ordens em ETH.

Com `DATABASE_URL` configurada, aplique as migrations e importe a amostra inicial:

```bash
python -m app.user_migrations migrate
python -m app.import_candles --symbol BTCUSDT --days 30
python -m app.import_candles --symbol ETHUSDT --days 30
```

O importador de 5m verifica a sequência das páginas e grava apenas candles
fechados; pode ser repetido sem duplicar registros. O processo `python -m app.main`
consulta BTC e ETH em cada ciclo e salva sinais separados e candles de 5m, 15m e
1h. Após interrupção, ele busca todos os candles fechados desde a última abertura
gravada antes de continuar. Falha em uma moeda não impede a tentativa da outra.

Para acompanhar as estratégias de ambas simultaneamente, mantenha também
`python -m app.strategy_worker` ativo e inicie a simulação em papel uma vez para
cada moeda na interface. O worker processa todas as sessões ativas, mesmo quando
outra moeda está selecionada no navegador. A coleta contínua exige o processo
scanner em execução; no VPS, atualize o código, aplique a migration e reinicie
o serviço correspondente.

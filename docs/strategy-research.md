# Hipóteses baseadas no histórico — versão 6

A versão 6 acrescenta **Rompimento com reteste** como hipótese de simulação.
Exige fechamento além do canal de 4 horas com volume, reteste confirmado no
candle seguinte e tendência EMA50/200 alinhada. A entrada ocorre na abertura
subsequente. O stop inicial cobre pelo menos 0,8% ou 1,5 ATR e a mínima/máxima
do reteste; após um fechamento favorável de 1R, ele avança para cobrir os custos
estimados e segue o preço a 2 ATR. O alvo é 3R e o prazo máximo é 12 horas.
O stop só avança depois de resolver as barreiras do candle fechado, sem usar o
fechamento para alterar retroativamente a execução desse mesmo candle.

No histórico local de 90 dias, com 25% da banca como margem e 5×, ETHUSDT teve
+4,47%, +11,54% e +8,55% nos três blocos cronológicos (21, 16 e 24 operações).
BTCUSDT teve −2,53%, +0,54% e −10,31%: a regra não deve ser aplicada a BTC com
base nessa evidência. O último bloco de ETH cai de +8,55% para +6,77% quando a
premissa de slippage sobe de 0,02% para 0,05% por ponta.

Também foi feito replay de leitura nos 5.000 candles de perpétuos ETH mais
recentes disponibilizados pela [API pública da Hyperliquid](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint): +4,18% com 11
operações em 5× e margem de 25%, ou +3,33% com maior slippage. Essa amostra
se sobrepõe ao histórico já estudado e não é uma validação independente.
Com 100% da margem a 40×, o replay dos perpétuos marcou drawdown de 78,95%; no
último bloco Binance de 30 dias, o retorno a 40× ficou negativo com maior
slippage. A alavancagem de 40× não foi escolhida para a hipótese.
Como referência, ETHUSDT spot subiu aproximadamente 65,63% nos mesmos 90 dias;
os três retornos da estratégia com 25% de margem compõem cerca de 26,49%.
Assim, lucro histórico não demonstrou vantagem sobre manter ETH comprado nesse
período de alta. Essa comparação não iguala risco, funding ou exposição.
Na simulação contínua de 90 dias a 5× e 25% da margem, apenas 1 dos 88 dias
completos atingiu +5%; o resultado não sustenta a meta diária de 5%.

Na triagem padrão dos 30 dias mais recentes, ETH teve 14 operações na descoberta
e seis no segundo período. Apesar de retornos positivos, não atingiu a exigência
de 15 operações no segundo período; por isso não entra automaticamente na
simulação. Pode ser escolhida manualmente para acompanhamento em papel. A
família continua fora da allowlist do executor real. Somente dados futuros de
simulação podem fornecer a próxima evidência independente; não há promessa de
5% ao dia.

## Pesquisa anterior (versão 5)

A versão 5 acrescenta 12 configurações em quatro famílias: reteste de tendência,
rompimento após compressão, retorno à banda e rompimento de 4 horas. São 75
configurações no catálogo. Todas usam indicadores calculados apenas até o candle
do sinal e continuam com entrada na abertura do candle seguinte. A direção
LONG/SHORT agora é respeitada também pelas estratégias predefinidas.
As quatro famílias novas ficam disponíveis apenas no simulador; a lista do
executor real usa uma allowlist explícita das seis famílias anteriores.

Em 29/09/2026, a auditoria do banco local comparou descoberta, triagem temporal
e os quatro dias recentes que haviam sido excluídos da seleção. Nenhuma das 12
novas configurações passou os critérios existentes em BTCUSDT ou ETHUSDT.
O catálogo completo de 75 configurações também não teve elegíveis em nenhuma
das duas moedas nesta janela. Portanto, a seleção automática permanece vazia;
nenhuma configuração foi declarada lucrativa por conveniência.
Por exemplo, o rompimento de 4 horas V2 em ETH teve +6,20% na descoberta e
+7,97% na triagem, mas −6,05% nos quatro dias recentes (cinco operações).
A Continuidade de tendência V16 em BTC teve −6,64%, +8,46% e −6,01% nos mesmos
períodos. Os resultados incluem a premissa atual de fee, slippage e funding,
mas usam candles spot da Binance, não fills de perpétuos da Hyperliquid.
O replay usa 25% da banca como margem a 5×; não representa o modo real de usar
100% da margem disponível. Maior exposição amplia os ganhos e as perdas.
O período recente já foi inspecionado nesta pesquisa e não pode mais ser tratado
como amostra independente para ajustes futuros. Nenhuma configuração nova deve
ser promovida ao robô real com base nesses resultados; a próxima evidência
independente é o acompanhamento em papel com dados que ainda não ocorreram.

Para repetir a auditoria de leitura no banco configurado, execute
`python -m app.strategy_audit --symbol BTCUSDT` ou substitua por `ETHUSDT`.
A coluna `holdout_more_slippage` aumenta a premissa de slippage de 0,02% para
0,05% por ponta, mantendo os demais custos.

Também foram importados 90 dias completos de BTCUSDT e ETHUSDT para o banco
local. A auditoria `python -m app.strategy_audit --symbol BTCUSDT --days 90`
(e equivalente para ETH) dividiu essa amostra em três blocos cronológicos de
aproximadamente 30 dias. Nenhuma das 75 configurações teve lucro líquido e
profit factor acima de um nos dois primeiros blocos em qualquer das moedas.
Em BTC, o rompimento de 4 horas V3 marcou −7,66%, +13,79% e −11,13% nos três
blocos; em ETH, recuperação de extremo V18 marcou −21,13%, +16,33% e −11,53%.
Esses exemplos evidenciam a instabilidade entre períodos. O terceiro bloco
inclui dias examinados na análise de 30 dias e também não é amostra inédita.

## Método anterior (versão 4)

A versão 4 compara 63 configurações de seis famílias em até 8.640 candles
(30 dias). Além das famílias anteriores, inclui continuidade de tendência,
canal direcional e recuperação de extremo. Quando há pelo menos 6.000 candles,
exclui os últimos 1.152 (quatro dias já explorados). Faz a divisão 70/30 no
restante, escolhe o melhor de cada família na descoberta e os três melhores
vencedores, também apenas na descoberta, para validação e acompanhamento.

A seção expansível “Todas as estratégias testadas” mostra todas as configurações
da pesquisa atual, incluindo negativas, parâmetros, moeda, retorno e drawdown
de descoberta. Validação aparece somente quando realizada. Resultados anteriores
permanecem arquivados no banco. O painel principal destaca lucro na validação.

Pesquisa ampliada: `strategy-research-expanded.json`. Canal direcional obteve
7,60% líquido no período de validação, 16 operações e 62,5% de acerto. Isso não
é retorno diário nem evidência de atingir a meta de 5% ao dia.

## Método anterior (versão 3)

A tela foi reduzida a uma tabela com validação histórica, sessão ao vivo,
resultado diário e posição. Regras, custos e operações ficam recolhidos.
Continua existindo um único botão para ativar/parar a simulação.

## Seleção reproduzível

Ao iniciar uma nova sessão, `strategy_research` compara 63 configurações do
catálogo nos até 8.640 candles de 5m mais recentes. Os primeiros 70% formam a
descoberta e os 30% seguintes formam a triagem temporal. A seleção automática
exige ao menos cinco operações na descoberta e 15 na triagem, lucro líquido
positivo e profit factor maior que um em ambos. Entre as elegíveis, escolhe até
três pelo maior acerto na triagem, seguido do retorno e da amostra.

Se nenhuma passar, a pesquisa fica registrada e a simulação não inicia
automaticamente para essa moeda. O usuário pode escolher manualmente uma
hipótese experimental. Os indicadores usam o passado para warm-up, mas nenhuma
posição da descoberta é transportada para a triagem. As regras escolhidas ficam
congeladas durante a sessão. Todos os candidatos e parâmetros são registrados,
junto a hash SHA-256 dos dados e resultados de ambos os períodos em
`snapshot.research`.

O catálogo inclui retomada da faixa, momentum, falha de rompimento,
continuidade de tendência, canal direcional e recuperação de extremo. Os
parâmetros completos estão centralizados em `candidates()`. Todas usam 5x e margem de 25% para não confundir
comparação de regras com diferenças de exposição. Permanecem os custos e as
limitações de execução da simulação anterior.

## Limites da evidência

A amostra atual cobre poucos dias. Menos de 15 operações na validação, ou menos
de cinco na descoberta, produz a classificação "amostra insuficiente" mesmo
que o lucro seja positivo. Com amostra maior, resultado líquido positivo e
profit factor acima de um recebem apenas "sinal inicial favorável".
Os limiares são critérios operacionais, não testes de significância estatística.

A triagem temporal participa da seleção; seu desempenho não é uma estimativa
independente de retorno futuro. O acompanhamento posterior em papel é separado.
Não se promete atingir 5% ao dia.

## Sessões anteriores

A migration 004 adiciona strategy_session_archive. Ao reativar, o registro
anterior completo é arquivado antes da substituição. As definições de estratégia
são persistidas por sessão, inclusive para o worker após reinício. Sessões
legadas continuam usando suas três regras originais até serem encerradas.

O relatório em strategy-research-latest.json é uma cópia da pesquisa da sessão
local no momento da entrega; novas sessões usam os períodos então disponíveis.

# Hipóteses baseadas no histórico — versão 4

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

Ao iniciar uma nova sessão, strategy_research compara nove configurações
predefinidas (três por família) nos primeiros 70% dos até 1.000 candles de 5m
disponíveis. Escolhe uma por família usando, nesta ordem:

1. Ter pelo menos cinco operações na descoberta.
2. Maior retorno líquido menos metade do drawdown percentual.
3. Maior quantidade de operações, em caso de empate.

Somente depois, as três escolhidas são avaliadas nos 30% finais. Os indicadores
usam o passado para warm-up, mas nenhuma posição da descoberta é transportada
para a validação. As regras escolhidas ficam congeladas durante a sessão.
Todos os candidatos e parâmetros são registrados, junto a hash SHA-256 dos
dados, períodos, resultados da descoberta e validação, em snapshot.research.

As três famílias são retomada da faixa após varredura, retomada de momentum
na direção das EMAs e falha de rompimento. Os parâmetros completos estão
centralizados em candidates(). Todas usam 5x e margem de 25% para não confundir
comparação de regras com diferenças de exposição. Permanecem os custos e as
limitações de execução da simulação anterior.

## Limites da evidência

A amostra atual cobre poucos dias. Menos de 15 operações na validação, ou menos
de cinco na descoberta, produz a classificação "amostra insuficiente" mesmo
que o lucro seja positivo. Com amostra maior, resultado líquido positivo e
profit factor acima de um recebem apenas "sinal inicial favorável".
Os limiares são critérios operacionais, não testes de significância estatística.

A validação é temporal e exploratória; partes do mesmo histórico já haviam
sido inspecionadas na versão anterior. Não equivale a um teste cego independente.
O acompanhamento futuro é separado. Não se repete a busca no trecho de validação
para forçar um resultado positivo, nem se promete atingir 5% ao dia.

## Sessões anteriores

A migration 004 adiciona strategy_session_archive. Ao reativar, o registro
anterior completo é arquivado antes da substituição. As definições de estratégia
são persistidas por sessão, inclusive para o worker após reinício. Sessões
legadas continuam usando suas três regras originais até serem encerradas.

O relatório em strategy-research-latest.json é uma cópia da pesquisa da sessão
local no momento da entrega; novas sessões usam os períodos então disponíveis.

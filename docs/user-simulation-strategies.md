# Estratégias criadas pelo usuário no simulador

A migration `010_user_simulation_strategies.sql` guarda regras próprias e a seleção
por usuário. A criação fica em `/simulator`, no botão **Criar estratégia**. O modal
aceita de um a seis gatilhos de entrada combinados com **qualquer um (OU)** ou
**todos no mesmo candle (E)**: rompimento do canal de 20 candles, cruzamento da
EMA21, reteste da EMA21, recuperação do RSI, varredura do canal e falha de
rompimento. Há filtros independentes de alinhamento das EMAs, preço versus EMA21,
faixa de RSI, volume relativo e direção do candle. Todos os filtros selecionados
são obrigatórios. Direção, limites de RSI e volume, alavancagem, stop, alvo e prazo
são parâmetros declarativos validados no servidor. Não é possível enviar código
executável. Definições criadas no formato anterior continuam válidas.

`GET /api/simulator/strategies` retorna o catálogo predefinido e as definições do
usuário. `POST /api/simulator/strategies` cria uma definição imutável.
`POST /api/simulator/selection` salva até 12 chaves; uma lista vazia restaura a seleção
automática. Na seleção automática, o início de cada sessão escolhe as três maiores
taxas de acerto na amostra de descoberta, priorizando estratégias com pelo menos
cinco operações; a validação posterior não participa da escolha. Apenas estratégias
do catálogo e do usuário autenticado são aceitas. Enquanto uma sessão automática
está em andamento, o seletor marca as três estratégias realmente em execução.

Ao iniciar uma nova sessão, as definições escolhidas são copiadas para o snapshot.
A descoberta e a validação temporal usam candles fechados do banco, e o worker
continua o replay com essas definições congeladas. Mudar a seleção durante uma
sessão só afeta a próxima. Cada estratégia tem banca virtual independente.

Os sinais usam indicadores calculados apenas com candles já fechados. A ordem
virtual entra na abertura do candle seguinte. A prévia do modal descreve a
combinação de gatilhos e filtros, mas não estima retorno nem confirma acerto.

As regras próprias pertencem somente ao simulador; a seleção da Hyperliquid
continua limitada ao catálogo predefinido. Para ativar em outra instalação,
aplique a migration, atualize API e worker e faça o build do frontend.

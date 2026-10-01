# Hyperliquid: conexão inicial

## Cadastro de API e limites (migration 007)

A seção Carteira de API e limites recebe a chave de um agente dedicado e verifica
`extraAgents` para a conta/rede salvas. Rejeita a chave da conta principal e agentes
ausentes ou expirados. O segredo é armazenado com Fernet, incluindo usuário, rede
e conta no conteúdo protegido; não é devolvido na API. HTTPS é obrigatório fora
do host local. O endpoint exige JSON e cabeçalho específico para impedir POST
cross-origin simples. Não habilitar CORS para esse cabeçalho.

Configure `HYPERLIQUID_ENCRYPTION_KEY` com uma chave Fernet aleatória no ambiente
do backend. Em desenvolvimento ela está no `.env` ignorado pelo Git. Produção
deve usar armazenamento de segredos com acesso restrito; proteja backups da chave
separadamente do banco. Perder ou substituir a chave exige recadastrar credenciais.
Trocar conta ou rede remove a credencial e os limites anteriores. A autorização
é verificada no cadastro; ainda não há executor que a revalide continuamente.

Modos salvos: `fixed` (capital e margem por entrada) e `available_balance`
(sem teto fixo, usar margem livre atual menos reserva de execução/taxas).
Ambos exigem alavancagem máxima e perda diária em USDC. Saldo dinâmico significa
recalcular antes de cada entrada, sem reutilizar margem comprometida por posições
ou ordens. Essa semântica ainda precisa ser aplicada pelo futuro executor;
nenhuma ordem é enviada ou limite aplicado ao mercado nesta etapa.

As seções abaixo descrevem a primeira etapa e o trabalho restante.

Rota local `/hyperliquid`, protegida pela sessão do aplicativo. Aplicar
`migrations/005_hyperliquid_connections.sql` antes de usar. Mainnet é a seleção
inicial; cada usuário salva somente a rede e o endereço público da conta.
Consultar um endereço não comprova propriedade. Nenhuma chave é coletada.

A API consulta `clearinghouseState` e `openOrders` em `/info` via HTTPS,
com timeout de 10 segundos por consulta e URLs fixas para mainnet/testnet.
O painel mostra patrimônio e margem de perpétuos, posições e ordens abertas.
Não agrega saldos spot nem representa um limite de capital da automação.

## Runtime dos bots e leitura de subcontas

A migration `013_hyperliquid_bot_runtime.sql` complementa bots já criados pela
migration 012: `master_address` identifica a wallet proprietária,
`account_address` é o endereço operacional da subconta e `subaccount_name` é
somente um label. O backend consulta `subAccounts` na wallet principal e exige
que o endereço operacional pertença a ela. Endereço ausente, igual à wallet
principal ou não encontrado não usa fallback: o payload informa health de erro.

A migration `014_hyperliquid_legacy_bot_import.sql` guarda a subconta vinculada
à configuração antiga. Para importar essa configuração, o endpoint autenticado
`POST /api/hyperliquid/bots/import-legacy` recebe
`{"subaccount_address":"0x..."}`. A importação copia rede, conta principal,
estratégia e limites existentes, cria o bot com status `stopped` e é idempotente.
Se capital ou limites não estavam configurados, são mantidos os defaults seguros
do cadastro; importar nunca inicia execução. Trocar a conta principal ou a rede
limpa o vínculo legado para evitar associar uma subconta à wallet errada.
Na criação sem um nome explícito, o nome persistido do bot é o nome da estratégia
selecionada. A migration `015_hyperliquid_bot_strategy_names.sql` ajusta bots
importados que ainda tinham o nome genérico `Bot BTC`. Os cards de bot podem ser
recolhidos; o cabeçalho mantém o nome, a estratégia e o mercado.
No editor do bot, `capital_reserved` é a banca inicial virtual do robô, não o
saldo real da subconta nem o valor por entrada. O sizing oferece duas opções:
`fixed` usa `risk_limits.margin_per_trade_usdc` por entrada; `available_balance`
usa toda a banca virtual atual. Em ambos os casos, o valor da entrada é limitado
pela banca atual do bot e pelo saldo livre real da subconta. A banca atual é a
banca inicial somada ao PnL realizado líquido desde a criação do bot
(`closedPnl - fees + funding`); PnL não realizado não altera a banca. Se o
histórico necessário não puder ser consultado ou estiver incompleto, a banca
atual fica indisponível em vez de usar um valor presumido. Essas configurações
ainda não são aplicadas pelo executor.

O serviço read-only do runtime consulta `clearinghouseState` e `openOrders`
usando exclusivamente `account_address`. Fills (`userFillsByTime`) e funding
(`userFunding`) incluem as leituras diárias opcionais e consultas históricas em
intervalos desde a criação do bot para calcular o PnL realizado líquido
acumulado. O histórico acumulado fica em cache por 60 segundos; o snapshot por
subconta, por 8 segundos; e a lista de subcontas da wallet, por 60 segundos.
Consultas de bots são concorrentes com limite de workers; uma falha de subconta
não interrompe as demais respostas da listagem.

Patrimônio, saque disponível, margem utilizada e exposição vêm do estado de
clearinghouse da subconta. O capital reservado é configuração independente e
nunca é apresentado como saldo. PnL não realizado vem da posição da exchange.
PnL realizado de 24h é a soma de `closedPnl` dos fills menos suas fees; funding
de 24h vem de `userFunding` e é somado ao líquido diário. O PnL acumulado do bot
repete a consulta histórica desde `created_at` em intervalos contíguos, sem
sobreposição. Se os endpoints históricos falharem, retornarem dados incompletos
ou um intervalo não puder ser paginado com segurança, os valores afetados ficam
`null`.

Posição e ordens são filtradas pelo mercado da configuração do bot, e apenas
ordens reduce-only com trigger reconhecido contam como proteção. Health combina
estado persistido do bot/run, heartbeat do worker, reconciliação de direção e
tamanho de posição, reachability/sincronização da exchange e presença de stop.
Heartbeat acima de 30 segundos é warning e acima de 120 segundos é error.
Nenhuma divergência é corrigida automaticamente.

O executor existente ainda é de conta única/BTC; iniciar um bot persistente
continua retornando conflito até o executor ser atualizado para construir a
sessão e o signer pela configuração individual da subconta. Este runtime não
envia ordens, altera leverage, cancela ordens ou transfere fundos.

## Estado da execução

Execução desativada, sem endpoint de ordens ou assinador. A sessão simulada
continua independente. A preferência registrada é Canal direcional em BTC;
capital, alavancagem e perda diária máxima ainda precisam ser definidos.

Antes da implementação e ativação do executor:

- Autorizar uma carteira de API dedicada; nunca usar a chave principal.
- Armazenar seu segredo exclusivamente no backend, segregado por usuário e rede.
- Fixar limites e regras de parada; impedir expansão de posição quando bloqueado.
- Persistir intenções de ordens e IDs antes do envio; reconciliar respostas
  ambíguas e reinícios sem reenviar entradas cegamente.
- Usar preços, precisão, mínimos, margem e posições atuais da Hyperliquid.
- Validar stop/target reduce-only, fills parciais, falhas de proteção e intervenção manual.
- Testar o fluxo de execução antes de habilitar capital real.

Documentação oficial:
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint

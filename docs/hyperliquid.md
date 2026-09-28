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

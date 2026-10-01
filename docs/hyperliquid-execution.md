# Executor de ordens por robô

## Correção de saldo unificado

O adapter consulta userAbstraction. Para unifiedAccount, usa USDC (token 0)
em spotClearinghouseState e limita a disponibilidade ao menor entre total menos
hold e tokenToAvailableAfterMaintenance. Não soma saldo spot ao patrimônio de
perpétuos. Modos padrão mantêm o cálculo anterior; portfolioMargin e respostas
incompletas bloqueiam o cálculo. Não faz transferências nem muda o modo da conta.
A reserva de execução continua sendo aplicada depois pelo dimensionamento.

Candles já avaliados mostram espera pelo próximo fechamento. Um candle ainda
não avaliado, mas fora da janela de 90 segundos, não dispara entrada atrasada;
o worker aguarda o próximo. Isso distingue espera normal de dados ausentes.

Migration 008: sessões e intenções de ordens persistentes. Worker:
`python -m app.execution_service`. API `/api/hyperliquid/execution` retorna
estado público; POST com active exige sessão e cabeçalho X-IziCrypto-Setup.
As configurações são congeladas por sessão. GET nunca ativa a execução. O
endpoint por robô `POST /api/hyperliquid/bots/{id}/start` também exige ação
autenticada explícita; a tela pede confirmação adicional antes de iniciar na
Mainnet. Criar, editar, recarregar ou abrir a tela não inicia uma sessão.

O envio é bloqueado por padrão nas duas redes por `HYPERLIQUID_ENABLE_*`. Para
ensaios operacionais, preparar uma conta e agente próprios da testnet e definir
`HYPERLIQUID_ENABLE_TESTNET=true` no serviço. A Mainnet continua bloqueada
enquanto `HYPERLIQUID_ENABLE_MAINNET` não estiver explicitamente habilitada no
ambiente; não alterar esse gate como parte de desenvolvimento ou validação.

As credenciais são cifradas por robô e vinculadas à wallet principal, rede e
usuário; as respostas da API expõem somente se há credencial cadastrada e sua
validade, nunca a chave ou o ciphertext. Agentes podem ser reutilizados em
robôs diferentes, desde que cada robô use sua própria subconta. A migration
016 copia a credencial global já cadastrada para os robôs existentes e remove
a unicidade do agente. A troca da credencial é bloqueada enquanto a sessão do
robô ainda estiver em gerenciamento.

A migration 017 só importa o run legado 7 se a configuração e a conexão atual
comprovarem uma subconta distinta da conta principal. Nesse caso, preenche
`master_address` e `wallet_address` com `hyperliquid_connections.account_address`
e associa somente `hyperliquid_runs.bot_id`; não copia credenciais. Runs sem
essa comprovação permanecem legados e não são associados a um bot.

O worker usa candles fechados nativos de BTC/5m; aguarda candle posterior à
ativação. Uma posição por conta, margem isolada e alavancagem limitada ao menor
valor entre estratégia, usuário e mercado. Não inicia com ordens ou posições
externas. O modo de saldo dinâmico usa min(patrimônio, disponível), reservando
0,4% do nocional para execução/custos; isso não garante suficiência em gaps.
Mínimo operacional de 12 USDC, quantidade arredondada para baixo.

Entrada IOC com tolerância 0,1%; saídas reduce-only IOC com tolerância 0,3%.
Stop e alvo são triggers reduce-only, calculados sobre o preenchimento real.
As proteções são enviadas após a entrada: existe um intervalo sem proteção.
Rejeição de proteção tenta saída de emergência. Timeout ou queda não autoriza
reenviar entradas: os CLOIDs persistem antes do envio. Estado ambíguo bloqueia
novas entradas, requer conferência humana e mantém a sessão reservando a conta.
Não existe recuperação automática de uma sessão halted nesta versão.

PnL diário em São Paulo usa fills realizados menos taxas e funding; histórico
truncado bloqueia entradas. O limite impede entradas posteriores, não força
liquidação imediata de posição em aberto nem limita a perda em gaps. Parar
novas entradas não cancela proteções nem encerra automaticamente a posição;
o worker continua gerindo prazo/stop/alvo. Uma ordem já em trânsito pode concluir.

Locks de sessão por run e por signer impedem workers concorrentes. Índices
únicos impedem sessões gerenciadas simultâneas para o mesmo robô; o lock por
signer serializa ordens de bots que compartilham um agente. Cada execução usa a
subconta do robô como vault e valida o agente contra a wallet principal.
Segredos permanecem criptografados nos snapshots; não registrar configuração
completa em logs. Backup da chave de criptografia deve ter acesso restrito.

Testes locais cobrem caminhos de sucesso, preenchimento parcial, timeout,
falha de proteção, prazo, exposição externa, custos diários, credenciais
isoladas por robô e preflight sem envio de ordens. Ainda pendentes ensaios de
API em testnet, incluindo reinício real do worker, revogação, respostas
ambíguas, gaps, disparo de triggers e reconciliação. Nenhuma ordem real foi
enviada no desenvolvimento.

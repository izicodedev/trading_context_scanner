# Executor de ordens — implementação inicial, envio bloqueado

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
As configurações são congeladas por sessão. GET nunca ativa a execução.

O envio é bloqueado por padrão nas duas redes. Não configuramos flags de
liberação no ambiente local. Para ensaios operacionais, preparar uma conta e
agente próprios da testnet e definir HYPERLIQUID_ENABLE_TESTNET=true no serviço.
Só após validar o ciclo completo considerar HYPERLIQUID_ENABLE_MAINNET=true.
Nunca apontar ensaios para a conta real nem migrar automaticamente credenciais.

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
únicos impedem sessões gerenciadas simultâneas para a mesma conta/usuário.
Segredos permanecem criptografados nos snapshots; não registrar configuração
completa em logs. Backup da chave de criptografia deve ter acesso restrito.

Testes locais cobrem caminhos de sucesso, preenchimento parcial, timeout,
falha de proteção, prazo, exposição externa, custos diários e bloqueio padrão.
Ainda pendentes ensaios de API em testnet, incluindo reinício real do worker,
revogação, respostas ambíguas, gaps, disparo de triggers e reconciliação.
Nenhuma ordem real foi enviada no desenvolvimento.

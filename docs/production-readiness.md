# Correções do executor e preparação da VPS

Checklist operacional para o executor de ordens reais.

## Recuperação

- Entrada ambígua permanece em reconciliação pelo CLOID. Só fills da ordem
  confirmada estabelecem a quantidade pertencente ao robô. Se houve execução,
  ele tenta zerar essa exposição via reduce-only, mantendo novas entradas paradas.
- `unknownOid` ou fills ainda inconsistentes não significam que nada executou.
  Não há reenvio de entrada. O estado fica visível e exige atenção se persistir;
  perda total de conectividade ainda exige intervenção pela corretora.
- Saída parcial é reconciliada antes de nova tentativa, usando quantidade
  restante e novo CLOID. Respostas reconhecidas ficam no journal (migration 009).
  Nova saída nunca aumenta nem inverte a posição. Não há escalada de slippage.
- Proteções remanescentes só são limpas após confirmação de posição zerada.
  Proteção possivelmente em trânsito ganha tempo para expirar antes da limpeza.
- O heartbeat usa clock_timestamp em todos os ciclos, inclusive open/halted,
  sem depender de uma nova ordem ou mudança de fase.

## Serviços preparados

1. Instalar requirements na VPS e aplicar migrations, incluindo 009.
2. Manter cópia protegida da HYPERLIQUID_ENCRYPTION_KEY existente. Nunca gerar
   outra por cima da chave usada pelos registros atuais. Não copiá-la em logs.
3. Serviço web usa Gunicorn em 127.0.0.1:5000, cookies seguros e APP_ENV=production.
   O proxy HTTPS deve sobrescrever X-Forwarded-Proto conforme o exemplo fornecido.
   TRUST_LOCAL_PROXY=true só é adequado quando a porta WSGI não é pública.
4. Instalar deploy/trading-context-executor.service para o executor, separado do
   scanner e do simulador. Os serviços fornecidos bloqueiam mainnet por padrão;
   não transportar uma sessão ativa para a VPS durante o deploy.
5. Verificar inicialização, reinício, logs, HTTPS e leitura de saldo na VPS.
   Systemd/Gunicorn/Nginx não foram executados neste ambiente Windows.
6. Validar o ciclo completo na corretora antes de operar sem supervisão.
7. Manter o relógio da VPS sincronizado. O executor compara a hora local com o
   cabeçalho `Date` da API da Hyperliquid antes de cada entrada e saída; desvio
   superior a cinco segundos bloqueia a ordem. Uma resposta explícita
   `Action already expired` encerra a tentativa sem reenvio e para novas entradas.
   Corrigir a sincronização de hora antes de iniciar outra sessão. Se o NTP
   permanecer sem resposta, verificar conectividade de saída UDP 123 com o
   provedor da VPS; um acerto manual do relógio não substitui NTP contínuo.

Desabilitar novas entradas no servidor não interrompe a recuperação de uma
posição já gerenciada. O botão Parar novas entradas também mantém essa gestão.
O deploy por si só não é autorização para habilitar uma rede ou iniciar sessão.

## Entrada incerta sem ordem na corretora

Uma sessão `submitting` com ação `pending` bloqueia outra ativação enquanto a
corretora não confirmar o destino da entrada. Se a consulta por CLOID continuar
`unknownOid`, use `python -m app.reconcile_execution ID` para conferir a sessão
sem alterá-la. Após inspecionar a conta na Hyperliquid, o operador pode executar
`python -m app.reconcile_execution ID --release`. O comando exige sessão parada,
entrada pendente há pelo menos 60 segundos, um único registro de entrada no journal,
CLOID desconhecido, ausência de posições, ordens e fills posteriores ao envio.
Após 60 segundos da tentativa, o comando de liberação repete essas consultas
em dois momentos antes de encerrar a sessão. Esse prazo não impede a zeragem
imediata de uma posição BTC observada: o controle **Zerar BTC agora** envia
somente uma ordem reduce-only, valida lado e tamanho da posição, bloqueia novas
entradas e mantém a reconciliação da saída até confirmar a exposição residual.
O comando de reconciliação não envia nem cancela ordens; só encerra o gerenciamento local dessa sessão.
Uma nova ativação continua exigindo o botão na interface e todas as validações do
executor. Se qualquer verificação falhar, a sessão permanece bloqueada.

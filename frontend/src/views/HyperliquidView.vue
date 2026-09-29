<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getHyperliquidConnection, saveHyperliquidConnection, getHyperliquidAccount, type HyperliquidAccount } from '../services/api'
import { getHyperliquidStrategy, saveHyperliquidStrategy, type HyperliquidStrategyConfiguration } from '../services/api'
import { getLiveSimulation, type LabStatus, type MarketSymbol } from '../services/api'
import { strategyName } from '../services/strategyDisplay'
import HyperliquidSetup from '../components/HyperliquidSetup.vue'
import ExecutionControls from '../components/ExecutionControls.vue'

const props = defineProps<{ symbol: MarketSymbol }>()

const address = ref('')
const savedAddress = ref('')
const network = ref<'mainnet' | 'testnet'>('mainnet')
const savedNetwork = ref('')
const busy = ref(false)
const error = ref('')
const account = ref<HyperliquidAccount | null>(null)
const spotUsdc = computed(() => account.value?.spot_balances?.find(item => item.token === 0 && item.coin === 'USDC'))
const strategyConfig = ref<HyperliquidStrategyConfiguration | null>(null)
const strategyKey = ref('')
const research = ref<LabStatus['snapshot']>(null)
const rankingError = ref('')
const pct = (value: number) => `${value.toLocaleString('pt-BR', { maximumFractionDigits: 2 })}%`
const rankedStrategies = computed(() => (strategyConfig.value?.strategies ?? []).map(strategy => {
  const validation = research.value?.research?.validation.find(item => item.strategy.key === strategy.key)
  const trial = research.value?.research?.trials?.find(item => item.strategy.key === strategy.key)
  return { strategy, qualified: Boolean(trial?.qualified),
    validation: trial?.validation_return ?? (validation && validation.closed_trades > 0 ? validation.total_return_pct : null),
    discovery: trial && trial.trades > 0 ? trial.discovery_return : null }
}).sort((a, b) => {
  return Number(b.qualified) - Number(a.qualified)
    || (b.validation ?? b.discovery ?? -Infinity) - (a.validation ?? a.discovery ?? -Infinity)
    || a.strategy.key.localeCompare(b.strategy.key)
}))
const defaultStrategy = computed(() => {
  const hasTriagedResults = research.value?.research?.trials?.some(item => item.qualified != null)
  return rankedStrategies.value.find(item => hasTriagedResults
    ? item.qualified : item.validation != null && item.validation > 0)
})
const preview = computed(() => strategyConfig.value?.strategies.find(item => item.key === strategyKey.value))
const performanceLabel = (item: typeof rankedStrategies.value[number]) => item.validation != null
  ? `${pct(item.validation)} no segundo período${item.qualified ? ' · apta na triagem' : ' · não aprovada'}`
  : item.discovery != null ? `${pct(item.discovery)} descoberta · sem triagem` : 'Sem resultado'
const strategyBusy = ref(false)
const strategyError = ref('')
const setupState = ref<{ agent_address: string | null; risk_limits: unknown } | null>(null)
const blockers = computed(() => [
  ...(!setupState.value?.agent_address ? ['Cadastrar uma carteira de API autorizada.'] : []),
  ...(!setupState.value?.risk_limits ? ['Definir e salvar os limites de operação.'] : []),
])
async function selectStrategy() {
  strategyBusy.value = true; strategyError.value = ''
  try { strategyConfig.value = await saveHyperliquidStrategy(strategyKey.value) }
  catch (reason) { strategyError.value = reason instanceof Error ? reason.message : 'Falha ao selecionar estratégia.' }
  finally { strategyBusy.value = false }
}
const money = (value: string | undefined) => value == null ? '—' : Number(value).toLocaleString('pt-BR', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
async function refresh() {
  busy.value = true; error.value = ''
  try { account.value = await getHyperliquidAccount() }
  catch (reason) { error.value = reason instanceof Error ? reason.message : 'Falha na consulta.' }
  finally { busy.value = false }
}
async function connect() {
  busy.value = true; error.value = ''; account.value = null
  try {
    const result = await saveHyperliquidConnection(network.value, address.value.trim())
    savedAddress.value = result.connection?.account_address ?? ''
    savedNetwork.value = result.connection?.network ?? ''
    await refresh()
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'Não foi possível salvar a conta.' }
  finally { busy.value = false }
}
let balanceTimer: number | undefined
onBeforeUnmount(() => window.clearInterval(balanceTimer))
onMounted(async () => {
  balanceTimer = window.setInterval(() => { if (savedAddress.value && !busy.value) void refresh() }, 30000)
  try {
    strategyConfig.value = await getHyperliquidStrategy()
    strategyKey.value = strategyConfig.value.selected?.key ?? ''
    try {
      research.value = (await getLiveSimulation(props.symbol)).snapshot
      if (!strategyConfig.value.selected) strategyKey.value = defaultStrategy.value?.strategy.key ?? ''
    } catch { rankingError.value = 'Não foi possível carregar os retornos. Selecione manualmente ou recarregue a página.' }
  } catch (reason) { strategyError.value = reason instanceof Error ? reason.message : 'Falha ao carregar estratégias.' }
  busy.value = true
  try {
    const result = await getHyperliquidConnection()
    if (result.connection) {
      address.value = savedAddress.value = result.connection.account_address
      network.value = result.connection.network
      savedNetwork.value = result.connection.network
      await refresh()
    }
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'Falha ao carregar conexão.' }
  finally { busy.value = false }
})
watch(() => props.symbol, async symbol => {
  research.value = null
  try { research.value = (await getLiveSimulation(symbol)).snapshot; rankingError.value = '' }
  catch { rankingError.value = 'Pesquisa desta moeda indisponível.' }
})
</script>

<template>
  <main class="hl-page">
    <header class="page-header">
      <div><p class="eyebrow">HYPERLIQUID / {{ props.symbol.replace('USDT', '') }}</p><h2>Trading automático</h2><p class="subtitle">Acompanhe sua conta e controle a estratégia.</p></div>
      <span class="account-badge">{{ savedAddress ? (savedNetwork === 'testnet' ? 'Teste' : 'Conta real') + ' · ' + savedAddress.slice(0, 6) + '…' + savedAddress.slice(-4) : 'Conta não conectada' }}</span>
    </header>
    <p v-if="error" class="alert" role="alert">{{ error }}</p>

    <div class="primary-grid">
      <ExecutionControls v-if="savedAddress" :network="savedNetwork" :key="`execution:${savedNetwork}:${savedAddress}`" />
      <section v-else class="empty-panel"><p class="eyebrow">ROBÔ DE TRADING</p><h3>Conecte sua conta</h3><p>Salve o endereço público para acompanhar saldo, posições e execução.</p></section>
      <section class="balance-panel" aria-label="Resumo da conta">
        <div class="balance-heading"><span class="eyebrow">SALDO OPERACIONAL</span><button v-if="savedAddress" :disabled="busy" type="button" @click="refresh">{{ busy ? 'Atualizando…' : 'Atualizar' }}</button></div>
        <div class="balance-number">{{ account?.trading_balance ? money(String(account.trading_balance.available)) : '—' }}<span>USDC</span></div>
        <p class="balance-caption">{{ account ? 'Disponível antes da reserva de execução' : savedAddress ? 'Aguardando consulta da conta' : 'Conecte a conta para consultar' }}</p>
        <div v-if="account" class="balance-stats"><div><span>Posições</span><strong>{{ account.positions.length }}</strong></div><div><span>Ordens</span><strong>{{ account.open_orders.length }}</strong></div></div>
        <p v-if="account" class="updated">Atualizado {{ new Date(account.checked_at).toLocaleString('pt-BR') }}</p>
      </section>
    </div>

    <section class="panel strategy-panel">
      <div class="section-heading"><div><p class="eyebrow">{{ props.symbol === 'BTCUSDT' ? 'PRÓXIMA SESSÃO BTC' : 'PESQUISA ETH' }}</p><h3>Estratégia</h3></div><span v-if="strategyConfig?.selected && props.symbol === 'BTCUSDT'" class="saved-label">Selecionada</span></div>
      <p v-if="props.symbol !== 'BTCUSDT'" class="note">Pesquisa histórica de {{ props.symbol }}. O executor real atual opera somente BTC; trocar a moeda exibida não muda uma sessão em andamento nem ativa ordens em ETH.</p>
      <p v-if="props.symbol !== 'BTCUSDT' && research" class="note">{{ research.research?.eligible_count === 0 ? 'Nenhuma hipótese aprovada na triagem histórica desta moeda.' : rankedStrategies.filter(item => item.qualified).slice(0, 3).map(item => `${strategyName(item.strategy)} · ${performanceLabel(item)}`).join(' | ') || 'Nenhum resultado de triagem disponível para esta moeda.' }}</p>
      <p v-if="strategyConfig?.selected && props.symbol === 'BTCUSDT'" class="selected-name">{{ strategyName(strategyConfig.selected) }}</p>
      <p v-else-if="props.symbol === 'BTCUSDT'" class="muted">Nenhuma estratégia salva.</p>
      <form v-if="props.symbol === 'BTCUSDT'" class="strategy-form" @submit.prevent="selectStrategy">
        <label>Alterar estratégia<select v-model="strategyKey" :disabled="strategyBusy || !strategyConfig"><option disabled value="">Selecione uma configuração</option><option v-for="item in rankedStrategies" :key="item.strategy.key" :value="item.strategy.key">{{ strategyName(item.strategy) }} · {{ performanceLabel(item) }}</option></select></label>
        <button type="submit" :disabled="strategyBusy || !savedAddress || !strategyConfig || !strategyKey || strategyConfig?.selected?.key === strategyKey">{{ strategyBusy ? 'Salvando…' : 'Salvar escolha' }}</button>
      </form>
      <p v-if="props.symbol === 'BTCUSDT' && !strategyConfig?.selected && defaultStrategy" class="note">Sugestão pela {{ defaultStrategy.validation != null ? 'validação' : 'descoberta' }} histórica. Selecione para salvar.</p>
      <p v-if="props.symbol === 'BTCUSDT' && preview" class="note">{{ preview.description }}</p>
      <p v-if="props.symbol === 'BTCUSDT'" class="note">A mudança vale para a próxima ativação. Uma sessão em andamento mantém sua estratégia.</p>
      <p v-if="rankingError" class="alert" role="alert">{{ rankingError }}</p><p v-if="strategyError" class="alert" role="alert">{{ strategyError }}</p>
      <div v-if="setupState && blockers.length" class="pending"><strong>Para ativar:</strong> {{ blockers.join(' ') }}</div>
    </section>

    <section v-if="account" class="panel activity-panel">
      <div class="section-heading"><div><p class="eyebrow">CONTA</p><h3>Posições e ordens</h3></div><span class="muted">Atualização a cada 30 segundos</span></div>
      <div v-if="!account.positions.length && !account.open_orders.length" class="no-activity">Nenhuma posição ou ordem aberta.</div>
      <template v-else>
        <div v-if="account.positions.length" class="activity-block"><h4>Posições <span>{{ account.positions.length }}</span></h4><div class="scroll"><table><thead><tr><th>Moeda</th><th>Quantidade</th><th>Entrada</th><th>PnL não realizado</th></tr></thead><tbody><tr v-for="position in account.positions" :key="position.coin"><td>{{ position.coin }}</td><td>{{ position.szi }}</td><td>{{ money(position.entryPx) }}</td><td :class="Number(position.unrealizedPnl) < 0 ? 'negative' : 'positive'">{{ money(position.unrealizedPnl) }} USDC</td></tr></tbody></table></div></div>
        <div v-if="account.open_orders.length" class="activity-block"><h4>Ordens abertas <span>{{ account.open_orders.length }}</span></h4><div class="scroll"><table><thead><tr><th>Moeda</th><th>Lado</th><th>Quantidade</th><th>Preço</th><th>ID</th></tr></thead><tbody><tr v-for="order in account.open_orders" :key="order.oid"><td>{{ order.coin }}</td><td>{{ order.side === 'B' ? 'Compra' : 'Venda' }}</td><td>{{ order.sz }}</td><td>{{ money(order.limitPx) }}</td><td class="muted">{{ order.oid }}</td></tr></tbody></table></div></div>
      </template>
    </section>

    <div class="settings-grid">
      <details class="settings-panel" :open="!savedAddress"><summary><span><strong>Conexão da conta</strong><small>Rede e endereço público</small></span><span class="chevron">⌄</span></summary>
        <div class="settings-content"><p class="note">Use o endereço da conta principal ou subconta.</p><form class="connection-form" @submit.prevent="connect"><label>Rede<select v-model="network" :disabled="busy"><option value="mainnet">Conta real · Mainnet</option><option value="testnet">Conta de teste · Testnet</option></select></label><label>Endereço público<input v-model="address" :disabled="busy" placeholder="0x…" required pattern="0x[0-9a-fA-F]{40}" autocomplete="off" spellcheck="false" /></label><button :disabled="busy" type="submit">{{ busy ? 'Consultando…' : 'Salvar conta' }}</button></form><p v-if="savedAddress" class="note address">{{ savedAddress }}</p></div>
      </details>
      <HyperliquidSetup v-if="savedAddress" :key="`${savedNetwork}:${savedAddress}`" @configured="setupState = $event" />
    </div>
    <details v-if="account" class="settings-panel balance-details"><summary><span><strong>Detalhes do saldo</strong><small>Spot, margem e outros ativos</small></span><span class="chevron">⌄</span></summary><div class="settings-content">
      <div class="detail-grid"><div><span>USDC spot / conta unificada</span><strong>{{ money(spotUsdc?.total ?? '0') }}</strong></div><div><span>USDC reservado em spot</span><strong>{{ money(spotUsdc?.hold ?? '0') }}</strong></div><div><span>Patrimônio em perpétuos</span><strong>{{ money(account.margin.accountValue) }}</strong></div><div><span>Margem utilizada</span><strong>{{ money(account.margin.totalMarginUsed) }}</strong></div><div><span>Saque disponível em perpétuos</span><strong>{{ money(account.withdrawable) }}</strong></div></div>
      <p class="note">Modo: {{ account.account_mode === 'unifiedAccount' ? 'Conta unificada' : account.account_mode }}. O saldo spot e o patrimônio de perpétuos não são somados.</p>
      <div v-if="account.spot_balances?.length" class="scroll"><table><thead><tr><th>Ativo spot</th><th>Total</th><th>Reservado</th></tr></thead><tbody><tr v-for="balance in account.spot_balances" :key="balance.token"><td>{{ balance.coin }}</td><td>{{ balance.total }}</td><td>{{ balance.hold }}</td></tr></tbody></table></div>
    </div></details>
  </main>
</template>

<style scoped>
.hl-page { display: grid; gap: 22px; max-width: 1180px; width: 100%; margin: 0 auto; color: #e5edf7; }.page-header,.section-heading,.balance-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }.page-header { margin: 2px 0 8px; }.eyebrow { margin: 0 0 7px; color: #8ea1b7; letter-spacing: .12em; font-size: .68rem; font-weight: 700; }.page-header h2 { margin: 0; font-size: clamp(1.5rem,3vw,2rem); font-weight: 600; letter-spacing: -.035em; }.subtitle { margin: 7px 0 0; color: #94a6ba; font-size: .83rem; }.account-badge { padding: 9px 12px; border: 1px solid #2b3d52; border-radius: 999px; color: #b3c2d2; background: #101f30; font-size: .75rem; white-space: nowrap; }
.primary-grid { display: grid; grid-template-columns: minmax(0,1.7fr) minmax(260px,1fr); gap: 18px; align-items: stretch; }.empty-panel,.balance-panel,.panel,.settings-panel { border: 1px solid #28394e; border-radius: 14px; background: #0d1929; }.empty-panel { padding: 28px; }.empty-panel h3 { margin: 24px 0 10px; }.empty-panel p:last-child { color: #94a6ba; font-size: .83rem; }.balance-panel { padding: 28px; display: flex; flex-direction: column; }.balance-heading button { padding: 3px 0; border: 0; background: transparent; color: #9fc5e9; font-size: .73rem; cursor: pointer; }.balance-number { margin: 26px 0 4px; font-size: clamp(2rem,4vw,3.1rem); font-weight: 600; letter-spacing: -.055em; font-variant-numeric: tabular-nums; line-height: 1.1; }.balance-number span { margin-left: 7px; color: #94a6ba; font-size: .88rem; letter-spacing: 0; font-weight: 400; }.balance-caption,.updated { color: #8ea1b7; font-size: .73rem; }.balance-caption { margin: 0; }.balance-stats { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid #28394e; margin-top: auto; padding-top: 18px; gap: 12px; }.balance-stats span { display: block; color: #8ea1b7; font-size: .71rem; }.balance-stats strong { display: block; margin-top: 4px; font-size: 1.2rem; font-weight: 550; }.updated { margin: 14px 0 0; }
.panel { padding: 26px 28px; }.section-heading { margin-bottom: 18px; }.section-heading h3 { margin: 0; font-size: 1.07rem; font-weight: 600; }.saved-label { padding: 6px 9px; border-radius: 5px; color: #88c9ab; background: #17342a; font-size: .68rem; }.selected-name { font-size: 1.03rem; font-weight: 550; margin: 0 0 18px; }.muted,.note { color: #92a4b8; font-size: .76rem; line-height: 1.55; }.note { margin: 10px 0 0; }.strategy-form,.connection-form { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 12px; align-items: end; margin: 0; }.connection-form { grid-template-columns: 170px minmax(0,1fr) auto; }.strategy-form label,.connection-form label { display: grid; gap: 7px; color: #aab9c9; font-size: .76rem; }input,select { width: 100%; min-width: 0; padding: 11px 12px; border: 1px solid #3c4e62; border-radius: 8px; background: #101e30; color: #e5edf7; }button { font: inherit; }.strategy-form button,.connection-form button { border: 0; border-radius: 8px; padding: 12px 16px; background: #dce8f3; color: #0a1928; font-size: .78rem; font-weight: 650; cursor: pointer; }.strategy-form button:disabled,.connection-form button:disabled { opacity: .45; cursor: not-allowed; }.pending { margin-top: 16px; padding: 12px; border: 1px solid #735e35; border-radius: 8px; color: #efc98f; background: #33281c; font-size: .76rem; }.alert { color: #f1a5a5; font-size: .8rem; }
.activity-panel { padding-bottom: 10px; }.activity-block { margin: 24px 0; }.activity-block h4 { font-size: .82rem; font-weight: 550; margin: 0 0 10px; }.activity-block h4 span { color: #8799ae; margin-left: 4px; }.no-activity { padding: 20px 0 26px; border-top: 1px solid #28394e; color: #8ea1b7; font-size: .8rem; }.scroll { overflow-x: auto; }table { width: 100%; border-collapse: collapse; font-size: .78rem; white-space: nowrap; }th { color: #8ea1b7; font-weight: 500; text-align: left; }th,td { padding: 11px 14px 11px 0; border-bottom: 1px solid #28394e; }td:last-child,th:last-child { text-align: right; padding-right: 0; }.positive { color: #73cfa6; }.negative { color: #f3a2a2; }
.settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; align-items: start; }.settings-panel { padding: 20px 24px; min-width: 0; }.settings-panel summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; list-style: none; cursor: pointer; }.settings-panel summary::-webkit-details-marker { display: none; }.settings-panel summary strong,.settings-panel summary small { display: block; }.settings-panel summary strong { font-size: .84rem; font-weight: 550; }.settings-panel summary small { margin-top: 5px; color: #8ea1b7; font-size: .72rem; }.chevron { color: #8ea1b7; font-size: 1.15rem; transition: transform .2s; }.settings-panel[open] .chevron { transform: rotate(180deg); }.settings-content { padding-top: 22px; }.address { overflow-wrap: anywhere; }.balance-details { margin-bottom: 20px; }.detail-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 22px; margin-bottom: 20px; }.detail-grid span { display: block; color: #8ea1b7; font-size: .72rem; }.detail-grid strong { display: block; font-size: 1rem; margin-top: 7px; font-weight: 550; }button:focus-visible,summary:focus-visible,input:focus-visible,select:focus-visible { outline: 2px solid #93c5fd; outline-offset: 3px; }
@media(max-width:850px) { .primary-grid,.settings-grid { grid-template-columns: 1fr; }.balance-stats { margin-top: 28px; } }
@media(max-width:650px) { .page-header { align-items: start; flex-direction: column; }.panel,.balance-panel,.empty-panel { padding: 20px; }.settings-panel { padding: 18px 20px; }.strategy-form,.connection-form { grid-template-columns: 1fr; }.detail-grid { grid-template-columns: repeat(2,1fr); } }
</style>

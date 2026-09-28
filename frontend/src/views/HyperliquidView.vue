<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getHyperliquidConnection, saveHyperliquidConnection, getHyperliquidAccount, type HyperliquidAccount } from '../services/api'
import { getHyperliquidStrategy, saveHyperliquidStrategy, type HyperliquidStrategyConfiguration } from '../services/api'
import { getLiveSimulation, type LabStatus } from '../services/api'
import { strategyName } from '../services/strategyDisplay'
import HyperliquidSetup from '../components/HyperliquidSetup.vue'
import ExecutionControls from '../components/ExecutionControls.vue'

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
  const discovery = research.value?.research?.trials?.find(item => item.strategy.key === strategy.key)
  return { strategy, validation: validation && validation.closed_trades > 0 ? validation.total_return_pct : null,
    discovery: discovery && discovery.trades > 0 ? discovery.discovery_return : null }
}).sort((a, b) => {
  const tier = (item: typeof a) => item.validation != null ? 2 : item.discovery != null ? 1 : 0
  return tier(b) - tier(a) || (b.validation ?? b.discovery ?? -Infinity) - (a.validation ?? a.discovery ?? -Infinity) || a.strategy.key.localeCompare(b.strategy.key)
}))
const defaultStrategy = computed(() => rankedStrategies.value.find(item => item.validation != null || item.discovery != null))
const preview = computed(() => strategyConfig.value?.strategies.find(item => item.key === strategyKey.value))
const performanceLabel = (item: typeof rankedStrategies.value[number]) => item.validation != null ? `${pct(item.validation)} validação` : item.discovery != null ? `${pct(item.discovery)} descoberta · sem validação` : 'Sem resultado'
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
      research.value = (await getLiveSimulation()).snapshot
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
</script>

<template>
  <main class="hl-page">
    <header><p class="hl-muted">HYPERLIQUID · PERPÉTUOS</p><h2>Conta e automação</h2><p>Conecte o endereço público para acompanhar sua conta.</p></header>
    <div class="hl-banner"><strong>Controle de execução</strong><span>A seleção de estratégia não ativa ordens. Consulte o estado do executor abaixo.</span></div>
    <section class="hl-panel">
      <h3>Estratégia para operar · BTC</h3>
      <p v-if="strategyConfig?.selected">Selecionada: <strong>{{ strategyName(strategyConfig.selected) }}</strong> · BTC</p>
      <p v-else class="hl-muted">Nenhuma estratégia salva para esta conta.</p>
      <form @submit.prevent="selectStrategy">
        <label class="hl-address">Estratégia e configuração<select v-model="strategyKey" :disabled="strategyBusy || !strategyConfig">
          <option disabled value="">Selecione uma configuração</option>
          <option v-for="item in rankedStrategies" :key="item.strategy.key" :value="item.strategy.key">{{ strategyName(item.strategy) }} · {{ performanceLabel(item) }}</option>
        </select></label>
        <button type="submit" :disabled="strategyBusy || !savedAddress || !strategyConfig || !strategyKey">{{ strategyBusy ? 'Salvando…' : 'Selecionar estratégia' }}</button>
      </form>
      <p v-if="!strategyConfig?.selected && defaultStrategy" class="hl-muted">Sugestão inicial: maior retorno na {{ defaultStrategy.validation != null ? 'validação histórica' : 'descoberta (sem validação disponível)' }} da sua pesquisa em BTC. A escolha só é salva ao selecionar.</p>
      <p class="hl-muted">Ordenação: validação por maior retorno; depois descoberta por maior retorno; por último, configurações sem resultados. Os dois períodos não são comparados entre si.</p>
      <p v-if="preview" class="hl-muted">{{ preview.description }} · {{ preview.leverage }}× · {{ preview.atr_multiple }} ATR</p>
      <p v-if="rankingError" class="hl-error" role="alert">{{ rankingError }}</p>
      <p v-if="strategyConfig?.selected" class="hl-muted">{{ strategyConfig.selected.description }} Stop mínimo {{ (strategyConfig.selected.stop_floor * 100).toFixed(2) }}% / {{ strategyConfig.selected.atr_multiple }} ATR · prazo {{ strategyConfig.selected.max_candles }} candles. Parâmetros da pesquisa; os limites reais ainda precisam ser definidos.</p>
      <p v-if="strategyError" class="hl-error" role="alert">{{ strategyError }}</p>
      <ExecutionControls v-if="savedAddress" :network="savedNetwork" :key="`execution:${savedNetwork}:${savedAddress}`" />
      <div class="hl-preparation"><template v-if="blockers.length"><strong>Pendências do cadastro</strong><ul><li v-for="blocker in blockers" :key="blocker">{{ blocker }}</li></ul></template><p>Selecionar salva sua escolha para a próxima sessão. O estado atual da operação aparece em “Execução automática”.</p></div>
    </section>
    <section class="hl-panel">
      <h3>Conexão da conta</h3>
      <p class="hl-muted">Use o endereço da conta principal ou subconta, não o endereço da carteira de API. Esta consulta não comprova propriedade nem autoriza operações.</p>
      <form @submit.prevent="connect">
        <label>Rede<select v-model="network" :disabled="busy"><option value="mainnet">Conta real · Mainnet</option><option value="testnet">Conta de teste · Testnet</option></select></label>
        <label class="hl-address">Endereço público<input v-model="address" :disabled="busy" placeholder="0x…" required pattern="0x[0-9a-fA-F]{40}" autocomplete="off" spellcheck="false" /></label>
        <button :disabled="busy" type="submit">{{ busy ? 'Consultando…' : 'Salvar e consultar' }}</button>
      </form>
      <p class="hl-muted">Não insira seed phrase ou chave privada. Nesta etapa, somente o endereço público é salvo no seu usuário.</p>
      <p v-if="savedAddress" class="hl-saved">Conta salva: {{ savedAddress }} · {{ savedNetwork === 'mainnet' ? 'Real' : 'Teste' }}</p>
      <p v-if="error" class="hl-error" role="alert">{{ error }}</p>
    </section>
    <HyperliquidSetup v-if="savedAddress" :key="`${savedNetwork}:${savedAddress}`" @configured="setupState = $event" />
    <section v-if="account" class="hl-panel">
      <div class="hl-section-title"><h3>Conta {{ account.network === 'mainnet' ? 'real' : 'de teste' }}</h3><button :disabled="busy" @click="refresh">Atualizar saldo</button></div>
      <p class="hl-muted">Consultado em {{ new Date(account.checked_at).toLocaleString('pt-BR') }} · atualização a cada 30 segundos</p>
      <div class="hl-metrics"><div><span>Saldo USDC · spot / conta unificada</span><strong>{{ money(spotUsdc?.total ?? '0') }}</strong></div><div><span>USDC reservado em spot</span><strong>{{ money(spotUsdc?.hold ?? '0') }}</strong></div><div><span>Patrimônio de perpétuos USDC</span><strong>{{ money(account.margin.accountValue) }}</strong></div></div>
      <div class="hl-metrics"><div><span>Margem utilizada em perpétuos USDC</span><strong>{{ money(account.margin.totalMarginUsed) }}</strong></div><div><span>Saque disponível · consulta perpétuos USDC</span><strong>{{ money(account.withdrawable) }}</strong></div></div>
      <p class="hl-muted">Modo da conta: {{ account.account_mode === 'unifiedAccount' ? 'Conta unificada' : account.account_mode }}. O executor usa {{ account.trading_balance?.source === 'unified_usdc' ? 'USDC da conta unificada, exibido em spot' : 'a margem de perpétuos quando suportada' }}. Os saldos não são somados.</p>
      <p v-if="account.trading_balance"><strong>Disponível antes da reserva de execução: {{ money(String(account.trading_balance.available)) }} USDC</strong></p>
      <p v-else class="hl-error">Não foi possível confirmar o saldo operacional para este modo de conta.</p>
      <details v-if="account.spot_balances?.length"><summary>Todos os saldos spot</summary><div class="hl-scroll"><table><thead><tr><th>Ativo</th><th>Total</th><th>Reservado</th></tr></thead><tbody><tr v-for="balance in account.spot_balances" :key="balance.token"><td>{{ balance.coin }}</td><td>{{ balance.total }}</td><td>{{ balance.hold }}</td></tr></tbody></table></div></details>
      <h4>Posições abertas</h4>
      <p v-if="!account.positions.length" class="hl-muted">Nenhuma posição aberta.</p>
      <div v-else class="hl-scroll"><table><thead><tr><th>Moeda</th><th>Quantidade</th><th>Entrada</th><th>PnL não realizado</th></tr></thead><tbody><tr v-for="position in account.positions" :key="position.coin"><td>{{ position.coin }}</td><td>{{ position.szi }}</td><td>{{ money(position.entryPx) }}</td><td>{{ money(position.unrealizedPnl) }}</td></tr></tbody></table></div>
      <h4>Ordens abertas</h4>
      <p v-if="!account.open_orders.length" class="hl-muted">Nenhuma ordem aberta.</p>
      <div v-else class="hl-scroll"><table><thead><tr><th>ID</th><th>Moeda</th><th>Lado</th><th>Quantidade</th><th>Preço limite</th></tr></thead><tbody><tr v-for="order in account.open_orders" :key="order.oid"><td>{{ order.oid }}</td><td>{{ order.coin }}</td><td>{{ order.side === 'B' ? 'Compra' : 'Venda' }}</td><td>{{ order.sz }}</td><td>{{ money(order.limitPx) }}</td></tr></tbody></table></div>
    </section>
    <details class="hl-panel"><summary>Preparação da automação <span>Canal direcional · BTC</span></summary><div class="hl-preparation">
      <p>Estratégia inicial: Canal direcional em BTC. A configuração usada no simulador não habilita negociações reais.</p>
      <ul><li v-for="blocker in blockers" :key="blocker">{{ blocker }}</li></ul>
      <p>Antes de habilitar, os limites serão definidos e o fluxo de execução será validado. O acompanhamento público da conta permanece independente dessa autorização.</p>
      <a href="https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets" target="_blank" rel="noopener noreferrer">Como funcionam as carteiras de API</a>
    </div></details>
  </main>
</template>

<style scoped>
.hl-page { display: grid; gap: 24px; color: #dce4ee; max-width: 1120px; margin: 0 auto; width: 100%; }h2 { margin: 8px 0; font-size: 1.6rem; }h3,h4 { margin: 0 0 16px; }h4 { margin-top: 24px; }p { line-height: 1.7; }.hl-muted,header>p { color: #94a3b8; font-size: .85rem; }.hl-banner { border-left: 3px solid #a5b4fc; background: #121f33; padding: 18px 22px; display: flex; flex-wrap: wrap; gap: 12px 24px; }.hl-banner span { color: #a9b7c9; }.hl-panel { border: 1px solid #233044; padding: 24px; border-radius: 10px; background: #0d1929; }form { display: flex; align-items: end; gap: 16px; margin: 24px 0; }label { display: grid; gap: 8px; font-size: .85rem; }.hl-address { flex: 1; }input,select { width: 100%; min-width: 0; color: #dce4ee; background: #101e30; border: 1px solid #455468; border-radius: 6px; padding: 12px; }button { background: #e4ebf4; color: #142032; padding: 12px 16px; border: 0; border-radius: 6px; cursor: pointer; white-space: nowrap; }button:disabled { opacity: .5; cursor: wait; }.hl-saved { overflow-wrap: anywhere; font-size: .8rem; }.hl-error { color: #f2b3b3; }.hl-section-title { display: flex; justify-content: space-between; align-items: center; gap: 12px; }.hl-section-title h3 { margin: 0; }.hl-metrics { display: grid; grid-template-columns: repeat(3,1fr); gap: 20px; margin: 24px 0; }.hl-metrics span { display: block; color: #94a3b8; font-size: .8rem; }.hl-metrics strong { display: block; margin-top: 8px; font-size: 1.3rem; }.hl-scroll { overflow-x: auto; }table { width: 100%; border-collapse: collapse; }th,td { text-align: left; border-bottom: 1px solid #233044; padding: 12px; font-size: .85rem; }summary { cursor: pointer; }summary span { margin-left: 16px; color: #94a3b8; font-size: .8rem; }.hl-preparation { margin-top: 22px; font-size: .85rem; line-height: 1.8; }.hl-preparation a { color: #a5b4fc; }@media(max-width:700px) { form { align-items: stretch; flex-direction: column; }.hl-metrics { grid-template-columns: 1fr; }.hl-panel { padding: 18px; } }
</style>

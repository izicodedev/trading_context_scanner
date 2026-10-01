<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { getHyperliquidConnection, saveHyperliquidConnection, getHyperliquidAccount, type HyperliquidAccount } from '../services/api'
import { getHyperliquidStrategy, type HyperliquidStrategyConfiguration } from '../services/api'
import {
  createHyperliquidBot, getHyperliquidBotMarkets, getHyperliquidBots, pauseHyperliquidBot, startHyperliquidBot, stopHyperliquidBot,
  updateHyperliquidBot, saveHyperliquidBotCredential,
  type HyperliquidBot, type HyperliquidBotCreate, type HyperliquidBotMarket, type HyperliquidBotUpdate, type LabStrategy,
} from '../services/api'
import { strategyName } from '../services/strategyDisplay'

const address = ref('')
const savedAddress = ref('')
const network = ref<'mainnet' | 'testnet'>('mainnet')
const busy = ref(false)
const error = ref('')
const connectionLoaded = ref(false)
const accountEditorOpen = ref(false)
const editorModal = ref<HTMLDialogElement | null>(null)
const account = ref<HyperliquidAccount | null>(null)
const spotUsdc = computed(() => account.value?.spot_balances?.find(item => item.token === 0 && item.coin === 'USDC'))
const strategyConfig = ref<HyperliquidStrategyConfiguration | null>(null)
const botMarkets = ref<HyperliquidBotMarket[]>([])
const botMarketsLoading = ref(false)
const botMarketsError = ref('')
const bots = ref<HyperliquidBot[]>([])
const botsLoaded = ref(false)
const botError = ref('')
const botActionBusy = ref<number | null>(null)
const botActionErrors = ref<Record<number, string>>({})
const botEditBusy = ref<number | null>(null)
const botEditErrors = ref<Record<number, string>>({})
const editingBotId = ref<number | null>(null)
const editingCredentialBotId = ref<number | null>(null)
const credentialDraft = ref('')
const credentialBusy = ref<number | null>(null)
const credentialErrors = ref<Record<number, string>>({})
const editingOperationBotId = ref<number | null>(null)
const operationDraft = ref<{
  market: string;
  initial_bankroll: string; sizing_mode: 'fixed' | 'available_balance';
  margin_per_trade: string; leverage: string; daily_loss: string;
}>()
const operationBusy = ref<number | null>(null)
const operationErrors = ref<Record<number, string>>({})
const botCreatorOpen = ref(false)
const botCreateBusy = ref(false)
const botCreateError = ref('')
const newBotDraft = ref({
  account_address: '',
  market: 'BTC',
  strategy_key: '',
  initial_bankroll: '',
  sizing_mode: 'fixed' as 'fixed' | 'available_balance',
  margin_per_trade: '',
  daily_loss: '',
  leverage: '1',
})
const botDraft = ref<{
  name: string; strategy_key: string; master_address: string;
  account_address: string;
}>()
const activeEditorBot = computed(() => {
  const botId = editingBotId.value ?? editingCredentialBotId.value ?? editingOperationBotId.value
  return bots.value.find(bot => bot.id === botId) ?? null
})
const activeBotMarketAvailable = computed(() =>
  botMarkets.value.some(market => market.symbol === activeEditorBot.value?.market),
)
const editorTitle = computed(() => {
  if (accountEditorOpen.value) return savedAddress.value ? 'Editar conta principal' : 'Configurar conta principal'
  if (editingCredentialBotId.value !== null) return 'Credencial privada da API'
  if (editingOperationBotId.value !== null) return 'Configuração de operação'
  return 'Editar robô'
})
const activeBotCount = computed(() => bots.value.filter(bot => bot.status === 'running').length)
const positionedBotCount = computed(() => bots.value.filter(bot => bot.position !== null).length)
const totalUnrealizedPnl = computed(() => {
  if (!bots.value.length || bots.value.some(bot => bot.pnl.current === null)) return null
  return bots.value.reduce((total, bot) => total + (bot.pnl.current ?? 0), 0)
})
const botHealthClass = (health: HyperliquidBot['health']) => health.status === 'healthy' ? 'healthy' : health.status === 'warning' ? 'warning' : health.status === 'error' ? 'error' : 'stopped'
const healthLabel = (health: HyperliquidBot['health']) => ({
  healthy: 'Saudável', warning: 'Atenção', error: 'Erro', stopped: 'Parado',
}[health.status])
const botStatusLabel = (status: HyperliquidBot['status']) => ({
  running: 'Ativo', paused: 'Pausado', stopped: 'Parado', error: 'Erro',
}[status] ?? status)
const botCurrentStatusLabel = (bot: HyperliquidBot) =>
  bot.status === 'running' && bot.position
    ? 'Posicionado'
    : bot.status === 'running' && bot.run.phase === 'waiting'
      ? 'Aguardando entrada'
      : botStatusLabel(bot.status)
const isStrategy = (value: Record<string, unknown>): value is Record<string, unknown> & LabStrategy =>
  typeof value.key === 'string' && typeof value.name === 'string'
  && typeof value.description === 'string' && typeof value.leverage === 'number'
  && typeof value.stop_floor === 'number' && typeof value.atr_multiple === 'number'
  && typeof value.reward_risk === 'number' && typeof value.max_candles === 'number'
const strategyForBot = (bot: HyperliquidBot): LabStrategy | undefined =>
  strategyConfig.value?.strategies.find(strategy => strategy.key === bot.strategy.key)
  ?? (isStrategy(bot.strategy.config) ? bot.strategy.config : undefined)
const strategyStop = (bot: HyperliquidBot) => {
  const value = bot.strategy.config.stop_floor ?? strategyForBot(bot)?.stop_floor
  return typeof value === 'number' && Number.isFinite(value)
    ? `${(value * 100).toLocaleString('pt-BR', { maximumFractionDigits: 2 })}%`
    : '—'
}
const strategyTarget = (bot: HyperliquidBot) => {
  const value = bot.strategy.config.reward_risk ?? strategyForBot(bot)?.reward_risk
  return typeof value === 'number' && Number.isFinite(value) ? `${displayNumber(value, 1)}R` : '—'
}
const strategyTimeframe = (bot: HyperliquidBot) => {
  const value = bot.strategy.config.timeframe ?? bot.strategy.config.interval
  if (typeof value === 'string' && value) return value
  const maxCandles = bot.strategy.config.max_candles ?? strategyForBot(bot)?.max_candles
  if (typeof maxCandles !== 'number' || !Number.isFinite(maxCandles) || maxCandles <= 0) return '—'
  const totalMinutes = maxCandles * 5
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return [
    hours ? `${hours} h` : '',
    minutes ? `${minutes} min` : '',
  ].filter(Boolean).join(' ') || '—'
}
const sizingLabel = (bot: HyperliquidBot) => {
  if (bot.sizing_mode === 'available_balance') return 'Usar a banca atual do robô'
  const amount = bot.risk_limits?.margin_per_trade_usdc
  return amount == null ? 'Valor fixo por entrada não configurado' : `${usd(Number(amount))} USDC por entrada`
}
function editBot(bot: HyperliquidBot) {
  if (editingBotId.value === bot.id) {
    closeBotEditor()
    return
  }
  closeEditor()
  editingBotId.value = bot.id
  botDraft.value = {
    name: bot.name,
    strategy_key: bot.strategy.key ?? '',
    master_address: bot.wallet ?? '',
    account_address: bot.account_address ?? bot.subaccount ?? '',
  }
  delete botEditErrors.value[bot.id]
  openEditorModal()
}
function closeBotEditor() {
  closeEditor()
}
function openEditorModal() {
  void nextTick(() => {
    if (editorModal.value && !editorModal.value.open) editorModal.value.showModal()
  })
}
function closeEditor() {
  if (accountEditorOpen.value) {
    address.value = savedAddress.value
    error.value = ''
  }
  accountEditorOpen.value = false
  editingBotId.value = null
  botDraft.value = undefined
  editingCredentialBotId.value = null
  credentialDraft.value = ''
  editingOperationBotId.value = null
  operationDraft.value = undefined
  if (editorModal.value?.open) editorModal.value.close()
}
function toggleBotCredentialEditor(bot: HyperliquidBot) {
  if (editingCredentialBotId.value === bot.id) {
    closeEditor()
    return
  }
  closeEditor()
  editingCredentialBotId.value = bot.id
  credentialDraft.value = ''
  delete credentialErrors.value[bot.id]
  openEditorModal()
}
function toggleBotOperationEditor(bot: HyperliquidBot) {
  if (editingOperationBotId.value === bot.id) {
    closeEditor()
    return
  }
  closeEditor()
  editingOperationBotId.value = bot.id
  operationDraft.value = {
    market: bot.market,
    initial_bankroll: bot.capital.initial_bankroll == null ? '' : String(bot.capital.initial_bankroll),
    sizing_mode: bot.sizing_mode ?? 'fixed',
    margin_per_trade: bot.risk_limits?.margin_per_trade_usdc == null ? '' : String(bot.risk_limits.margin_per_trade_usdc),
    leverage: bot.capital.configured_leverage == null ? '' : String(bot.capital.configured_leverage),
    daily_loss: bot.risk_limits?.daily_loss_usdc == null ? '' : String(bot.risk_limits.daily_loss_usdc),
  }
  delete operationErrors.value[bot.id]
  openEditorModal()
}
async function saveBotOperationConfig(bot: HyperliquidBot) {
  if (!operationDraft.value) return
  operationBusy.value = bot.id
  delete operationErrors.value[bot.id]
  const draft = operationDraft.value
  const changes: HyperliquidBotUpdate = {
    market: draft.market,
    capital_reserved: Number(draft.initial_bankroll),
    sizing_mode: draft.sizing_mode,
    leverage: Number(draft.leverage),
    risk_limits: {
      ...bot.risk_limits,
      sizing_mode: draft.sizing_mode,
      margin_per_trade_usdc: draft.sizing_mode === 'fixed' ? Number(draft.margin_per_trade) : 0,
      max_leverage: Number(draft.leverage),
      daily_loss_usdc: Number(draft.daily_loss),
    },
  }
  try {
    await updateHyperliquidBot(bot.id, changes)
    await refreshBots()
    closeEditor()
  } catch (reason) {
    operationErrors.value[bot.id] = reason instanceof Error ? reason.message : 'Não foi possível salvar as configurações de operação.'
  } finally {
    operationBusy.value = null
  }
}
async function saveBotCredential(bot: HyperliquidBot) {
  credentialBusy.value = bot.id
  delete credentialErrors.value[bot.id]
  try {
    await saveHyperliquidBotCredential(bot.id, credentialDraft.value)
    await refreshBots()
    closeEditor()
  } catch (reason) {
    credentialErrors.value[bot.id] = reason instanceof Error ? reason.message : 'Não foi possível salvar a chave da API.'
  } finally {
    credentialBusy.value = null
  }
}
async function createBot() {
  if (!savedAddress.value) return
  botCreateBusy.value = true
  botCreateError.value = ''
  const draft = newBotDraft.value
  const payload: HyperliquidBotCreate = {
    market: draft.market,
    master_address: savedAddress.value,
    account_address: draft.account_address.trim(),
    strategy_key: draft.strategy_key,
    capital_reserved: Number(draft.initial_bankroll),
    max_utilization_pct: 100,
    leverage: Number(draft.leverage),
    sizing_mode: draft.sizing_mode,
    risk_limits: {
      sizing_mode: draft.sizing_mode,
      margin_per_trade_usdc: draft.sizing_mode === 'fixed' ? Number(draft.margin_per_trade) : 0,
      max_leverage: Number(draft.leverage),
      daily_loss_usdc: Number(draft.daily_loss),
    },
  }
  try {
    await createHyperliquidBot(payload)
    newBotDraft.value = {
      account_address: '',
      market: 'BTC',
      strategy_key: '',
      initial_bankroll: '',
      sizing_mode: 'fixed',
      margin_per_trade: '',
      daily_loss: '',
      leverage: '1',
    }
    botCreatorOpen.value = false
    await refreshBots()
  } catch (reason) {
    botCreateError.value = reason instanceof Error ? reason.message : 'Não foi possível criar o robô.'
  } finally {
    botCreateBusy.value = false
  }
}
async function saveBot(bot: HyperliquidBot) {
  if (!botDraft.value) return
  botEditBusy.value = bot.id
  delete botEditErrors.value[bot.id]
  const draft = botDraft.value
  const changes: HyperliquidBotUpdate = {
    name: draft.name.trim(),
    master_address: draft.master_address.trim(),
    account_address: draft.account_address.trim(),
    strategy_key: draft.strategy_key || null,
  }
  try {
    await updateHyperliquidBot(bot.id, changes)
    await refreshBots()
    closeBotEditor()
  } catch (reason) {
    botEditErrors.value[bot.id] = reason instanceof Error ? reason.message : 'Não foi possível salvar a configuração.'
  } finally {
    botEditBusy.value = null
  }
}
const healthReasonLabel = (reason: string | null) => ({
  bot_stopped: 'Robô parado.',
  position_open_while_stopped: 'Há posição aberta com o robô parado.',
  orders_open_while_stopped: 'Há ordens abertas com o robô parado.',
  active_bot_without_managing_run: 'Robô ativo sem execução gerenciada.',
  worker_heartbeat_missing: 'Sem heartbeat do worker.',
  worker_heartbeat_stale: 'Worker sem atualização recente.',
  worker_heartbeat_delayed: 'Heartbeat do worker atrasado.',
  worker_error: 'O worker registrou um erro.',
  subaccount_unconfigured: 'Subconta não configurada.',
  subaccount_is_master: 'O endereço cadastrado é a wallet principal, não uma subconta.',
  subaccount_invalid: 'Endereço de subconta inválido.',
  subaccount_not_found: 'Subconta não encontrada nesta wallet.',
  master_wallet_unconfigured: 'Wallet principal não configurada.',
  exchange_timeout: 'Tempo limite consultando a Hyperliquid.',
  exchange_unavailable: 'Hyperliquid indisponível.',
  local_exchange_position_mismatch: 'Estado local divergente da posição na exchange.',
  unmanaged_exchange_position: 'A subconta tem posição sem estado local correspondente.',
  exchange_position_on_unconfigured_market: 'A subconta possui posição em outro mercado.',
  exchange_orders_on_unconfigured_market: 'A subconta possui ordens em outro mercado.',
  local_exchange_position_size_mismatch: 'Tamanho da posição diverge do estado local.',
  local_exchange_position_side_mismatch: 'Direção da posição diverge do estado local.',
  local_exchange_order_mismatch: 'Ordens de proteção divergem do journal local.',
  unmanaged_exchange_orders: 'A subconta tem ordens sem estado local correspondente.',
  position_without_stop: 'Posição aberta sem stop detectável.',
  partial_exchange_data: 'Histórico de fills/funding parcialmente indisponível.',
}[reason ?? ''] ?? reason ?? '')
const displayNumber = (value: number | null | undefined, digits = 2) => value == null
  ? '—'
  : value.toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits })
const usd = (value: number | null | undefined) => value == null
  ? '—'
  : `$${Math.abs(value).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const signedUsd = (value: number | null | undefined) => value == null
  ? '—'
  : `${value > 0 ? '+' : value < 0 ? '−' : ''}${usd(value)}`
const signedPercent = (value: number | null | undefined) => value == null
  ? '—'
  : `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`
const relativeTime = (value: string | null | undefined) => {
  if (!value) return '—'
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000))
  if (!Number.isFinite(seconds)) return '—'
  if (seconds < 60) return `há ${seconds}s`
  if (seconds < 3600) return `há ${Math.floor(seconds / 60)} min`
  return `há ${Math.floor(seconds / 3600)} h`
}
const botUpdatedAt = (bot: HyperliquidBot) =>
  bot.health.last_exchange_sync_at ?? bot.capital.synced_at ?? bot.health.last_worker_at
const shortHealthMessage = (bot: HyperliquidBot) => {
  if (bot.health.status === 'healthy' || bot.health.status === 'stopped' || !bot.health.reason) return ''
  if (bot.health.partial_data_reasons.includes('history_unavailable')) {
    return 'Histórico de PnL incompleto; banca atual indisponível.'
  }
  const message = healthReasonLabel(bot.health.reason)
  return message.length > 54 ? `${message.slice(0, 51)}…` : message
}
async function refreshBots() {
  try {
    const payload = await getHyperliquidBots()
    bots.value = payload.bots ?? []
    botError.value = ''
  } catch (reason) {
    botError.value = 'Não foi possível carregar os robôs.'
  } finally {
    botsLoaded.value = true
  }
}
async function refreshBotMarkets() {
  botMarketsLoading.value = true
  botMarketsError.value = ''
  try {
    const response = await getHyperliquidBotMarkets()
    botMarkets.value = response.markets
    if (!botMarkets.value.some(market => market.symbol === newBotDraft.value.market) && botMarkets.value[0]) {
      newBotDraft.value.market = botMarkets.value[0].symbol
    }
  } catch (reason) {
    botMarkets.value = []
    botMarketsError.value = reason instanceof Error ? reason.message : 'Não foi possível consultar os mercados.'
  } finally {
    botMarketsLoading.value = false
  }
}
async function performBotAction(bot: HyperliquidBot, action: 'start' | 'pause' | 'stop') {
  if (botActionBusy.value !== null) return
  if (action === 'start' && bot.network === 'mainnet'
    && !window.confirm(`Iniciar ${bot.name} na Mainnet pode enviar ordens reais. Confirma que deseja iniciar?`)) return
  botActionBusy.value = bot.id
  const errors = { ...botActionErrors.value }
  delete errors[bot.id]
  botActionErrors.value = errors
  try {
    if (action === 'start') await startHyperliquidBot(bot.id)
    else if (action === 'pause') await pauseHyperliquidBot(bot.id)
    else await stopHyperliquidBot(bot.id)
    await refreshBots()
  } catch (reason) {
    botActionErrors.value = {
      ...botActionErrors.value,
      [bot.id]: reason instanceof Error ? reason.message : 'Não foi possível atualizar o robô.',
    }
    await refreshBots()
  } finally {
    botActionBusy.value = null
  }
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
    closeEditor()
    await refresh()
    await refreshBotMarkets()
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'Não foi possível salvar a conta.' }
  finally { busy.value = false }
}
function toggleAccountEditor() {
  if (accountEditorOpen.value) {
    closeEditor()
    return
  }
  closeEditor()
  address.value = savedAddress.value
  error.value = ''
  accountEditorOpen.value = true
  openEditorModal()
}
let balanceTimer: number | undefined
onBeforeUnmount(() => window.clearInterval(balanceTimer))
onMounted(async () => {
  balanceTimer = window.setInterval(() => {
    if (busy.value) return
    if (savedAddress.value) void refresh()
    void refreshBots()
  }, 30000)
  try {
    strategyConfig.value = await getHyperliquidStrategy()
  } catch { strategyConfig.value = null }
  busy.value = true
  try {
    const result = await getHyperliquidConnection()
    if (result.connection) {
      address.value = savedAddress.value = result.connection.account_address
      network.value = result.connection.network
      accountEditorOpen.value = false
      await refresh()
      await refreshBotMarkets()
    } else {
      accountEditorOpen.value = true
      openEditorModal()
    }
    await refreshBots()
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'Falha ao carregar conexão.' }
  finally { busy.value = false; connectionLoaded.value = true }
  await refreshBots()
})
</script>

<template>
  <main class="hl-page">
    <header class="page-header">
      <div><p class="eyebrow">HYPERLIQUID</p><h1>Robôs de trading</h1><p class="subtitle">Acompanhe seus robôs, posições e resultados.</p></div>
      <div class="header-actions">
        <button class="secondary-button" type="button" :disabled="!savedAddress || !strategyConfig" @click="botCreatorOpen = !botCreatorOpen">
          {{ botCreatorOpen ? 'Cancelar' : 'Adicionar robô' }}
        </button>
        <button class="refresh-button" type="button" :disabled="!botsLoaded" @click="refreshBots">{{ botsLoaded ? 'Atualizar' : 'Carregando…' }}</button>
      </div>
    </header>

    <section v-if="botsLoaded && !botError && bots.length" class="overview" aria-label="Resumo dos robôs">
      <div><strong>{{ activeBotCount }}</strong><span>ativos</span></div>
      <div><strong>{{ positionedBotCount }}</strong><span>posicionados</span></div>
      <div :class="totalUnrealizedPnl == null ? 'neutral' : totalUnrealizedPnl > 0 ? 'positive' : totalUnrealizedPnl < 0 ? 'negative' : 'neutral'">
        <strong>{{ signedUsd(totalUnrealizedPnl) }}</strong><span>PnL não realizado total</span>
      </div>
    </section>

    <section class="bots-grid" aria-label="Conta principal e robôs de trading">
      <article class="account-card">
        <div class="account-card-heading">
          <div><h2>Conta principal</h2><p>Conexão compartilhada para consulta</p></div>
          <span class="network-label">{{ network === 'mainnet' ? 'Mainnet' : 'Testnet' }}</span>
        </div>
        <div class="account-address-row">
          <strong>Conta principal:</strong>
          <code>{{ savedAddress || (connectionLoaded ? 'Não configurada' : 'Carregando…') }}</code>
          <button type="button" class="account-edit-button" :disabled="busy || !connectionLoaded" @click="toggleAccountEditor">
                {{ !connectionLoaded ? 'Carregando…' : savedAddress ? 'Editar' : 'Configurar' }}
              </button>
            </div>
            <p v-if="error && !accountEditorOpen" class="alert" role="alert">{{ error }}</p>
        <details v-if="account" class="account-details">
          <summary>Saldo e atividade global</summary>
          <div v-if="account.trading_balance" class="account-summary">Saldo disponível: <strong>{{ money(String(account.trading_balance.available)) }} USDC</strong></div>
          <div class="detail-grid">
            <div><span>USDC spot</span><strong>{{ money(spotUsdc?.total) }}</strong></div>
            <div><span>Patrimônio em perpétuos</span><strong>{{ money(account.margin.accountValue) }}</strong></div>
            <div><span>Margem utilizada</span><strong>{{ money(account.margin.totalMarginUsed) }}</strong></div>
            <div><span>Saque disponível</span><strong>{{ money(account.withdrawable) }}</strong></div>
          </div>
          <p v-if="!account.positions.length && !account.open_orders.length" class="no-activity">Nenhuma posição ou ordem aberta na conta principal.</p>
          <p v-else class="note">Posições e ordens abaixo são da conta principal; não são atribuídas aos cards dos robôs.</p>
          <div v-if="account.positions.length" class="scroll">
            <table><thead><tr><th>Moeda</th><th>Quantidade</th><th>Entrada</th><th>PnL não realizado</th></tr></thead>
              <tbody><tr v-for="position in account.positions" :key="position.coin"><td>{{ position.coin }}</td><td>{{ position.szi }}</td><td>{{ money(position.entryPx) }}</td><td>{{ money(position.unrealizedPnl) }} USDC</td></tr></tbody>
            </table>
          </div>
          <div v-if="account.open_orders.length" class="scroll">
            <table><thead><tr><th>Moeda</th><th>Lado</th><th>Quantidade</th><th>Preço</th></tr></thead>
              <tbody><tr v-for="order in account.open_orders" :key="order.oid"><td>{{ order.coin }}</td><td>{{ order.side === 'B' ? 'Compra' : 'Venda' }}</td><td>{{ order.sz }}</td><td>{{ money(order.limitPx) }}</td></tr></tbody>
            </table>
          </div>
        </details>
      </article>
      <form v-if="botCreatorOpen" class="bot-create-form" @submit.prevent="createBot">
        <div class="editor-heading"><strong>Criar robô isolado</strong><span>Ele ficará parado até você selecionar Iniciar.</span></div>
        <div class="editor-columns">
          <label>Mercado<select v-model="newBotDraft.market" required :disabled="botCreateBusy || botMarketsLoading || !botMarkets.length">
            <option v-for="market in botMarkets" :key="market.symbol" :value="market.symbol">{{ market.label }}</option>
          </select></label>
          <label>Endereço da subconta<input v-model="newBotDraft.account_address" required pattern="0x[0-9a-fA-F]{40}" autocomplete="off" spellcheck="false" :disabled="botCreateBusy" placeholder="0x…" /></label>
        </div>
        <p v-if="botMarketsLoading" class="field-hint">Consultando mercados disponíveis na Hyperliquid…</p>
        <p v-else-if="botMarketsError" class="card-error" role="alert">{{ botMarketsError }}</p>
        <p v-else-if="!botMarkets.length" class="field-hint">Nenhum mercado BTC/ETH disponível para a rede configurada.</p>
        <label>Estratégia<select v-model="newBotDraft.strategy_key" required :disabled="botCreateBusy || !strategyConfig">
          <option value="" disabled>Selecione uma estratégia</option>
          <option v-for="strategy in strategyConfig?.strategies ?? []" :key="strategy.key" :value="strategy.key">{{ strategyName(strategy) }}</option>
        </select></label>
        <div class="editor-columns">
          <label>Banca inicial do robô (USDC)<input v-model="newBotDraft.initial_bankroll" type="number" min="0.01" step="0.01" required :disabled="botCreateBusy" /></label>
          <label>Alavancagem máxima<input v-model="newBotDraft.leverage" type="number" min="1" max="40" step="1" required :disabled="botCreateBusy" /></label>
        </div>
        <label>Valor de cada entrada
          <select v-model="newBotDraft.sizing_mode" :disabled="botCreateBusy">
            <option value="fixed">Valor fixo por entrada</option>
            <option value="available_balance">Usar toda a banca atual do robô</option>
          </select>
        </label>
        <label v-if="newBotDraft.sizing_mode === 'fixed'">Valor fixo por entrada (USDC)<input v-model="newBotDraft.margin_per_trade" type="number" min="0.01" step="0.01" required :disabled="botCreateBusy" /></label>
        <label>Perda diária máxima (USDC)<input v-model="newBotDraft.daily_loss" type="number" min="0.01" step="0.01" required :disabled="botCreateBusy" /></label>
        <p class="editor-note">A credencial de API pode ser cadastrada ou editada no cartão depois da criação. Nenhuma ordem será enviada ao salvar.</p>
        <p v-if="botCreateError" class="card-error" role="alert">{{ botCreateError }}</p>
        <div class="editor-actions">
          <button type="submit" :disabled="botCreateBusy || !newBotDraft.strategy_key || !botMarkets.some(market => market.symbol === newBotDraft.market)">{{ botCreateBusy ? 'Criando…' : 'Criar robô parado' }}</button>
          <button type="button" class="secondary" :disabled="botCreateBusy" @click="botCreatorOpen = false">Cancelar</button>
        </div>
      </form>
      <p v-if="!botsLoaded" class="dashboard-message" role="status">Carregando robôs…</p>
      <p v-else-if="botError" class="dashboard-message error-message" role="alert">{{ botError }}</p>
      <article v-else-if="!bots.length" class="empty-dashboard">
        <div class="empty-icon" aria-hidden="true">◇</div>
        <h2>Nenhum robô configurado</h2>
        <p>Quando você criar um robô, ele aparecerá aqui.</p>
      </article>
      <template v-else>
        <article v-for="bot in bots" :key="bot.id" class="bot-card" :class="botHealthClass(bot.health)">
          <div class="bot-header">
            <h2>{{ bot.name }}</h2>
            <div class="bot-header-status">
              <span class="market-tag">{{ bot.market || '—' }}</span>
              <span class="status-chip" :class="bot.status">{{ botCurrentStatusLabel(bot) }}</span>
            </div>
          </div>
          <div class="bot-strategy-row">
            <strong>Estratégia:</strong>
            <span>{{ bot.strategy.name ?? bot.strategy.key ?? 'Não selecionada' }}</span>
            <button type="button" class="account-edit-button" :disabled="botEditBusy !== null" @click="editBot(bot)">
              {{ editingBotId === bot.id ? 'Fechar' : 'Editar' }}
            </button>
          </div>
          <section class="bot-results" aria-label="Resultados acumulados do robô">
            <div class="bot-result-card" :class="bot.pnl.bot_total == null ? 'neutral' : bot.pnl.bot_total > 0 ? 'positive' : bot.pnl.bot_total < 0 ? 'negative' : 'neutral'">
              <span>PnL líquido</span>
              <strong>{{ signedUsd(bot.pnl.bot_total) }} <small>USDC</small></strong>
              <small>{{ bot.pnl.bot_total == null ? 'Histórico indisponível' : 'Bruto − fees + funding' }}</small>
            </div>
            <div class="bot-result-card" :class="bot.pnl.realized_total == null ? 'neutral' : bot.pnl.realized_total > 0 ? 'positive' : bot.pnl.realized_total < 0 ? 'negative' : 'neutral'">
              <span>PnL bruto</span>
              <strong>{{ signedUsd(bot.pnl.realized_total) }} <small>USDC</small></strong>
              <small>{{ bot.pnl.realized_total == null ? 'Histórico indisponível' : 'Antes dos custos' }}</small>
            </div>
            <div class="bot-result-card neutral">
              <span>Fees Hyperliquid</span>
              <strong>{{ usd(bot.pnl.fees_total) }} <small>USDC</small></strong>
              <small>{{ bot.pnl.fees_total == null ? 'Histórico indisponível' : 'Total pago' }}</small>
            </div>
          </section>
          <div class="bot-state">
            <template v-if="bot.position">
              <div class="position-heading"><span>Posição aberta</span><strong>{{ bot.position.side }} · {{ displayNumber(bot.position.size, 5) }} {{ bot.position.coin ?? bot.market }}</strong></div>
              <div class="position-prices"><span>Entrada <strong>{{ usd(bot.position.entry_price) }}</strong></span><span>Preço atual <strong>{{ usd(bot.position.mark_price) }}</strong></span><span>Stop <strong>{{ usd(bot.protection?.stop_price) }}</strong></span><span>Alvo <strong>{{ usd(bot.protection?.take_profit_price) }}</strong></span></div>
            </template>
            <div v-else class="position-heading"><span>Posição</span><strong>Sem posição aberta</strong></div>
          </div>
          <details class="bot-card-collapse">
            <summary>Ver detalhes</summary>
            <div class="bot-card-content">
          <div class="bot-credential-banner" :class="{ configured: bot.api_credential?.configured }">
            <div class="credential-banner-copy">
              <strong>{{ bot.api_credential?.configured ? 'API privada cadastrada' : 'API privada não cadastrada' }}</strong>
              <span>{{ bot.api_credential?.configured ? 'Chave protegida e não exibida' : 'Cadastre a chave autorizada para este robô' }}</span>
            </div>
            <button type="button" class="account-edit-button"
              :disabled="credentialBusy !== null || botEditBusy !== null"
              @click="toggleBotCredentialEditor(bot)">
              {{ bot.api_credential?.configured ? 'Editar chave' : 'Cadastrar chave' }}
            </button>
          </div>
          <div class="bot-operation-banner">
            <div class="operation-banner-copy">
              <strong>Configuração de operação</strong>
              <span>{{ sizingLabel(bot) }} · {{ bot.capital.configured_leverage ?? '—' }}x · Perda diária: {{ bot.risk_limits?.daily_loss_usdc == null ? '—' : `${usd(Number(bot.risk_limits.daily_loss_usdc))} USDC` }}</span>
            </div>
            <button type="button" class="account-edit-button"
              :disabled="operationBusy !== null || botEditBusy !== null || credentialBusy !== null"
              @click="toggleBotOperationEditor(bot)">
              {{ editingOperationBotId === bot.id ? 'Fechar' : 'Editar configuração' }}
            </button>
          </div>
          <div class="configuration-summary">
            <span class="section-label">Configuração</span>
            <div class="configuration-items">
              <div><span>Horizonte máximo</span><strong>{{ strategyTimeframe(bot) }}</strong></div>
              <div><span>Stop</span><strong>{{ strategyStop(bot) }}</strong></div>
              <div><span>Alvo</span><strong>{{ strategyTarget(bot) }}</strong></div>
              <div><span>Entrada</span><strong>{{ sizingLabel(bot) }}</strong></div>
              <div><span>Alavancagem</span><strong>{{ bot.capital.configured_leverage == null ? '—' : `${bot.capital.configured_leverage}x` }}</strong></div>
              <div><span>Perda diária máx.</span><strong>{{ bot.risk_limits?.daily_loss_usdc == null ? '—' : `${usd(Number(bot.risk_limits.daily_loss_usdc))} USDC` }}</strong></div>
            </div>
          </div>
          <p v-if="botActionErrors[bot.id]" class="card-error" role="alert">{{ botActionErrors[bot.id] }}</p>
          <div class="bot-metrics">
            <div><label>Banca inicial</label><strong>{{ usd(bot.capital.initial_bankroll) }} <small>USDC</small></strong></div>
            <div><label>Banca atual</label><strong>{{ usd(bot.capital.current_bankroll) }} <small>USDC</small></strong><small v-if="bot.capital.current_bankroll == null">Histórico de PnL indisponível</small></div>
            <div><label>Saldo da subconta</label><strong>{{ usd(bot.capital.balance) }} <small>USDC</small></strong></div>
            <div class="unrealized-metric" :class="bot.pnl.current == null ? 'neutral' : bot.pnl.current > 0 ? 'positive' : bot.pnl.current < 0 ? 'negative' : 'neutral'">
              <label>PnL não realizado</label>
              <strong>{{ signedUsd(bot.pnl.current) }} <small>USDC</small></strong>
              <small>{{ signedPercent(bot.pnl.percent) }}</small>
            </div>
          </div>
          <div class="health-row">
            <span class="health-indicator" :class="botHealthClass(bot.health)" aria-hidden="true"></span>
            <strong>{{ healthLabel(bot.health) }}</strong>
            <span class="updated-at">Atualizado {{ relativeTime(botUpdatedAt(bot)) }}</span>
          </div>
          <p v-if="bot.health.status === 'warning' || bot.health.status === 'error'" class="health-message">
            {{ shortHealthMessage(bot) }}
          </p>
          <details class="bot-details">
            <summary>Dados detalhados</summary>
            <div class="bot-details-content">
            <dl class="detail-grid">
              <div><dt>Wallet principal</dt><dd>{{ bot.wallet ?? '—' }}</dd></div>
              <div><dt>Subconta</dt><dd>{{ bot.subaccount_name ?? 'Sem label' }} · {{ bot.subaccount ?? 'não configurada' }}</dd></div>
              <div><dt>Execução</dt><dd>Run {{ bot.run.id ?? '—' }} · Último fill {{ relativeTime(bot.activity.last_fill_at) }} · Última ordem {{ relativeTime(bot.activity.last_order_at) }}</dd></div>
              <div><dt>Saldo e exposição</dt><dd>{{ bot.capital.source ?? 'Fonte indisponível' }} · {{ displayNumber(bot.capital.exposure) }} USDC</dd></div>
              <div><dt>Proteções</dt><dd>Stop {{ displayNumber(bot.protection?.stop_price) }} · Alvo {{ displayNumber(bot.protection?.take_profit_price) }}</dd></div>
              <div><dt>PnL realizado · 24h</dt><dd>Bruto {{ displayNumber(bot.pnl.realized_24h) }} · Líquido {{ displayNumber(bot.pnl.net_24h) }} USDC</dd></div>
              <div><dt>Custos · 24h</dt><dd>Funding {{ displayNumber(bot.pnl.funding_24h) }} · Fees {{ displayNumber(bot.pnl.fees_24h) }} USDC</dd></div>
              <div><dt>PnL acumulado</dt><dd>{{ bot.pnl.bot_total == null ? 'Indisponível' : `${displayNumber(bot.pnl.bot_total)} USDC` }} · {{ bot.orders?.count ?? '—' }} ordens abertas</dd></div>
              <div v-if="bot.strategy_state.message"><dt>Estado</dt><dd>{{ bot.strategy_state.message }}</dd></div>
              <div v-if="bot.health.last_error" class="detail-error"><dt>Último erro</dt><dd>{{ bot.health.last_error }}</dd></div>
            </dl>
            <div v-if="bot.orders?.items.length" class="scroll">
              <table><thead><tr><th>Mercado</th><th>Lado</th><th>Tamanho</th><th>Preço</th><th>Tipo</th></tr></thead>
                <tbody><tr v-for="(order, index) in bot.orders.items" :key="String(order.oid ?? index)">
                  <td>{{ order.coin }}</td><td>{{ order.side }}</td><td>{{ order.sz }}</td><td>{{ order.limitPx ?? order.triggerPx ?? '—' }}</td><td>{{ order.orderType ?? 'Limit' }}</td>
                </tr></tbody>
              </table>
            </div>
            </div>
          </details>
          <p v-if="(bot.status === 'stopped' || bot.status === 'error' || bot.status === 'paused') && !bot.can_start"
            class="execution-blocker" role="status">
            {{ bot.start_blocker ?? 'Aguardando a configuração do servidor para iniciar.' }}
          </p>
          <div class="bot-actions" :aria-busy="botActionBusy === bot.id">
            <button
              v-if="bot.status === 'stopped' || bot.status === 'error'"
              type="button"
              :disabled="!bot.can_start || botActionBusy !== null"
              :title="bot.start_blocker ?? 'Iniciar esta execução isolada'"
              @click="performBotAction(bot, 'start')"
            >{{ botActionBusy === bot.id ? 'Aguarde…' : 'Iniciar' }}</button>
            <template v-else-if="bot.status === 'running'">
              <button type="button" :disabled="botActionBusy !== null" @click="performBotAction(bot, 'pause')">
                {{ botActionBusy === bot.id ? 'Aguarde…' : 'Pausar' }}
              </button>
              <button type="button" class="secondary" :disabled="botActionBusy !== null" @click="performBotAction(bot, 'stop')">Parar</button>
            </template>
            <template v-else-if="bot.status === 'paused'">
              <button type="button" :disabled="!bot.can_start || botActionBusy !== null" :title="bot.start_blocker ?? 'Retomar esta execução isolada'" @click="performBotAction(bot, 'start')">Retomar</button>
              <button type="button" class="secondary" :disabled="botActionBusy !== null" @click="performBotAction(bot, 'stop')">Parar</button>
            </template>
          </div>
            </div>
          </details>
        </article>
      </template>
    </section>
    <dialog
      ref="editorModal"
      class="editor-modal"
      aria-labelledby="editor-dialog-title"
      @cancel.prevent="closeEditor"
      @click.self="closeEditor"
    >
      <div class="modal-content">
        <div class="modal-heading">
          <div>
            <p class="eyebrow">CONFIGURAÇÕES</p>
            <h2 id="editor-dialog-title">{{ editorTitle }}</h2>
            <p v-if="activeEditorBot" class="modal-subtitle">{{ activeEditorBot.name }}</p>
          </div>
          <button type="button" class="modal-close" aria-label="Fechar" @click="closeEditor">×</button>
        </div>
        <form v-if="accountEditorOpen" class="modal-form" @submit.prevent="connect">
          <label>Rede<select v-model="network" :disabled="busy"><option value="mainnet">Mainnet</option><option value="testnet">Testnet</option></select></label>
          <label>Endereço da conta principal<input v-model="address" :disabled="busy" placeholder="0x…" required pattern="0x[0-9a-fA-F]{40}" autocomplete="off" spellcheck="false" /></label>
          <p v-if="error" class="card-error" role="alert">{{ error }}</p>
          <div class="editor-actions">
            <button :disabled="busy" type="submit">{{ busy ? 'Salvando…' : 'Salvar conta' }}</button>
            <button type="button" class="secondary" :disabled="busy" @click="closeEditor">Cancelar</button>
          </div>
        </form>
        <form v-else-if="activeEditorBot && editingBotId === activeEditorBot.id && botDraft" class="modal-form" @submit.prevent="saveBot(activeEditorBot)">
          <label>Nome<input v-model="botDraft.name" required maxlength="60" minlength="3" :disabled="botEditBusy === activeEditorBot.id" /></label>
          <label>Estratégia<select v-model="botDraft.strategy_key" :disabled="botEditBusy === activeEditorBot.id || !strategyConfig"><option value="">Sem estratégia</option><option v-if="botDraft.strategy_key && !strategyConfig?.strategies.some(strategy => strategy.key === botDraft?.strategy_key)" :value="botDraft.strategy_key">{{ strategyForBot(activeEditorBot)?.name ?? botDraft.strategy_key }}</option><option v-for="strategy in strategyConfig?.strategies ?? []" :key="strategy.key" :value="strategy.key">{{ strategyName(strategy) }}</option></select></label>
          <label>Conta principal<input v-model="botDraft.master_address" required pattern="0x[0-9a-fA-F]{40}" :disabled="botEditBusy === activeEditorBot.id" /></label>
          <label>Subconta<input v-model="botDraft.account_address" required pattern="0x[0-9a-fA-F]{40}" :disabled="botEditBusy === activeEditorBot.id" /></label>
          <p v-if="botEditErrors[activeEditorBot.id]" class="card-error" role="alert">{{ botEditErrors[activeEditorBot.id] }}</p>
          <div class="editor-actions">
            <button type="submit" :disabled="botEditBusy === activeEditorBot.id">{{ botEditBusy === activeEditorBot.id ? 'Salvando…' : 'Salvar alterações' }}</button>
            <button type="button" class="secondary" :disabled="botEditBusy === activeEditorBot.id" @click="closeEditor">Cancelar</button>
          </div>
        </form>
        <form v-else-if="activeEditorBot && editingCredentialBotId === activeEditorBot.id" class="modal-form" @submit.prevent="saveBotCredential(activeEditorBot)">
          <label>Nova chave privada da API
            <input v-model="credentialDraft" type="password" required autocomplete="new-password"
              spellcheck="false" :disabled="credentialBusy === activeEditorBot.id"
              placeholder="Cole a chave privada autorizada para esta wallet" />
          </label>
          <small class="field-hint">A chave atual nunca é exibida. Ao salvar, a nova chave será validada e armazenada criptografada.</small>
          <p v-if="credentialErrors[activeEditorBot.id]" class="card-error" role="alert">{{ credentialErrors[activeEditorBot.id] }}</p>
          <div class="editor-actions">
            <button type="submit" :disabled="credentialBusy === activeEditorBot.id || !credentialDraft.trim()">
              {{ credentialBusy === activeEditorBot.id ? 'Validando e salvando…' : 'Salvar chave da API' }}
            </button>
            <button type="button" class="secondary" :disabled="credentialBusy === activeEditorBot.id" @click="closeEditor">Cancelar</button>
          </div>
        </form>
        <form v-else-if="activeEditorBot && editingOperationBotId === activeEditorBot.id && operationDraft" class="modal-form" @submit.prevent="saveBotOperationConfig(activeEditorBot)">
          <label>Mercado do robô
            <select v-model="operationDraft.market" required :disabled="operationBusy === activeEditorBot.id || botMarketsLoading">
              <option v-if="!activeBotMarketAvailable" :value="activeEditorBot.market">{{ activeEditorBot.market }} (atual)</option>
              <option v-for="market in botMarkets" :key="market.symbol" :value="market.symbol">{{ market.label }}</option>
            </select>
            <small v-if="botMarketsError" class="field-hint">{{ botMarketsError }}</small>
          </label>
          <label>Banca inicial do robô (USDC)
            <input v-model="operationDraft.initial_bankroll" type="number" min="0.01" step="0.01" required :disabled="operationBusy === activeEditorBot.id" />
            <small class="field-hint">Banca virtual para sizing e acompanhamento de PnL; não é transferida para a subconta.</small>
          </label>
          <label>Valor de cada entrada
            <select v-model="operationDraft.sizing_mode" :disabled="operationBusy === activeEditorBot.id">
              <option value="fixed">Valor fixo por entrada</option>
              <option value="available_balance">Usar toda a banca atual do robô</option>
            </select>
          </label>
          <label v-if="operationDraft.sizing_mode === 'fixed'">Valor fixo por entrada (USDC)
            <input v-model="operationDraft.margin_per_trade" type="number" min="0.01" step="0.01" required :disabled="operationBusy === activeEditorBot.id" />
            <small class="field-hint">Limitado pela banca atual do robô e pelo saldo livre real da subconta.</small>
          </label>
          <div class="editor-columns">
            <label>Alavancagem máxima<input v-model="operationDraft.leverage" type="number" min="1" max="40" step="1" required :disabled="operationBusy === activeEditorBot.id" /></label>
            <label>Perda diária máxima (USDC)<input v-model="operationDraft.daily_loss" type="number" min="0.01" step="0.01" required :disabled="operationBusy === activeEditorBot.id" /></label>
          </div>
          <p v-if="operationErrors[activeEditorBot.id]" class="card-error" role="alert">{{ operationErrors[activeEditorBot.id] }}</p>
          <div class="editor-actions">
            <button type="submit" :disabled="operationBusy === activeEditorBot.id">
              {{ operationBusy === activeEditorBot.id ? 'Salvando…' : 'Salvar configurações' }}
            </button>
            <button type="button" class="secondary" :disabled="operationBusy === activeEditorBot.id" @click="closeEditor">Cancelar</button>
          </div>
        </form>
      </div>
    </dialog>
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
  .bot-dashboard { display: grid; gap: 14px; }
  .bot-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 16px; }
  .bot-card { display: grid; gap: 14px; padding: 18px; border-radius: 16px; background: rgba(12,19,29,.82); border: 1px solid rgba(148,169,194,.18); }
  .bot-card.healthy { border-color: rgba(103,215,167,.45); box-shadow: inset 0 0 0 1px rgba(103,215,167,.2); }
  .bot-card.warning { border-color: rgba(255,196,92,.45); box-shadow: inset 0 0 0 1px rgba(255,196,92,.2); }
  .bot-card.error { border-color: rgba(255,139,139,.45); box-shadow: inset 0 0 0 1px rgba(255,139,139,.2); }
  .bot-card.stopped { border-color: rgba(148,169,194,.3); }
  .bot-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .bot-header strong { display: block; font-size: 1.02rem; }
  .bot-header span { color: #9db2c9; font-size: .78rem; }
  .chip { display: inline-flex; padding: 5px 8px; border-radius: 999px; font-size: .7rem; text-transform: uppercase; letter-spacing: .08em; border: 1px solid rgba(148,169,194,.22); }
  .chip.healthy { background: rgba(103,215,167,.12); color: #9ef0c3; border-color: rgba(103,215,167,.35); }
  .chip.warning { background: rgba(255,196,92,.1); color: #ffd77a; border-color: rgba(255,196,92,.35); }
  .chip.error { background: rgba(255,139,139,.12); color: #ffb0b0; border-color: rgba(255,139,139,.35); }
  .chip.stopped { background: rgba(148,169,194,.08); color: #d0d9e5; border-color: rgba(148,169,194,.25); }
  .bot-meta { display: flex; flex-wrap: wrap; gap: 6px; }
  .bot-meta span { padding: 4px 8px; border-radius: 999px; background: rgba(148,169,194,.08); font-size: .72rem; color: #d0dbe7; }
  .bot-actions { display: flex; flex-wrap: wrap; gap: 8px; }
  .bot-actions button { border: 0; border-radius: 8px; padding: 9px 13px; background: #dce8f3; color: #0a1928; font-size: .76rem; font-weight: 650; cursor: pointer; }
  .bot-actions button.secondary { border: 1px solid #536579; background: transparent; color: #d0dbe7; }
  .bot-actions button:disabled { opacity: .45; cursor: not-allowed; }
  .bot-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .bot-metrics div, .bot-state div { display: grid; gap: 4px; padding: 10px; border-radius: 10px; background: rgba(148,169,194,.04); border: 1px solid rgba(148,169,194,.12); }
  .bot-metrics label, .bot-state span { color: #8ea1b7; font-size: .7rem; text-transform: uppercase; letter-spacing: .08em; }
  .bot-pnl { display: grid; gap: 2px; padding: 10px 12px; border-radius: 10px; border: 1px solid rgba(148,169,194,.14); background: rgba(148,169,194,.04); }
  .bot-pnl span { color: #8ea1b7; font-size: .7rem; text-transform: uppercase; letter-spacing: .08em; }
  .bot-pnl strong { font-size: 1.2rem; }
  .bot-pnl small { font-size: .8rem; }
  .bot-state { display: grid; gap: 10px; }
  .bot-details { border-top: 1px solid rgba(148,169,194,.14); padding-top: 12px; color: #a7b4c3; font-size: .78rem; }
  .bot-details summary { color: #c8d5e3; cursor: pointer; font-weight: 600; }
  .bot-details p { margin: 8px 0; overflow-wrap: anywhere; }
  .hl-page { max-width: 1420px; gap: 18px; }
  .page-header h1 { margin: 0; font-size: clamp(1.55rem,3vw,2rem); font-weight: 620; letter-spacing: -.035em; }
  .refresh-button { border: 1px solid #34465b; border-radius: 8px; padding: 9px 13px; background: #101f30; color: #c7d5e4; font-size: .78rem; cursor: pointer; }
  .refresh-button:disabled { opacity: .55; cursor: wait; }
  .overview { display: flex; flex-wrap: wrap; gap: 10px; }
  .overview div { display: flex; align-items: baseline; gap: 7px; padding: 10px 14px; border: 1px solid #27384b; border-radius: 10px; background: #0d1929; }
  .overview strong { font-size: 1rem; font-weight: 650; font-variant-numeric: tabular-nums; }
  .overview span { color: #93a5b9; font-size: .75rem; }
  .dashboard-message,.empty-dashboard { border: 1px solid #28394e; border-radius: 14px; background: #0d1929; padding: 28px; color: #a9b8c8; font-size: .86rem; }
  .error-message { color: #dfa0a0; }
  .empty-dashboard { display: grid; justify-items: center; text-align: center; padding: 48px 22px; }
  .empty-dashboard h2 { margin: 12px 0 4px; font-size: 1.1rem; font-weight: 600; color: #e5edf7; }
  .empty-dashboard p { margin: 0; color: #93a5b9; font-size: .82rem; }
  .empty-icon { display: grid; place-items: center; width: 40px; height: 40px; border: 1px solid #34485e; border-radius: 50%; color: #a9c2db; font-size: 1.4rem; }
  .bots-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 15px; align-items: start; }
  .bot-card { display: grid; gap: 11px; min-width: 0; padding: 16px; border: 1px solid #28394e; border-radius: 13px; background: #0d1929; }
  .bot-card.healthy { border-color: #315846; box-shadow: none; }.bot-card.warning { border-color: #695832; box-shadow: none; }.bot-card.error { border-color: #674343; box-shadow: none; }.bot-card.stopped { border-color: #344357; }
  .bot-header { align-items: center; }
  .bot-header-status { display: flex; align-items: center; gap: 7px; flex: 0 0 auto; }
  .bot-header h2 { margin: 0; overflow-wrap: anywhere; color: #edf3fa; font-size: .98rem; font-weight: 630; }
  .bot-header p { margin: 0; color: #98aabc; font-size: .75rem; line-height: 1.35; }
  .bot-header .status-chip { flex: 0 0 auto; border: 1px solid #405065; border-radius: 999px; padding: 5px 9px; color: #c3d0dd; background: #142235; font-size: .64rem; font-weight: 650; text-transform: uppercase; letter-spacing: .05em; }
  .status-chip.running { color: #9ad4b2; border-color: #355e48; background: #12271e; }
  .status-chip.paused { color: #dec58d; border-color: #655735; background: #272215; }
  .status-chip.error { color: #e2a2a2; border-color: #694343; background: #291919; }
  .market-tag { justify-self: start; border-radius: 5px; padding: 3px 7px; color: #b7c6d5; background: #152438; font-size: .67rem; font-weight: 650; }
  .bot-metrics { gap: 8px; padding: 10px 0; border-top: 1px solid #223247; border-bottom: 1px solid #223247; }
  .bot-metrics div { gap: 4px; padding: 2px 8px 2px 0; border: 0; background: transparent; }
  .bot-metrics div + div { padding-left: 10px; border-left: 1px solid #26374b; }
  .bot-metrics label { color: #91a3b8; font-size: .66rem; text-transform: none; letter-spacing: 0; }
  .bot-metrics strong { overflow: hidden; color: #e1eaf3; font-size: .98rem; font-weight: 620; font-variant-numeric: tabular-nums; text-overflow: ellipsis; }
  .bot-state { gap: 6px; min-height: 54px; }
  .bot-state div { display: flex; justify-content: space-between; gap: 8px; padding: 0; border: 0; background: transparent; }
  .bot-state span { color: #91a3b8; font-size: .67rem; text-transform: none; letter-spacing: 0; }
  .bot-state strong { color: #d8e2ec; font-size: .74rem; font-weight: 550; text-align: right; font-variant-numeric: tabular-nums; }
  .bot-pnl { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 11px; border: 0; border-radius: 9px; background: #111f30; }
  .bot-pnl span { color: #91a3b8; font-size: .67rem; text-transform: uppercase; letter-spacing: .04em; }
  .bot-pnl > div { display: grid; justify-items: end; gap: 1px; }
  .bot-pnl strong { font-size: 1.12rem; line-height: 1.1; font-weight: 680; font-variant-numeric: tabular-nums; }
  .bot-pnl small { font-size: .72rem; opacity: .86; font-variant-numeric: tabular-nums; }
  .positive { color: #82c9a3; }.negative { color: #dfa0a0; }.neutral { color: #d0d9e4; }
  .health-row { display: flex; align-items: center; gap: 7px; min-width: 0; }
  .health-indicator { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; background: #8999aa; }
  .health-indicator.healthy { background: #79bd96; }.health-indicator.warning { background: #cfb16a; }.health-indicator.error { background: #d38484; }
  .health-row > strong { color: #cbd7e3; font-size: .74rem; font-weight: 600; }
  .updated-at { margin-left: auto; overflow: hidden; color: #879aaf; font-size: .68rem; text-overflow: ellipsis; white-space: nowrap; }
  .health-message,.card-error { margin: -7px 0 0 15px; overflow: hidden; color: #cdb77f; font-size: .69rem; text-overflow: ellipsis; white-space: nowrap; }
  .card-error { color: #dfa0a0; }
  .bot-details { padding-top: 8px; border-top: 1px solid rgba(148,169,194,.14); font-size: .73rem; }
  .bot-details .scroll { max-width: 100%; overflow-x: auto; }
  .bot-actions { justify-content: flex-end; gap: 6px; }
  .bot-actions button { padding: 7px 10px; border-radius: 7px; font-size: .69rem; }
  .legacy-settings { padding: 14px 17px; }
  .legacy-settings > summary { display: flex; justify-content: space-between; align-items: center; gap: 12px; cursor: pointer; list-style: none; }
  .legacy-settings > summary::-webkit-details-marker { display: none; }
  .legacy-settings > summary strong,.legacy-settings > summary small { display: block; }
  .legacy-settings > summary strong { color: #dce6ef; font-size: .82rem; font-weight: 580; }
  .legacy-settings > summary small { margin-top: 4px; color: #8396aa; font-size: .7rem; }
  .legacy-content { display: grid; gap: 15px; padding-top: 17px; }
  button:focus-visible,summary:focus-visible,input:focus-visible,select:focus-visible { outline: 2px solid #93c5fd; outline-offset: 3px; }
  @media(max-width:1080px) { .bots-grid { grid-template-columns: repeat(2,minmax(0,1fr)); } }
  @media(max-width:850px) { .primary-grid,.settings-grid { grid-template-columns: 1fr; } }
  @media(max-width:650px) { .hl-page { gap: 15px; }.page-header { align-items: flex-start; }.bots-grid { grid-template-columns: 1fr; }.overview { display: grid; grid-template-columns: 1fr 1fr; }.overview div:last-child { grid-column: 1 / -1; }.bot-card { padding: 15px; }.legacy-content { gap: 12px; }.panel,.balance-panel,.empty-panel { padding: 18px; }.settings-panel { padding: 16px; }.strategy-form,.connection-form { grid-template-columns: 1fr; }.detail-grid { grid-template-columns: repeat(2,1fr); } }
  .hl-page { max-width: 1420px; gap: 18px; }
  .page-header h1 { margin: 0; font-size: clamp(1.55rem,3vw,2rem); font-weight: 620; letter-spacing: -.035em; }
  .bots-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 15px; align-items: start; }
  .bot-card { grid-column: 1 / -1; gap: 10px; padding: 16px; border-radius: 13px; }
  .bot-header { align-items: flex-start; }
  .bot-header h2 { margin: 0; overflow-wrap: anywhere; color: #edf3fa; font-size: .98rem; font-weight: 630; }
  .bot-header p { margin: 4px 0 0; color: #98aabc; font-size: .75rem; }
  .bot-header .status-chip { flex: 0 0 auto; border: 1px solid #405065; border-radius: 999px; padding: 5px 9px; color: #c3d0dd; background: #142235; font-size: .64rem; font-weight: 650; text-transform: uppercase; letter-spacing: .05em; }
  .status-chip.running { color: #9ad4b2; border-color: #355e48; background: #12271e; }
  .status-chip.paused { color: #dec58d; border-color: #655735; background: #272215; }
  .status-chip.error { color: #e2a2a2; border-color: #694343; background: #291919; }
  .market-tag { justify-self: start; border-radius: 5px; padding: 3px 7px; color: #b7c6d5; background: #152438; font-size: .67rem; font-weight: 650; }
  .configuration-summary { display: grid; gap: 5px; padding: 10px 0; border-top: 1px solid #223247; border-bottom: 1px solid #223247; }
  .configuration-summary p { margin: 0; color: #c0ccda; font-size: .72rem; line-height: 1.4; }
  .section-label { color: #91a3b8; font-size: .65rem; text-transform: uppercase; letter-spacing: .08em; }
  .bot-metrics { gap: 8px; }
  .bot-metrics div { gap: 4px; padding: 2px 8px 2px 0; border: 0; background: transparent; }
  .bot-metrics div + div { padding-left: 10px; border-left: 1px solid #26374b; }
  .bot-metrics label { color: #91a3b8; font-size: .66rem; text-transform: none; letter-spacing: 0; }
  .bot-metrics strong { overflow: hidden; color: #e1eaf3; font-size: .98rem; font-weight: 620; font-variant-numeric: tabular-nums; text-overflow: ellipsis; }
  .bot-state { gap: 6px; min-height: 42px; }
  .bot-state div { display: flex; justify-content: space-between; gap: 8px; padding: 0; border: 0; background: transparent; }
  .bot-state span { color: #91a3b8; font-size: .67rem; text-transform: none; letter-spacing: 0; }
  .bot-state strong { color: #d8e2ec; font-size: .74rem; font-weight: 550; text-align: right; font-variant-numeric: tabular-nums; }
  .bot-state .position-prices { justify-content: flex-start; gap: 14px; color: #a7b7c8; font-size: .7rem; }
  .bot-pnl { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 11px; border: 0; border-radius: 9px; background: #111f30; }
  .bot-pnl span { color: #91a3b8; font-size: .67rem; text-transform: uppercase; letter-spacing: .04em; }
  .bot-pnl > div { display: grid; justify-items: end; gap: 1px; }
  .bot-pnl strong { font-size: 1.12rem; line-height: 1.1; font-weight: 680; font-variant-numeric: tabular-nums; }
  .bot-pnl small { font-size: .72rem; opacity: .86; font-variant-numeric: tabular-nums; }
  .positive { color: #82c9a3; }.negative { color: #dfa0a0; }.neutral { color: #d0d9e4; }
  .health-row { display: flex; align-items: center; gap: 7px; min-width: 0; }
  .health-indicator { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; background: #8999aa; }
  .health-indicator.healthy { background: #79bd96; }.health-indicator.warning { background: #cfb16a; }.health-indicator.error { background: #d38484; }
  .health-row > strong { color: #cbd7e3; font-size: .74rem; font-weight: 600; }
  .updated-at { margin-left: auto; overflow: hidden; color: #879aaf; font-size: .68rem; text-overflow: ellipsis; white-space: nowrap; }
  .health-message,.card-error { margin: -5px 0 0 15px; overflow: hidden; color: #cdb77f; font-size: .69rem; text-overflow: ellipsis; white-space: nowrap; }
  .card-error { color: #dfa0a0; }
  .bot-details { padding-top: 8px; border-top: 1px solid rgba(148,169,194,.14); font-size: .73rem; }
  .bot-details .scroll { max-width: 100%; overflow-x: auto; }
  .bot-actions { justify-content: flex-end; gap: 6px; }
  .bot-actions button { padding: 7px 10px; border-radius: 7px; font-size: .69rem; }
  .bot-editor { display: grid; gap: 11px; padding: 13px; border: 1px solid #34495f; border-radius: 10px; background: #0a1523; }
  .editor-heading,.editor-actions { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .editor-heading strong { color: #e1eaf3; font-size: .82rem; }
  .editor-heading .text-button { border: 0; background: transparent; color: #9fc5e9; font-size: .7rem; cursor: pointer; }
  .bot-editor label { display: grid; gap: 5px; color: #aab9c9; font-size: .69rem; }
  .bot-editor input,.bot-editor select { padding: 8px 9px; font-size: .75rem; }
  .editor-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .editor-readonly,.editor-note,.editor-warning,.field-hint { margin: 0; color: #91a3b8; font-size: .69rem; line-height: 1.5; }
  .field-hint { padding: 9px 10px; border-left: 2px solid #49627c; border-radius: 0 6px 6px 0; background: #101e2e; }
  .editor-warning { color: #d6bf83; }
  .editor-actions { justify-content: flex-start; }
  .editor-actions button { border: 0; border-radius: 7px; padding: 8px 11px; background: #dce8f3; color: #0a1928; font-size: .7rem; font-weight: 650; cursor: pointer; }
  .editor-actions button.secondary { border: 1px solid #536579; background: transparent; color: #d0dbe7; }
  .legacy-settings { padding: 14px 17px; }
  .legacy-settings > summary { display: flex; justify-content: space-between; align-items: center; gap: 12px; cursor: pointer; list-style: none; }
  .legacy-settings > summary::-webkit-details-marker { display: none; }
  .legacy-settings > summary strong,.legacy-settings > summary small { display: block; }
  .legacy-settings > summary strong { color: #dce6ef; font-size: .82rem; font-weight: 580; }
  .legacy-settings > summary small { margin-top: 4px; color: #8396aa; font-size: .7rem; }
  .legacy-content { display: grid; gap: 14px; padding-top: 14px; }
  .account-summary { color: #aab9c9; font-size: .78rem; }.account-summary strong { color: #e1eaf3; }
  .account-details { padding-top: 12px; border-top: 1px solid #28394e; color: #b5c2d0; font-size: .75rem; }
  .account-details > summary { color: #a9c9e5; cursor: pointer; }
  .account-details .detail-grid { padding-top: 14px; grid-template-columns: repeat(auto-fit,minmax(150px,1fr)); gap: 12px; }
  .connection-form { grid-template-columns: 170px minmax(0,1fr) auto; }
  .connection-form label { display: grid; gap: 6px; color: #aab9c9; font-size: .72rem; }
  .connection-form input,.connection-form select { padding: 9px 10px; }
  .connection-form button { border: 0; border-radius: 7px; padding: 9px 12px; background: #dce8f3; color: #0a1928; font-size: .72rem; font-weight: 650; cursor: pointer; }
  .connection-form button:disabled { opacity: .45; cursor: not-allowed; }
  .account-card { grid-column: 1 / -1; display: grid; align-content: start; gap: 14px; min-width: 0; padding: 17px; border: 1px solid #344b63; border-radius: 13px; background: #101e2e; }
  .header-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
  .secondary-button { padding: 8px 11px; border: 1px solid #536579; border-radius: 7px; background: transparent; color: #d0dbe7; font-size: .72rem; cursor: pointer; }
  .secondary-button:disabled { opacity: .45; cursor: not-allowed; }
  .bot-create-form { grid-column: 1 / -1; display: grid; gap: 12px; padding: 18px; border: 1px solid #344b63; border-radius: 13px; background: #101e2e; }
  .bot-create-form label { display: grid; gap: 5px; color: #aab9c9; font-size: .72rem; }
  .bot-create-form input,.bot-create-form select { padding: 9px 10px; font-size: .75rem; }
  .bot-create-form .editor-heading span { color: #91a3b8; font-size: .7rem; }
  .bot-create-form .editor-note { margin: 0; color: #91a3b8; font-size: .72rem; }
  .bot-card-collapse { min-width: 0; padding-top: 9px; border-top: 1px solid rgba(148,169,194,.14); color: #a9c9e5; font-size: .73rem; }
  .bot-card-collapse > summary { color: #a9c9e5; cursor: pointer; }
  .bot-card-content { display: grid; gap: 10px; padding-top: 14px; }
  .detail-heading { color: #c8d5e3; font-size: .72rem; font-weight: 600; }
  .bot-strategy-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
  .bot-strategy-row p { margin: 0; color: #98aabc; font-size: .75rem; }
  .bot-strategy-row p strong { color: #a9b9c9; font-weight: 550; }
  .account-card-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
  .account-card-heading h2 { margin: 0; color: #edf3fa; font-size: .98rem; font-weight: 630; }
  .account-card-heading p { margin: 4px 0 0; color: #91a3b8; font-size: .72rem; }
  .network-label { flex: 0 0 auto; padding: 4px 7px; border: 1px solid #34485e; border-radius: 5px; color: #aebfd0; font-size: .64rem; }
  .account-address-row { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; min-width: 0; }
  .account-address-row > strong { color: #a9b9c9; font-size: .71rem; font-weight: 550; }
  .account-address-row code { flex: 1 1 200px; min-width: 0; color: #e1eaf3; font-size: .68rem; overflow-wrap: anywhere; }
  .account-edit-button { flex: 0 0 auto; border: 1px solid #536579; border-radius: 7px; padding: 6px 9px; background: transparent; color: #d0dbe7; font-size: .68rem; cursor: pointer; }
  .account-edit-button:disabled { opacity: .5; cursor: wait; }
  .account-editor { display: grid; gap: 10px; padding-top: 12px; border-top: 1px solid #28394e; }
  .account-editor label { display: grid; gap: 5px; color: #aab9c9; font-size: .69rem; }
  .account-editor input,.account-editor select { padding: 8px 9px; font-size: .74rem; }
  .account-editor-actions { display: flex; gap: 7px; }
  .account-editor-actions button { border: 0; border-radius: 7px; padding: 8px 11px; background: #dce8f3; color: #0a1928; font-size: .7rem; font-weight: 650; cursor: pointer; }
  .account-editor-actions button.secondary { border: 1px solid #536579; background: transparent; color: #d0dbe7; }
  .account-editor-actions button:disabled { opacity: .5; cursor: wait; }
  .account-card .alert { margin: 0; }
  .account-details { margin-top: 1px; }
  .account-details .account-summary { padding: 10px 0 0; }
  .account-details .detail-grid { margin-top: 14px; }
  .account-card .no-activity { padding-bottom: 0; }
  .dashboard-message,.empty-dashboard { grid-column: 1 / -1; }
  .bots-grid { grid-template-columns: minmax(0,1fr); }
  .bot-card { gap: 16px; padding: 22px; }
  .bot-header { align-items: flex-start; }
  .bot-header h2 { font-size: 1.15rem; }
  .bot-strategy-row { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; width: 100%; min-width: 0; padding: 10px 12px; border: 1px solid #25384d; border-radius: 9px; background: #0a1625; }
  .bot-strategy-row > strong { flex: 0 0 auto; color: #a9b9c9; font-size: .76rem; font-weight: 550; }
  .bot-strategy-row > span { flex: 1 1 180px; min-width: 0; color: #e1eaf3; font-size: .8rem; overflow-wrap: anywhere; }
  .bot-results { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 8px; }
  .bot-result-card { display: grid; align-content: start; gap: 5px; min-width: 0; padding: 10px 11px; border: 1px solid rgba(148,169,194,.12); border-radius: 9px; background: rgba(148,169,194,.035); }
  .bot-result-card > span { color: #91a3b8; font-size: .66rem; }
  .bot-result-card > strong { color: #d0d9e4; font-size: .93rem; font-weight: 620; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
  .bot-result-card > strong small { color: #8fa2b7; font-size: .63rem; font-weight: 500; }
  .bot-result-card > small { color: #8295aa; font-size: .6rem; line-height: 1.35; }
  .bot-result-card.positive > strong { color: #82c9a3; }
  .bot-result-card.negative > strong { color: #dfa0a0; }
  .bot-header .status-chip { margin-top: 1px; }
  .bot-credential-banner { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; padding: 11px 13px; border: 1px solid #735e35; border-radius: 9px; background: #33281c; }
  .bot-credential-banner.configured { border-color: #315846; background: #10231c; }
  .credential-banner-copy { display: grid; gap: 3px; }
  .credential-banner-copy strong { color: #efc98f; font-size: .75rem; font-weight: 600; }
  .bot-credential-banner.configured .credential-banner-copy strong { color: #a9c9b6; }
  .credential-banner-copy span { color: #aab9c9; font-size: .68rem; }
  .bot-operation-banner { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; padding: 11px 13px; border: 1px solid #34495f; border-radius: 9px; background: #101e2e; }
  .operation-banner-copy { display: grid; gap: 3px; min-width: 0; }
  .operation-banner-copy strong { color: #d7e1ec; font-size: .75rem; font-weight: 600; }
  .operation-banner-copy span { color: #aab9c9; font-size: .68rem; overflow-wrap: anywhere; }
  .operation-editor { display: grid; gap: 11px; padding: 13px; border: 1px solid #34495f; border-radius: 10px; background: #0a1523; }
  .operation-editor label { display: grid; gap: 5px; color: #aab9c9; font-size: .72rem; }
  .operation-editor input,.operation-editor select { padding: 9px 10px; font-size: .75rem; }
  .bot-card-collapse { padding-top: 12px; }
  .bot-card-collapse > summary { color: #a9c9e5; cursor: pointer; }
  .market-tag { justify-self: start; padding: 5px 9px; border: 1px solid #2a3d53; border-radius: 6px; font-size: .7rem; }
  .bot-card-content { gap: 16px; padding-top: 17px; }
  .configuration-summary { gap: 12px; padding: 14px; border: 1px solid #25384d; border-radius: 10px; background: #0a1625; }
  .section-label { font-size: .68rem; }
  .configuration-items { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 14px 20px; }
  .configuration-items div { display: grid; gap: 4px; min-width: 0; }
  .configuration-items div > span { color: #91a3b8; font-size: .7rem; }
  .configuration-items strong { overflow-wrap: anywhere; color: #d7e1ec; font-size: .8rem; font-weight: 550; line-height: 1.4; }
  .bot-metrics { grid-template-columns: repeat(4,minmax(0,1fr)); gap: 12px; }
  .bot-metrics div { gap: 7px; min-width: 0; padding: 13px 15px; border: 1px solid #25384d; border-radius: 10px; background: #101e2e; }
  .bot-metrics div + div { padding-left: 15px; border-left: 1px solid #25384d; }
  .bot-metrics label { font-size: .7rem; }
  .bot-metrics strong { font-size: 1.12rem; }
  .bot-metrics strong small,.bot-pnl strong small { color: #8fa2b7; font-size: .68rem; font-weight: 500; }
  .bot-metrics div > small { color: #cdb77f; font-size: .68rem; line-height: 1.4; }
  .bot-metrics .unrealized-metric > small { color: inherit; opacity: .82; }
  .unrealized-metric.positive strong { color: #82c9a3; }
  .unrealized-metric.negative strong { color: #dfa0a0; }
  .unrealized-metric.neutral strong { color: #d0d9e4; }
  .bot-state { min-height: 0; padding: 13px 15px; border: 1px solid #25384d; border-radius: 10px; background: #0a1625; }
  .bot-state .position-heading { align-items: center; gap: 14px; }
  .bot-state .position-heading strong { text-align: left; }
  .bot-state .position-prices { flex-wrap: wrap; gap: 8px 22px; }
  .bot-state .position-prices span { display: inline-flex; gap: 5px; align-items: baseline; color: #91a3b8; }
  .bot-state .position-prices strong { color: #d8e2ec; font-weight: 550; }
  .bot-pnl { padding: 13px 15px; }
  .health-row { padding: 2px 1px; }
  .health-message { margin: -8px 0 0 16px; white-space: normal; line-height: 1.45; }
  .bot-details { padding-top: 14px; border-top: 1px solid #223247; }
  .bot-details > summary { color: #a9c9e5; cursor: pointer; }
  .bot-details-content { display: grid; gap: 12px; padding-top: 12px; }
  .bot-details .detail-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 0 18px; margin: 0; padding: 0; }
  .bot-details .detail-grid > div { min-width: 0; padding: 10px 0; border-top: 1px solid #223247; }
  .bot-details dt { margin-bottom: 5px; color: #91a3b8; font-size: .68rem; }
  .bot-details dd { margin: 0; color: #c6d2df; font-size: .73rem; line-height: 1.5; overflow-wrap: anywhere; }
  .bot-details .detail-error dd { color: #e2a2a2; }
  .bot-actions { padding-top: 2px; }
  .execution-blocker { margin: 0; color: #d9b979; font-size: .72rem; line-height: 1.45; }
  .credential-editor { display: grid; gap: 9px; padding: 12px; border: 1px solid #2a3d53; border-radius: 9px; background: #0a1625; }
  .credential-status { display: grid; gap: 4px; }
  .credential-status span { color: #91a3b8; font-size: .69rem; }
  .credential-status strong { color: #d7e1ec; font-size: .76rem; font-weight: 550; }
  .credential-edit-button { justify-self: start; }
  .credential-form { display: grid; gap: 8px; }
  .credential-form label { display: grid; gap: 5px; color: #aab9c9; font-size: .69rem; }
  .credential-form input { padding: 8px 9px; font-size: .74rem; }
  .credential-form button { justify-self: start; border: 0; border-radius: 7px; padding: 8px 11px; background: #dce8f3; color: #0a1928; font-size: .7rem; font-weight: 650; cursor: pointer; }
  .credential-form button:disabled { opacity: .5; cursor: wait; }
  .editor-modal { width: min(560px,calc(100vw - 28px)); max-height: min(88vh,760px); padding: 0; overflow: auto; border: 1px solid #3a4e64; border-radius: 16px; background: #0d1929; color: #e5edf7; box-shadow: 0 24px 80px rgba(0,0,0,.55); }
  .editor-modal::backdrop { background: rgba(3,9,16,.72); backdrop-filter: blur(4px); }
  .modal-content { display: grid; gap: 20px; padding: clamp(20px,4vw,28px); }
  .modal-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
  .modal-heading .eyebrow { margin-bottom: 6px; }
  .modal-heading h2 { margin: 0; color: #edf3fa; font-size: 1.2rem; font-weight: 620; letter-spacing: -.02em; }
  .modal-subtitle { margin: 5px 0 0; color: #91a3b8; font-size: .76rem; }
  .modal-close { flex: 0 0 auto; width: 34px; height: 34px; padding: 0; border: 1px solid #34495f; border-radius: 8px; background: #101e2e; color: #b9c8d8; font-size: 1.25rem; line-height: 1; cursor: pointer; }
  .modal-form { display: grid; gap: 13px; }
  .modal-form label { display: grid; gap: 6px; color: #aab9c9; font-size: .76rem; }
  .modal-form input,.modal-form select { padding: 11px 12px; font-size: .78rem; }
  .modal-form .editor-actions { padding-top: 3px; }
  .modal-form .editor-actions button { padding: 10px 14px; font-size: .74rem; }
  .modal-form .editor-actions button:disabled { opacity: .48; cursor: wait; }
  .modal-form .card-error { margin: 0; white-space: normal; }
  .modal-form .field-hint { margin: 0; }
  @media(max-width:520px) {
    .editor-modal { width: calc(100vw - 20px); max-height: 92vh; }
    .modal-content { gap: 16px; padding: 18px; }
    .modal-form .editor-columns { grid-template-columns: 1fr; }
    .modal-form .editor-actions { flex-wrap: wrap; }
  }
  @media(max-width:850px) { .connection-form { grid-template-columns: 1fr; } }
  @media(max-width:850px) {
    .bot-metrics { grid-template-columns: repeat(2,minmax(0,1fr)); }
  }
  @media(max-width:650px) {
    .bot-card { padding: 16px; }
    .bot-header-status { gap: 5px; }
    .bot-results { gap: 6px; }
    .bot-result-card { padding: 9px 8px; }
    .bot-result-card > strong { font-size: .82rem; }
    .configuration-items { grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }
    .bot-metrics div + div { padding-left: 15px; border-left: 1px solid #25384d; }
    .bot-details .detail-grid { grid-template-columns: 1fr; }
    .bot-state .position-heading { align-items: flex-start; flex-direction: column; gap: 5px; }
    .bot-header { gap: 12px; }
    .bot-header .status-chip { padding: 5px 7px; font-size: .58rem; }
  }
  @media(max-width:650px) { .hl-page { gap: 15px; }.page-header { align-items: flex-start; }.account-card { padding: 15px; }.editor-columns { grid-template-columns: 1fr; }.bot-actions { flex-wrap: wrap; }.legacy-content { gap: 12px; } }
</style>

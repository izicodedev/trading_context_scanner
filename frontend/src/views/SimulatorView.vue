<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { createSimulationStrategy, getLiveSimulation, getSimulationCatalog, saveSimulationSelection, setLiveSimulation, type CustomStrategyInput, type LabStatus, type LabStrategy, type MarketSymbol } from '../services/api'
import { strategyName } from '../services/strategyDisplay'

const props = defineProps<{ symbol: MarketSymbol }>()

const state = ref<LabStatus | null>(null)
const busy = ref(false)
const loading = ref(true)
const error = ref('')
const now = ref(Date.now())
const catalog = ref<LabStrategy[]>([])
const selectedKeys = ref<string[]>([])
const savedKeys = ref<string[]>([])
const automaticSelection = ref(true)
const catalogLoaded = ref(false)
const catalogError = ref('')
const catalogBusy = ref(false)
const catalogSearch = ref('')
const modal = ref<HTMLDialogElement | null>(null)
const creating = ref(false)
const createError = ref('')
const notice = ref('')
const triggerOptions = [
  { key: 'channel_breakout', title: 'Rompimento do canal', detail: 'Fecha além da máxima ou mínima dos 20 candles anteriores.' },
  { key: 'ema_cross', title: 'Cruzamento da EMA21', detail: 'O fechamento cruza a EMA21 na direção da entrada.' },
  { key: 'ema_pullback', title: 'Reteste da EMA21', detail: 'Toca a média e fecha de volta do lado da entrada.' },
  { key: 'rsi_recovery', title: 'Recuperação do RSI', detail: 'O RSI cruza o limite configurado; na venda, ele é espelhado.' },
  { key: 'liquidity_sweep', title: 'Varredura do canal', detail: 'Rompe a borda intrabar e fecha novamente dentro do canal.' },
  { key: 'failed_breakout', title: 'Rompimento falhou', detail: 'O candle anterior fechou fora do canal e o atual voltou para dentro.' },
] as const
const filterOptions = [
  { key: 'ema_alignment', title: 'Tendência das EMAs', detail: 'EMA21 acima da EMA50 na compra; abaixo na venda.' },
  { key: 'price_ema21', title: 'Preço e EMA21', detail: 'Fechamento do lado da média correspondente à direção.' },
  { key: 'rsi_band', title: 'Faixa do RSI', detail: 'Compra dentro da faixa; venda na faixa espelhada.' },
  { key: 'volume', title: 'Volume relativo', detail: 'Volume do candle acima do múltiplo da média de 20.' },
  { key: 'candle_color', title: 'Cor do candle', detail: 'Candle de alta para compra ou de baixa para venda.' },
] as const
const draft = reactive({ name: '', direction: 'BOTH', entry_triggers: ['channel_breakout'] as string[],
  trigger_mode: 'ANY' as 'ANY' | 'ALL', entry_filters: ['ema_alignment', 'volume'] as string[],
  volume_min: 1.2, rsi_lower: 40, rsi_upper: 70, leverage: 5, stop_pct: 1,
  atr_multiple: 1.5, reward_risk: 2, max_hours: 12 })
const hasTrigger = (key: string) => draft.entry_triggers.includes(key)
const hasFilter = (key: string) => draft.entry_filters.includes(key)
function toggleTrigger(key: string) {
  draft.entry_triggers = hasTrigger(key) ? draft.entry_triggers.filter(item => item !== key) : [...draft.entry_triggers, key]
}
function toggleFilter(key: string) {
  draft.entry_filters = hasFilter(key) ? draft.entry_filters.filter(item => item !== key) : [...draft.entry_filters, key]
}
const rulePreview = computed(() => {
  const triggers = triggerOptions.filter(option => hasTrigger(option.key)).map(option => option.title)
  const filters = filterOptions.filter(option => hasFilter(option.key)).map(option => option.title)
  return `${triggers.length ? triggers.join(draft.trigger_mode === 'ALL' ? ' E ' : ' OU ') : 'Selecione pelo menos um gatilho'}${filters.length ? `, desde que: ${filters.join(' + ')}` : ''}.`
})
let polling: number | undefined
let fetching = false
let revision = 0
const number = (value: number | null | undefined, digits = 2) => value == null ? '—' : value.toLocaleString('pt-BR', { maximumFractionDigits: digits, minimumFractionDigits: digits })
const percent = (value: number | null | undefined) => value == null ? '—' : `${number(value)}%`
const date = (value?: string) => value ? new Date(value).toLocaleString('pt-BR') : '—'
const historical = (key: string) => state.value?.snapshot?.historical.find(item => item.strategy.key === key)
const sessionStrategies = computed(() => state.value?.snapshot
  ? [...state.value.strategies].sort((a, b) => (historical(b.key)?.win_rate ?? -1) - (historical(a.key)?.win_rate ?? -1)) : [])
const sessionKeys = computed(() => sessionStrategies.value.map(item => item.key))
const live = (key: string) => state.value?.snapshot?.live.find(item => item.strategy.key === key)
const training = (key: string) => state.value?.snapshot?.research?.training.find(item => item.strategy.key === key)
const validation = (key: string) => state.value?.snapshot?.research?.validation.find(item => item.strategy.key === key)
const testedStrategies = computed(() => state.value?.snapshot?.research?.trials ?? [])
const selectionChanged = computed(() => JSON.stringify([...selectedKeys.value].sort()) !== JSON.stringify([...savedKeys.value].sort()))
function syncAutomaticSelection() {
  if (!catalogLoaded.value || !automaticSelection.value || selectionChanged.value || !state.value?.snapshot) return
  selectedKeys.value = [...sessionKeys.value]
  savedKeys.value = [...sessionKeys.value]
}
const visibleCatalog = computed(() => catalog.value
  .filter(item => `${item.name} ${item.description} ${item.key}`.toLocaleLowerCase('pt-BR').includes(catalogSearch.value.toLocaleLowerCase('pt-BR')))
  .sort((a, b) => Number(selectedKeys.value.includes(b.key)) - Number(selectedKeys.value.includes(a.key))
    || Number(Boolean(trial(b.key)?.qualified)) - Number(Boolean(trial(a.key)?.qualified))
    || (trial(b.key)?.validation_win_rate ?? validation(b.key)?.win_rate ?? -1) - (trial(a.key)?.validation_win_rate ?? validation(a.key)?.win_rate ?? -1)
    || Number(Boolean(b.entry_rule)) - Number(Boolean(a.entry_rule))
    || (trial(b.key)?.validation_return ?? validation(b.key)?.total_return_pct ?? trialReturn(b.key) ?? -Infinity)
      - (trial(a.key)?.validation_return ?? validation(a.key)?.total_return_pct ?? trialReturn(a.key) ?? -Infinity)
    || a.name.localeCompare(b.name, 'pt-BR')))
const trial = (key: string) => testedStrategies.value.find(item => item.strategy.key === key)
const trialReturn = (key: string) => testedStrategies.value.find(item => item.strategy.key === key)?.discovery_return
function toggleKey(key: string) {
  catalogError.value = ''
  if (selectedKeys.value.includes(key)) selectedKeys.value = selectedKeys.value.filter(item => item !== key)
  else if (selectedKeys.value.length < 12) selectedKeys.value = [...selectedKeys.value, key]
  else catalogError.value = 'Selecione no máximo 12 estratégias por sessão.'
}
async function loadCatalog() {
  const symbol = props.symbol
  try {
    const data = await getSimulationCatalog(symbol)
    if (symbol !== props.symbol) return
    catalog.value = data.strategies
    selectedKeys.value = [...data.selected_keys]
    savedKeys.value = [...data.selected_keys]
    automaticSelection.value = !data.selected_keys.length
    catalogLoaded.value = true
    syncAutomaticSelection()
    catalogError.value = ''
  } catch (reason) { catalogError.value = reason instanceof Error ? reason.message : 'Não foi possível carregar as estratégias.' }
}
async function saveSelection() {
  if (catalogBusy.value) return false
  catalogBusy.value = true; catalogError.value = ''
  try {
    const data = await saveSimulationSelection(selectedKeys.value, props.symbol)
    automaticSelection.value = !data.selected_keys.length
    selectedKeys.value = [...data.selected_keys]
    savedKeys.value = [...data.selected_keys]
    syncAutomaticSelection()
    notice.value = automaticSelection.value ? 'Seleção automática restaurada para a próxima sessão.' : 'Seleção salva para a próxima sessão.'
    return true
  } catch (reason) { catalogError.value = reason instanceof Error ? reason.message : 'Não foi possível salvar a seleção.'; return false }
  finally { catalogBusy.value = false }
}
function openCreate() {
  createError.value = ''
  modal.value?.showModal()
}
function closeCreate() { modal.value?.close() }
async function createStrategy() {
  if (creating.value) return
  if (!draft.entry_triggers.length) { createError.value = 'Selecione pelo menos um gatilho de entrada.'; return }
  creating.value = true; createError.value = ''
  try {
    const payload: CustomStrategyInput = {
      name: draft.name, entry_rule: 'rule_builder', entry_triggers: [...draft.entry_triggers],
      trigger_mode: draft.trigger_mode, entry_filters: [...draft.entry_filters],
      direction: draft.direction as CustomStrategyInput['direction'],
      volume_min: draft.volume_min, rsi_lower: draft.rsi_lower, rsi_upper: draft.rsi_upper,
      leverage: draft.leverage, stop_pct: draft.stop_pct, atr_multiple: draft.atr_multiple,
      reward_risk: draft.reward_risk, max_candles: draft.max_hours * 12,
    }
    const created = await createSimulationStrategy(payload)
    catalog.value = [created, ...catalog.value]
    if (selectedKeys.value.length < 12) {
      selectedKeys.value = [...selectedKeys.value, created.key]
      if (!await saveSelection()) notice.value = 'Estratégia criada. Salve a seleção para incluí-la na próxima sessão.'
    } else notice.value = 'Estratégia criada. Escolha até 12 para a próxima sessão.'
    draft.name = ''
    closeCreate()
  } catch (reason) { createError.value = reason instanceof Error ? reason.message : 'Não foi possível criar a estratégia.' }
  finally { creating.value = false }
}
const assessment = (key: string) => {
  const result = state.value?.snapshot?.research?.assessments.find(item => item.key === key)?.status
  return result === 'promising' ? 'Sinal inicial favorável' : result === 'not_confirmed' ? 'Não confirmada' : result === 'insufficient_sample' ? 'Amostra insuficiente' : 'Em observação'
}
const stale = computed(() => state.value?.active && (!state.value.heartbeat || now.value - Date.parse(state.value.heartbeat) > 60000 || !state.value.processed_through || now.value - Date.parse(state.value.processed_through) > 600000))
const today = (key: string) => {
  const localDay = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(now.value))
  return live(key)?.daily.find(item => item.day === localDay)?.return_pct
}
async function refresh() {
  if (fetching || busy.value) return
  fetching = true
  const current = revision
  const symbol = props.symbol
  try {
    const data = await getLiveSimulation(symbol)
    if (current === revision && symbol === props.symbol) { state.value = data; error.value = ''; syncAutomaticSelection() }
  } catch (reason) {
    if (current === revision) error.value = reason instanceof Error ? reason.message : 'Não foi possível consultar a simulação.'
  } finally { fetching = false; loading.value = false; now.value = Date.now() }
}
async function toggle() {
  if (busy.value) return
  busy.value = true; error.value = ''; revision++
  try {
    if (!state.value?.active && selectionChanged.value && !await saveSelection()) return
    const symbol = props.symbol
    const data = await setLiveSimulation(!state.value?.active, symbol)
    if (symbol !== props.symbol) return
    state.value = data
    syncAutomaticSelection()
    if (state.value.active) notice.value = 'Nova sessão iniciada com a seleção salva.'
  }
  catch (reason) { error.value = reason instanceof Error ? reason.message : 'Não foi possível atualizar a simulação.' }
  finally { busy.value = false; now.value = Date.now() }
}
onMounted(() => { void refresh(); void loadCatalog(); polling = window.setInterval(() => { now.value = Date.now(); void refresh() }, 10000) })
watch(() => props.symbol, () => {
  revision++; fetching = false; state.value = null; catalog.value = []; selectedKeys.value = []
  savedKeys.value = []; catalogLoaded.value = false; loading.value = true; error.value = ''
  void refresh(); void loadCatalog()
})
onBeforeUnmount(() => { if (polling) window.clearInterval(polling); revision++ })
</script>

<template>
  <main class="sim-lab">
    <header class="sim-toolbar">
      <div>
        <p class="sim-label">{{ props.symbol }} <span>·</span> 5 minutos <span>·</span> Paper trading</p>
        <h2>Estratégias da sessão</h2>
        <p class="sim-subtitle">Todas as estratégias acompanhadas nesta sessão, com resultados positivos e negativos.</p>
      </div>
      <div class="sim-controls">
        <span class="sim-status" :class="{ active: state?.active && !stale }"><i />{{ loading ? 'Carregando' : stale ? 'Dados atrasados' : state?.active ? 'Em execução' : 'Parada' }}</span>
        <button class="sim-secondary" type="button" @click="openCreate">Criar estratégia</button>
        <button :disabled="busy || loading || !state" type="button" @click="toggle">{{ busy ? 'Processando…' : state?.active ? 'Parar simulação' : state?.snapshot && !sessionStrategies.length ? 'Reavaliar estratégias' : 'Ativar simulação' }}</button>
      </div>
    </header>
    <p v-if="error || state?.last_error" class="sim-error" role="alert">{{ error || state?.last_error }}</p>
    <p v-if="stale" class="sim-error">Aguardando atualização da coleta ou do processo de simulação. O último resultado foi preservado.</p>
    <div class="sim-context" v-if="state">
      <span>Banca inicial <strong>US$ {{ number(state.configuration.initial_equity, 0) }} / estratégia</strong></span>
      <span>Meta diária <strong>{{ number(state.configuration.daily_goal_pct, 0) }}% <small>referência</small></strong></span>
      <span>Último candle <strong>{{ date(state.processed_through) }}</strong></span>
    </div>
    <section v-if="state && sessionStrategies.length" class="sim-results" aria-label="Comparação das estratégias da sessão">
      <div class="sim-table-scroll">
        <table>
          <thead><tr><th>Estratégia</th><th>Validação histórica<small>Retorno · acerto · operações</small></th><th>Sessão ao vivo<small>Retorno líquido · acerto</small></th><th>Hoje<small>São Paulo · parcial</small></th><th>Posição</th></tr></thead>
          <tbody>
            <tr v-for="(strategy, index) in sessionStrategies" :key="strategy.key">
              <td><div class="sim-name"><span class="sim-index">0{{ index + 1 }}</span><div><strong>{{ strategyName(strategy) }}</strong><small>{{ strategy.leverage }}× · {{ assessment(strategy.key) }}</small></div></div></td>
              <td><strong :class="{ positive: (historical(strategy.key)?.total_return_pct ?? 0) > 0, negative: (historical(strategy.key)?.total_return_pct ?? 0) < 0 }">{{ percent(historical(strategy.key)?.total_return_pct) }}</strong><small>{{ percent(historical(strategy.key)?.win_rate) }} acerto · {{ historical(strategy.key)?.closed_trades ?? 0 }} trades</small></td>
              <td><strong :class="{ positive: (live(strategy.key)?.total_return_pct ?? 0) > 0, negative: (live(strategy.key)?.total_return_pct ?? 0) < 0 }">{{ percent(live(strategy.key)?.total_return_pct) }}</strong><small>{{ percent(live(strategy.key)?.win_rate) }} acerto · {{ live(strategy.key)?.closed_trades ?? 0 }} trades</small></td>
              <td>{{ percent(today(strategy.key)) }}</td>
              <td><span class="sim-position" :class="{ open: live(strategy.key)?.open_position }">{{ live(strategy.key)?.open_position?.side ?? 'Aguardando' }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="sim-caption">Acerto conta apenas operações fechadas com lucro após custos. Sem operações, o acerto aparece como “—”.</p>
    </section>
    <section v-else-if="state" class="sim-empty" role="status">
      <h3>{{ state.snapshot ? 'Nenhuma estratégia aprovada nesta moeda' : 'Aguardando avaliação das estratégias' }}</h3>
      <p>{{ state.snapshot?.research?.selection_message || 'Ative a simulação para avaliar o histórico e acompanhar juntas as estratégias selecionadas.' }}</p>
    </section>
    <details class="sim-picker" aria-label="Escolher estratégias para simular" open>
      <summary class="sim-picker-head"><div><h3>Escolher estratégias</h3><p>{{ automaticSelection ? 'A seleção automática usa até três hipóteses lucrativas nos dois períodos históricos, ordenadas pelo acerto no segundo.' : 'Seleção salva para a próxima sessão. A sessão atual mantém as regras com que começou.' }}</p></div><span>{{ selectedKeys.length }}/12 selecionadas</span></summary>
      <div class="sim-picker-actions"><input v-model="catalogSearch" type="search" placeholder="Buscar por nome ou regra" aria-label="Buscar estratégias" /><button class="sim-secondary" type="button" :disabled="catalogBusy || !selectionChanged" @click="saveSelection">{{ catalogBusy ? 'Salvando…' : 'Salvar seleção' }}</button></div>
      <p v-if="automaticSelection && !sessionKeys.length" class="sim-muted">Se nenhuma hipótese cumprir os critérios, a simulação não inicia automaticamente. Você ainda pode selecionar uma hipótese experimental.</p>
      <div class="sim-picker-list">
        <label v-for="strategy in visibleCatalog" :key="strategy.key" class="sim-picker-item"><input type="checkbox" :checked="selectedKeys.includes(strategy.key)" :disabled="!selectedKeys.includes(strategy.key) && selectedKeys.length >= 12" @change="toggleKey(strategy.key)" /><span><strong>{{ strategyName(strategy) }}</strong><small>{{ sessionKeys.includes(strategy.key) && state?.active ? 'Em simulação · ' : '' }}{{ strategy.entry_rule ? 'Criada por você' : 'Catálogo' }} · {{ strategy.leverage }}×<template v-if="trial(strategy.key)?.qualified != null"> · {{ trial(strategy.key)?.qualified ? 'apta na triagem' : 'não aprovada' }} · retorno {{ percent(trial(strategy.key)?.validation_return) }} no segundo período · {{ percent(trial(strategy.key)?.validation_win_rate) }} acerto</template><template v-else-if="validation(strategy.key)"> · pesquisa anterior · validação {{ percent(validation(strategy.key)?.total_return_pct) }} retorno · {{ percent(validation(strategy.key)?.win_rate) }} acerto</template><template v-else-if="trial(strategy.key)"> · pesquisa anterior · descoberta {{ percent(trialReturn(strategy.key)) }} retorno</template></small></span></label>
        <p v-if="!catalog.length" class="sim-muted">Carregando catálogo…</p><p v-else-if="!visibleCatalog.length" class="sim-muted">Nenhuma estratégia encontrada.</p>
      </div>
      <p v-if="catalogError" class="sim-error" role="alert">{{ catalogError }}</p><p v-if="notice" class="sim-muted" role="status">{{ notice }}</p>
    </details>
    <p v-if="state?.snapshot" class="sim-caption">{{ sessionStrategies.length }} estratégias nesta sessão · {{ state.active ? 'Acompanhamento ativo' : 'Simulação parada — últimos resultados preservados' }}. Lucro histórico não garante lucro na sessão ao vivo.</p>
    <p class="sim-notice" v-if="state?.snapshot?.research">{{ state.snapshot.research.candidates_tested }} configurações do catálogo comparadas{{ state.snapshot.research.custom_tested ? `, mais ${state.snapshot.research.custom_tested} criada(s) por você` : '' }}. O segundo período histórico participa da seleção; não é uma prova independente. A sessão em papel acompanha o desempenho futuro.</p>
    <section class="sim-details" v-if="state">
      <details>
        <summary>Todas as estratégias testadas <span>{{ testedStrategies.length }} configurações · {{ state.snapshot?.symbol ?? props.symbol }}</span></summary>
        <div class="sim-detail-body sim-catalog">
          <p>Resultados desta pesquisa em {{ state.snapshot?.symbol ?? props.symbol }} · {{ state.snapshot?.timeframe ?? '5m' }}. Inclui resultados negativos e positivos; uma estratégia pode ter comportamento diferente em outra moeda.</p>
          <p class="sim-muted">O catálogo foi comparado nos dois períodos históricos. A triagem usa ambos; a sessão em papel é a observação independente. Retornos incluem os custos estimados.</p>
          <p v-if="!testedStrategies.length" class="sim-muted">Ainda não há configurações testadas registradas nesta sessão.</p>
          <details v-for="trial in testedStrategies" :key="trial.strategy.key">
            <summary>{{ strategyName(trial.strategy) }} <span>{{ trial.strategy.key }} · descoberta {{ percent(trial.discovery_return) }} · {{ trial.trades }} trades</span></summary>
            <div class="sim-detail-body">
              <p>{{ trial.strategy.description }}</p>
              <p class="sim-muted">{{ trial.strategy.leverage }}× · stop mínimo {{ percent(trial.strategy.stop_floor * 100) }} / {{ trial.strategy.atr_multiple }} ATR · alvo {{ trial.strategy.reward_risk }}R · prazo {{ trial.strategy.max_candles }} candles.</p>
              <p v-if="trial.strategy.key.startsWith('momentum_reset')" class="sim-muted">RSI: {{ trial.strategy.threshold }} LONG / {{ 100 - (trial.strategy.threshold ?? 50) }} SHORT.</p>
              <p v-if="trial.strategy.key.startsWith('failed_breakout')" class="sim-muted">Volume mínimo: {{ trial.strategy.threshold }}× a média.</p>
              <div class="sim-detail-grid">
                <div><span>Retorno na descoberta</span><strong :class="trial.discovery_return > 0 ? 'positive' : trial.discovery_return < 0 ? 'negative' : ''">{{ percent(trial.discovery_return) }}</strong></div>
                <div><span>Drawdown na descoberta</span><strong>{{ percent(trial.discovery_drawdown) }}</strong></div>
                <div><span>Retorno no segundo período</span><strong :class="(trial.validation_return ?? 0) > 0 ? 'positive' : (trial.validation_return ?? 0) < 0 ? 'negative' : ''">{{ percent(trial.validation_return ?? validation(trial.strategy.key)?.total_return_pct) }}</strong></div>
                <div><span>Acerto no segundo período</span><strong>{{ percent(trial.validation_win_rate ?? validation(trial.strategy.key)?.win_rate) }}</strong></div>
              </div>
              <p class="sim-muted">{{ trial.qualified == null ? 'Pesquisa anterior; reavalie para ver a triagem completa.' : trial.qualified ? 'Apta na triagem histórica' : 'Não aprovada na triagem histórica' }} · {{ trial.validation_trades ?? validation(trial.strategy.key)?.closed_trades ?? '—' }} operações no segundo período.</p>
            </div>
          </details>
        </div>
      </details>
      <details v-for="strategy in sessionStrategies" :key="strategy.key">
        <summary>{{ strategyName(strategy) }} <span>Regras e desempenho</span></summary>
        <div class="sim-detail-body">
          <p>{{ strategy.description }}</p>
          <p class="sim-muted">Stop: maior entre {{ percent(strategy.stop_floor * 100) }} e {{ strategy.atr_multiple }} ATR · alvo {{ strategy.reward_risk }}R · expiração {{ strategy.max_candles }} candles · margem {{ percent(state.configuration.margin_fraction * 100) }} da banca.</p>
          <p v-if="strategy.key.startsWith('momentum_reset')" class="sim-muted">Gatilho RSI: {{ strategy.threshold }} para LONG / {{ 100 - (strategy.threshold ?? 50) }} para SHORT.</p>
          <p v-if="strategy.key.startsWith('failed_breakout')" class="sim-muted">Volume mínimo: {{ strategy.threshold }}× a média de 20 candles.</p>
          <div class="sim-detail-grid"><div><span>Descoberta</span><strong>{{ percent(training(strategy.key)?.total_return_pct) }}</strong></div><div><span>Drawdown na validação</span><strong>{{ percent(historical(strategy.key)?.max_drawdown_pct) }}</strong></div><div><span>Profit factor na validação</span><strong>{{ number(historical(strategy.key)?.profit_factor) }}</strong></div><div><span>Banca ao vivo</span><strong>US$ {{ number(live(strategy.key)?.equity) }}</strong></div></div>
          <p class="sim-muted">Custos realizados nesta sessão: taxas US$ {{ number(live(strategy.key)?.fees) }} · slippage US$ {{ number(live(strategy.key)?.slippage) }} · funding US$ {{ number(live(strategy.key)?.funding) }}.</p>
          <p v-if="live(strategy.key)?.open_position">Entrada {{ number(live(strategy.key)?.open_position?.entry_price) }} · resultado aberto estimado US$ {{ number(live(strategy.key)?.open_position?.estimated_net_pnl) }}.</p>
          <div class="sim-table-scroll" v-if="live(strategy.key)?.recent_trades.length"><table><thead><tr><th>Saída</th><th>Lado</th><th>Evento</th><th>Líquido US$</th></tr></thead><tbody><tr v-for="trade in live(strategy.key)?.recent_trades ?? []" :key="trade.entry_time"><td>{{ date(trade.exit_time) }}</td><td>{{ trade.side }}</td><td>{{ trade.status }}{{ trade.ambiguous ? ' · ambíguo' : '' }}</td><td>{{ number(trade.net_pnl) }}</td></tr></tbody></table></div>
        </div>
      </details>
      <details>
        <summary>Dados e premissas <span>Período, custos e funcionamento</span></summary>
        <div class="sim-detail-body">
          <p v-if="state.snapshot?.research">Descoberta: {{ date(state.snapshot.research.discovery_start) }} a {{ date(state.snapshot.research.discovery_end) }}.<br />Validação: {{ date(state.snapshot.research.validation_start) }} a {{ date(state.snapshot.research.validation_end) }}.</p>
          <p v-if="state.snapshot?.research?.excluded_recent_candles" class="sim-muted">Os últimos {{ state.snapshot.research.excluded_recent_candles }} candles, já explorados anteriormente, foram excluídos desta pesquisa histórica.</p>
          <p>{{ state.snapshot?.research?.selected_manually ? 'As estratégias foram escolhidas pelo usuário antes da sessão.' : state.snapshot?.research?.method }} A validação não escolhe os parâmetros. O acompanhamento ao vivo é o próximo teste.</p>
          <p>{{ state.strategies.length }} bancas independentes. Entrada no candle posterior ao sinal; stop primeiro quando o candle é ambíguo. Não somar retornos como se fossem uma carteira. Custos estimados: {{ number(state.configuration.fee_rate * 100, 3) }}% por execução, {{ number(state.configuration.slippage_rate * 100, 3) }}% de slippage e {{ number(state.configuration.hourly_funding_rate * 100, 5) }}% de funding por hora.</p>
          <p>Binance spot, liquidação aproximada; sem fills ou funding histórico da Hyperliquid. A meta de 5% não é uma previsão. Nenhuma ordem real é enviada.</p>
          <p>Ao parar, posições virtuais encerram no último fechamento. Reativar cria nova sessão; a anterior fica arquivada no banco. Os resultados continuam sendo processados com a página fechada.</p>
          <p class="sim-muted">Sessão iniciada: {{ date(state.started_at) }} · processamento: {{ date(state.heartbeat) }}</p>
        </div>
      </details>
    </section>
    <dialog ref="modal" class="strategy-modal" aria-labelledby="create-strategy-title"><form class="strategy-form" @submit.prevent="createStrategy">
      <div class="modal-head"><div><p class="sim-label">SIMULADOR · {{ props.symbol }} 5M</p><h3 id="create-strategy-title">Criar estratégia</h3></div><button type="button" class="modal-close" aria-label="Fechar" @click="closeCreate">×</button></div>
      <p class="sim-muted">Monte a lógica com gatilhos e filtros. A estratégia entra na próxima sessão do simulador; cada sinal usa somente candles fechados.</p>
      <label>Nome da estratégia<input v-model.trim="draft.name" type="text" minlength="3" maxlength="60" required placeholder="Ex.: Rompimento com RSI" /></label>
      <div class="modal-grid"><label>Direção<select v-model="draft.direction"><option value="BOTH">Compra e venda</option><option value="LONG">Somente compra</option><option value="SHORT">Somente venda</option></select></label><label>Combinar gatilhos<select v-model="draft.trigger_mode"><option value="ANY">Qualquer um (OU)</option><option value="ALL">Todos no mesmo candle (E)</option></select></label></div>
      <fieldset class="rule-section"><legend>1. Gatilhos de entrada <small>selecione um ou mais</small></legend><div class="rule-options"><label v-for="option in triggerOptions" :key="option.key" class="rule-option"><input type="checkbox" :checked="hasTrigger(option.key)" @change="toggleTrigger(option.key)" /><span><strong>{{ option.title }}</strong><small>{{ option.detail }}</small></span></label></div></fieldset>
      <fieldset class="rule-section"><legend>2. Filtros obrigatórios <small>todos os selecionados devem passar</small></legend><div class="rule-options"><label v-for="option in filterOptions" :key="option.key" class="rule-option"><input type="checkbox" :checked="hasFilter(option.key)" @change="toggleFilter(option.key)" /><span><strong>{{ option.title }}</strong><small>{{ option.detail }}</small></span></label></div></fieldset>
      <div v-if="hasTrigger('rsi_recovery') || hasFilter('rsi_band') || hasFilter('volume')" class="modal-grid">
        <label v-if="hasTrigger('rsi_recovery') || hasFilter('rsi_band')">RSI mínimo / recuperação na compra<input v-model.number="draft.rsi_lower" type="number" min="1" :max="hasTrigger('rsi_recovery') ? 49 : 79" step="1" required /></label>
        <label v-if="hasFilter('rsi_band')">RSI máximo na compra<input v-model.number="draft.rsi_upper" type="number" min="21" max="99" step="1" required /></label>
        <label v-if="hasFilter('volume')">Volume mínimo (× média)<input v-model.number="draft.volume_min" type="number" min="0.1" max="5" step="0.1" required /></label>
      </div>
      <p v-if="hasTrigger('rsi_recovery') || hasFilter('rsi_band')" class="sim-muted">Os limites de RSI para venda são espelhados: 100 menos o valor configurado.</p>
      <div class="rule-preview"><small>Lógica de entrada</small><p>{{ rulePreview }}</p></div>
      <h4 class="rule-heading">3. Saída e risco no simulador</h4>
      <div class="modal-grid"><label>Alavancagem simulada<input v-model.number="draft.leverage" type="number" min="1" max="20" step="1" required /></label><label>Stop mínimo (%)<input v-model.number="draft.stop_pct" type="number" min="0.1" max="10" step="0.1" required /></label><label>Stop por ATR (×)<input v-model.number="draft.atr_multiple" type="number" min="0.1" max="5" step="0.1" required /></label><label>Alvo (R)<input v-model.number="draft.reward_risk" type="number" min="0.5" max="10" step="0.1" required /></label><label>Prazo máximo (horas)<input v-model.number="draft.max_hours" type="number" min="1" max="24" step="1" required /></label></div>
      <p class="sim-muted">Stop efetivo: o maior entre o percentual e o ATR. A entrada ocorre no candle posterior ao sinal.</p>
      <p v-if="createError" class="sim-error" role="alert">{{ createError }}</p>
      <div class="modal-actions"><button class="sim-secondary" type="button" @click="closeCreate">Cancelar</button><button type="submit" :disabled="creating || !draft.entry_triggers.length">{{ creating ? 'Criando…' : 'Criar e selecionar' }}</button></div>
    </form></dialog>
  </main>
</template>

<style scoped>
.sim-lab { display: grid; gap: 24px; color: #dce4ee; }
.sim-empty { padding: 36px 24px; border: 1px solid #233044; border-radius: 10px; background: #0d1929; }
.sim-empty h3 { font-size: 1rem; font-weight: 500; margin-bottom: 10px; }
.sim-empty p { color: #94a3b8; font-size: .85rem; max-width: 740px; margin: 0; }
.sim-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 28px; padding: 12px 0 4px; }
.sim-label { color: #94a3b8; font-size: .75rem; margin-bottom: 10px; letter-spacing: .025em; }.sim-label span { padding: 0 8px; opacity: .5; }
h2 { margin-bottom: 8px; font-size: 1.6rem; font-weight: 600; letter-spacing: -.03em; }.sim-subtitle { margin: 0; color: #94a3b8; font-size: .88rem; }
.sim-controls { display: flex; gap: 16px; align-items: center; flex-shrink: 0; }
.sim-status { display: flex; align-items: center; gap: 7px; font-size: .8rem; color: #94a3b8; }.sim-status i { width: 6px; height: 6px; border-radius: 50%; background: #94a3b8; }.sim-status.active i { background: #55c49d; }
button { border: 1px solid #455468; background: #e4ebf4; color: #142032; border-radius: 7px; padding: 10px 16px; cursor: pointer; font-weight: 600; font-size: .82rem; white-space: nowrap; }button:disabled { opacity: .55; cursor: wait; }button:focus-visible, summary:focus-visible { outline: 2px solid #93c5fd; outline-offset: 4px; }
.sim-context { display: flex; flex-wrap: wrap; gap: 22px 40px; padding: 18px 0; border-block: 1px solid #233044; font-size: .75rem; color: #94a3b8; }.sim-context strong { display: block; margin-top: 5px; font-size: .88rem; color: #dce4ee; font-weight: 500; }.sim-context small { font-size: .72rem; color: #94a3b8; font-weight: 400; }
.sim-results { border: 1px solid #233044; border-radius: 10px; background: #0d1929; overflow: hidden; }.sim-table-scroll { overflow-x: auto; }table { width: 100%; border-collapse: collapse; font-size: .84rem; }th { text-align: left; color: #a9b7c9; font-size: .74rem; font-weight: 500; padding: 17px 20px; background: #101e30; white-space: nowrap; }td { padding: 23px 20px; border-top: 1px solid #233044; vertical-align: middle; white-space: nowrap; }td strong { font-weight: 600; }table small { display: block; font-weight: 400; color: #94a3b8; font-size: .7rem; margin-top: 5px; }
.sim-name { display: flex; gap: 14px; align-items: center; }.sim-index { color: #718198; font-size: .72rem; font-variant-numeric: tabular-nums; }.positive { color: #67c7a5; }.negative { color: #e99898; }.sim-position { color: #94a3b8; font-size: .76rem; }.sim-position.open { color: #93c5fd; }
.sim-caption { color: #8494ab; font-size: .72rem; margin: 0; padding: 14px 20px; border-top: 1px solid #233044; }.sim-notice { margin: 0; color: #a6b2c4; font-size: .8rem; max-width: 880px; line-height: 1.7; }
.sim-error { color: #f2b3b3; border-left: 2px solid #c87575; padding: 8px 14px; font-size: .85rem; }
.sim-details details { border-bottom: 1px solid #233044; }summary { padding: 17px 0; cursor: pointer; font-size: .85rem; font-weight: 500; }summary span { color: #8292a8; font-size: .75rem; font-weight: 400; margin-left: 14px; }.sim-detail-body { padding: 0 0 18px; font-size: .83rem; line-height: 1.7; max-width: 1000px; }.sim-muted { color: #94a3b8; }.sim-detail-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin: 20px 0; }.sim-detail-grid span { color: #94a3b8; display: block; font-size: .73rem; }.sim-detail-grid strong { font-weight: 500; }
@media (max-width: 1000px) { .sim-toolbar { align-items: flex-start; flex-direction: column; gap: 18px; } th, td { padding: 16px 12px; } }
@media (max-width: 600px) { .sim-context { gap: 18px; }.sim-detail-grid { grid-template-columns: 1fr 1fr; }summary span { display: block; margin: 5px 0 0 18px; } }
.sim-secondary { background: transparent; color: #dce4ee; border: 1px solid #455468; }.sim-secondary:hover:not(:disabled) { background: #1b2b40; }
.sim-picker { border: 1px solid #233044; border-radius: 10px; background: #0d1929; padding: 22px; }.sim-picker-head,.sim-picker-actions { display: flex; justify-content: space-between; align-items: center; gap: 16px; }.sim-picker-head h3 { font-size: 1rem; margin: 0 0 6px; }.sim-picker-head p { color: #94a3b8; font-size: .8rem; margin: 0; }.sim-picker-head>span { color: #94a3b8; font-size: .75rem; white-space: nowrap; }.sim-picker-actions { justify-content: flex-start; margin: 18px 0 12px; }.sim-picker-actions input { flex: 1; max-width: 420px; }.sim-picker input[type="search"],.strategy-modal input:not([type="checkbox"]),.strategy-modal select { min-width: 0; width: 100%; padding: 10px 12px; border: 1px solid #455468; border-radius: 7px; background: #101e30; color: #dce4ee; }.sim-picker-list { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 1px 16px; max-height: 360px; overflow: auto; border-top: 1px solid #233044; }.sim-picker-item { display: flex; align-items: flex-start; gap: 11px; padding: 12px 6px; border-bottom: 1px solid #233044; cursor: pointer; min-width: 0; }.sim-picker-item input { margin-top: 4px; accent-color: #67c7a5; }.sim-picker-item span { min-width: 0; }.sim-picker-item strong { display: block; font-size: .78rem; font-weight: 500; line-height: 1.4; }.sim-picker-item small { display: block; font-size: .7rem; color: #94a3b8; margin-top: 4px; }.sim-picker .sim-muted { font-size: .76rem; }
.sim-picker-head { padding: 0; list-style: none; cursor: pointer; }.sim-picker-head::-webkit-details-marker { display: none; }.sim-picker-head::after { content: '▾'; color: #94a3b8; font-size: 1.1rem; margin-left: 3px; }.sim-picker:not([open]) .sim-picker-head::after { transform: rotate(-90deg); }.sim-picker-head:focus-visible { outline: 2px solid #93c5fd; outline-offset: 5px; }
.strategy-modal { width: min(720px,calc(100vw - 30px)); max-height: min(90vh,900px); overflow-y: auto; padding: 0; border: 1px solid #455468; border-radius: 12px; background: #0d1929; color: #dce4ee; box-shadow: 0 24px 80px rgba(0,0,0,.55); }.strategy-modal::backdrop { background: rgba(2,8,18,.76); }.strategy-form { display: grid; gap: 16px; padding: 24px; }.modal-head,.modal-actions { display: flex; justify-content: space-between; align-items: center; gap: 16px; }.modal-head h3 { margin: 0; font-size: 1.25rem; }.modal-close { padding: 4px 10px; background: transparent; color: #94a3b8; border: 0; font-size: 1.5rem; }.strategy-form label { display: grid; gap: 7px; color: #b5c2d2; font-size: .78rem; }.modal-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px; }.strategy-form .modal-check { display: flex; align-items: center; gap: 9px; }.modal-check input { accent-color: #67c7a5; }.modal-actions { justify-content: flex-end; padding-top: 10px; border-top: 1px solid #233044; }.strategy-form .sim-muted { margin: 0; font-size: .75rem; }.strategy-modal button:focus-visible,.strategy-modal input:focus-visible,.strategy-modal select:focus-visible,.sim-picker input:focus-visible { outline: 2px solid #93c5fd; outline-offset: 3px; }
.rule-section { border: 1px solid #293b50; border-radius: 8px; padding: 12px; margin: 0; }.rule-section legend { padding: 0 6px; font-size: .82rem; font-weight: 600; }.rule-section legend small { color: #94a3b8; font-weight: 400; margin-left: 6px; }.rule-options { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; }.strategy-form .rule-option { display: flex; gap: 9px; align-items: flex-start; padding: 10px; border: 1px solid #293b50; border-radius: 7px; cursor: pointer; }.rule-option:has(input:checked) { border-color: #4b8e83; background: #142b32; }.rule-option input { margin-top: 3px; accent-color: #67c7a5; }.rule-option span { min-width: 0; }.rule-option strong { display: block; color: #e2eaf3; font-size: .77rem; font-weight: 600; }.rule-option small { display: block; color: #94a3b8; font-size: .7rem; line-height: 1.4; margin-top: 4px; }.rule-preview { border-left: 2px solid #67c7a5; background: #10252b; padding: 11px 14px; }.rule-preview small { color: #91b9ad; font-size: .7rem; text-transform: uppercase; letter-spacing: .06em; }.rule-preview p { margin: 5px 0 0; font-size: .8rem; line-height: 1.5; }.rule-heading { margin: 4px 0 -4px; font-size: .82rem; }
@media (max-width: 600px) { .rule-options { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .sim-controls { flex-wrap: wrap; }.sim-picker-head { align-items: flex-start; }.sim-picker-list { grid-template-columns: 1fr; }.sim-picker-actions { flex-wrap: wrap; }.modal-grid { grid-template-columns: 1fr; } }
</style>

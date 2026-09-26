<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getAuthSession, getComponents, getEntries, getEvaluation, getHistory, getStatus, signOut } from './services/api'
import type { ComponentSummary, EvaluationRow, SignalRow, StatusPayload } from './types/api'
import InfoPopover from './components/InfoPopover.vue'
import LoginView from './views/LoginView.vue'

const isLoginRoute = ref(window.location.pathname.replace(/\/+$/, '') === '/login')
const isAuthenticated = ref(false)
const authReady = ref(false)
const authError = ref('')

const status = ref<StatusPayload | null>(null)
const history = ref<SignalRow[]>([])
const components = ref<ComponentSummary[]>([])
const entries = ref<SignalRow[]>([])
const evaluation = ref<EvaluationRow[]>([])
const isLoading = ref(true)
const scoreThreshold = computed(() => toNumber(status.value?.threshold) ?? 65)
const visibleCount = ref(5)
const historyExpanded = ref(false)
const historyFilter = ref<'ALL' | 'LONG' | 'SHORT' | 'WAIT'>('ALL')
const lastAlertKey = ref<string | null>(null)
const STORAGE_KEY = 'scanner-component-config-v1'
const componentConfig = ref<Record<string, boolean>>({})

const formatNumber = (value: number | string | null | undefined, digits = 2) => {
  if (value === null || value === undefined || value === 'N/D' || value === '') return 'N/D'
  const num = Number(value)
  if (Number.isNaN(num)) return 'N/D'
  return num.toLocaleString('pt-BR', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

const formatDate = (value: string | null | undefined) => {
  if (!value || value === 'N/D') return 'N/D'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

const toNumber = (value: number | string | undefined | null) => {
  if (value === null || value === undefined || value === '') return null
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

const normalizeSide = (value: string | null | undefined) => {
  const side = (value ?? '').toString().trim().toUpperCase()
  if (side === 'LONG' || side === 'SHORT') return side
  return 'WAIT'
}

const getSignalSide = (row: SignalRow | null | undefined) => normalizeSide(row?.side)

const getTrendBias = (row: SignalRow | null | undefined) => {
  const trend = (row?.trend_bias ?? '').toString().trim().toUpperCase()
  return trend || 'N/D'
}

const getComponentLabel = (name: string) => {
  const labels: Record<string, string> = {
    trend_ema: 'Tendência por EMAs',
    price_above_ema: 'Preço em relação à EMA21',
    price_below_ema: 'Preço em relação à EMA21',
    rsi_favorable: 'RSI favorável',
    rsi_extreme: 'RSI extremo',
    volume_confirmation: 'Confirmação por volume',
    fib: 'Proximidade de Fibonacci',
    liquidity_sweep: 'Sweep de liquidez',
    structure: 'Estrutura de preço',
  }
  const component = name.replace(/^(long|short)_/, '')
  return labels[component] ?? component.replace(/_/g, ' ')
}

const loadComponentConfig = () => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      componentConfig.value = Object.fromEntries((components.value ?? []).map((item) => [item.name, true]))
      return
    }
    const parsed = JSON.parse(raw) as Record<string, boolean>
    componentConfig.value = Object.fromEntries((components.value ?? []).map((item) => [item.name, parsed[item.name] ?? true]))
  } catch (error) {
    console.warn('Configuração local de componentes indisponível.', error)
    componentConfig.value = Object.fromEntries((components.value ?? []).map((item) => [item.name, true]))
  }
}

const persistComponentConfig = () => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(componentConfig.value))
}

const isComponentEnabled = (name: string) => componentConfig.value[name] ?? true

const toggleComponent = (name: string) => {
  componentConfig.value[name] = !isComponentEnabled(name)
  persistComponentConfig()
}

const latestHistory = computed(() => history.value[0] ?? null)
const latestEvaluation = computed(() => evaluation.value[evaluation.value.length - 1] ?? null)

const longScoreValue = computed(() => toNumber((latestHistory.value?.long_score as string | number | undefined) ?? status.value?.long_score) ?? 0)
const shortScoreValue = computed(() => toNumber((latestHistory.value?.short_score as string | number | undefined) ?? status.value?.short_score) ?? 0)

const longPercent = computed(() => Math.min(100, (longScoreValue.value / scoreThreshold.value) * 100))
const shortPercent = computed(() => Math.min(100, (shortScoreValue.value / scoreThreshold.value) * 100))

const timeframeParts = computed(() => (status.value?.timeframe ?? '').split('/').map((part) => part.trim()).filter(Boolean))
const contextTimeframe = computed(() => timeframeParts.value[0]?.toUpperCase() ?? 'N/D')
const structureTimeframe = computed(() => timeframeParts.value[1]?.toUpperCase() ?? 'N/D')
const triggerTimeframe = computed(() => timeframeParts.value[2]?.toUpperCase() ?? 'N/D')
const currentDirection = computed(() => getSignalSide(latestHistory.value))
const currentSetupState = computed(() => (latestHistory.value?.setup_state ?? 'N/D').toString().trim().toUpperCase())
const currentEntryState = computed(() => (latestHistory.value?.entry_state ?? 'N/D').toString().trim().toUpperCase())

const currentComponentActive = (name: string): boolean | null => {
  const value = latestHistory.value?.[`${name}_active`]
  if (value === true || value === 'true' || value === 1 || value === '1') return true
  if (value === false || value === 'false' || value === 0 || value === '0') return false
  return null
}

const currentComponentPoints = (name: string): number | null => {
  return toNumber(latestHistory.value?.[`${name}_points`] as number | string | null | undefined)
}

const currentComponentValue = (name: string): number | null => {
  return toNumber(latestHistory.value?.[`${name}_value`] as number | string | null | undefined)
}

const visibleComponents = computed(() => components.value.filter((item) => isComponentEnabled(item.name)))

const componentInfo = (name: string) => {
  const direction = name.startsWith('long_') ? 'LONG' : 'SHORT'
  const component = name.replace(/^(long|short)_/, '')
  const descriptions: Record<string, string> = {
    trend_ema: `Compara as EMAs 21 e 50 no contexto de ${contextTimeframe.value}. Para ${direction}, fica ativo quando a EMA21 está na direção correspondente em relação à EMA50 e contribui com 20 pontos.`,
    price_above_ema: `Verifica se o fechamento do contexto ${contextTimeframe.value} está acima da EMA21; quando verdadeiro, contribui com 8 pontos LONG. Representa uma condição técnica, não uma ordem.`,
    price_below_ema: `Verifica se o fechamento do contexto ${contextTimeframe.value} está abaixo da EMA21; quando verdadeiro, contribui com 8 pontos SHORT. Representa uma condição técnica, não uma ordem.`,
    rsi_favorable: `Usa o RSI calculado no período de gatilho ${triggerTimeframe.value}. A faixa 52–68 contribui com 12 pontos LONG; 32–48 contribui com 12 pontos SHORT.`,
    rsi_extreme: `Usa o RSI calculado no período de gatilho ${triggerTimeframe.value}. RSI abaixo de 28 contribui com 6 pontos LONG; acima de 72 contribui com 6 pontos SHORT. Extremos não significam reversão automática.`,
    volume_confirmation: `Compara o volume do período de gatilho ${triggerTimeframe.value} com sua média móvel de 20 candles. Razão de pelo menos 1,2 e candle na direção do componente contribuem com 8 pontos.`,
    fib: `Verifica se o preço está a até 1 ATR do nível 0,618 de Fibonacci do contexto ${contextTimeframe.value}, com EMAs alinhadas. Se ativa, contribui com 15 pontos para este lado.`,
    liquidity_sweep: `Na estrutura ${structureTimeframe.value}, procura rompimento da máxima/mínima recente seguido de fechamento de volta para dentro dessa faixa. Se ativa, contribui com 15 pontos; não confirma reversão por si só.`,
    structure: `Compara o preço com máximas/mínimas recentes da estrutura ${structureTimeframe.value}: proximidade de rompimento (0,2%) ativa LONG ou SHORT conforme o lado. Se ativa, contribui com 5 pontos, sem garantir continuidade.`,
  }
  return descriptions[component] ?? 'Componente técnico usado na composição do score. A condição não representa, isoladamente, uma decisão de compra ou venda.'
}

const entryGuidance = computed(() => {
  if (!latestHistory.value) return 'Aguardando dados do scanner.'
  if (currentEntryState.value === 'ENTRY') return 'O scanner reconheceu ENTRY neste ciclo. Isso não garante o resultado futuro da operação.'

  const direction = longScoreValue.value >= shortScoreValue.value ? 'LONG' : 'SHORT'
  const selectedScore = direction === 'LONG' ? longScoreValue.value : shortScoreValue.value
  const oppositeScore = direction === 'LONG' ? shortScoreValue.value : longScoreValue.value
  const requirements = []
  if (selectedScore < scoreThreshold.value) requirements.push(`score ${direction} alcançar ${scoreThreshold.value}`)
  if (selectedScore <= oppositeScore + 5) requirements.push(`score ${direction} superar o oposto por mais de 5 pontos`)
  return requirements.length
    ? `Aguardando: ${requirements.join(' e ')}.`
    : 'Aguardando o próximo ciclo do scanner.'
})

const visibleHistory = computed(() => {
  const rows = [...history.value]
  const filtered = historyFilter.value === 'ALL'
    ? rows
    : rows.filter((row) => getSignalSide(row) === historyFilter.value)

  return filtered.slice(0, visibleCount.value)
})

const loadHistoryChunk = (nextCount: number) => {
  visibleCount.value = Math.min(Math.max(nextCount, 5), 200)
}

const collapseHistory = () => {
  visibleCount.value = 5
}

const syncHistoryExpanded = (event: Event) => {
  if (event.target instanceof HTMLDetailsElement) historyExpanded.value = event.target.open
}

const alertEntry = computed(() => {
  const latestEntry = [...history.value].find((row) => String(row.entry_state ?? '').toUpperCase() === 'ENTRY')

  if (!latestEntry) return null

  const direction = getSignalSide(latestEntry)
  const key = `${latestEntry.timestamp ?? latestEntry.timestamp_dt ?? 'na'}-${direction}`

  if (lastAlertKey.value === key) return null

  lastAlertKey.value = key

  return {
    direction,
    price: latestEntry.price_float ?? latestEntry.price ?? 'N/D',
    score: latestEntry.long_score && direction === 'LONG'
      ? latestEntry.long_score
      : latestEntry.short_score && direction === 'SHORT'
        ? latestEntry.short_score
        : latestEntry.score ?? 'N/D',
    trend: getTrendBias(latestEntry),
    timestamp: latestEntry.timestamp ?? latestEntry.timestamp_dt ?? 'N/D',
    components: components.value
      .filter((component) => isComponentEnabled(component.name) && currentComponentActive(component.name) === true)
      .slice(0, 6)
      .map((component) => `${getComponentLabel(component.name)} (+${currentComponentPoints(component.name) ?? 0})`),
  }
})

const loadData = async () => {
  try {
    const [statusPayload, historyPayload, componentsPayload, entriesPayload, evaluationPayload] = await Promise.all([
      getStatus(),
      getHistory(200),
      getComponents(),
      getEntries(),
      getEvaluation(),
    ])

    status.value = statusPayload
    history.value = historyPayload
    components.value = componentsPayload
    entries.value = entriesPayload
    evaluation.value = evaluationPayload

    if (!Object.keys(componentConfig.value).length) {
      loadComponentConfig()
    }
  } catch (error) {
    console.error('Erro ao carregar dados do dashboard', error)
  } finally {
    isLoading.value = false
  }
}

let intervalId: number | undefined

const navigateTo = (path: string, replace = false) => {
  if (replace) {
    window.history.replaceState({}, '', path)
  } else {
    window.history.pushState({}, '', path)
  }
  isLoginRoute.value = path === '/login'
}

const startDashboardPolling = () => {
  if (intervalId) return
  void loadData()
  intervalId = window.setInterval(() => {
    void loadData()
  }, 15000)
}

const handleAuthenticated = () => {
  isAuthenticated.value = true
  authError.value = ''
  navigateTo('/')
  startDashboardPolling()
}

const handleLogout = async () => {
  try {
    await signOut()
    isAuthenticated.value = false
    authError.value = ''
    if (intervalId) {
      window.clearInterval(intervalId)
      intervalId = undefined
    }
    navigateTo('/login')
  } catch (error) {
    console.error('Erro ao encerrar sessão', error)
    authError.value = 'Não foi possível encerrar a sessão. Tente novamente.'
  }
}

const synchronizeRoute = () => {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  isLoginRoute.value = path === '/login'
  if (!isAuthenticated.value && !isLoginRoute.value) {
    navigateTo('/login', true)
  } else if (isAuthenticated.value && isLoginRoute.value) {
    navigateTo('/', true)
  }
}

onMounted(async () => {
  window.addEventListener('popstate', synchronizeRoute)
  try {
    const auth = await getAuthSession()
    isAuthenticated.value = auth.authenticated
    if (!auth.authenticated && !isLoginRoute.value) {
      navigateTo('/login', true)
    } else if (auth.authenticated && isLoginRoute.value) {
      navigateTo('/', true)
    }
    if (auth.authenticated) startDashboardPolling()
  } catch (error) {
    console.error('Não foi possível validar a sessão', error)
    if (!isLoginRoute.value) navigateTo('/login', true)
  } finally {
    authReady.value = true
  }
})

onBeforeUnmount(() => {
  if (intervalId) window.clearInterval(intervalId)
  window.removeEventListener('popstate', synchronizeRoute)
})
</script>

<template>
  <LoginView v-if="authReady && !isAuthenticated" @authenticated="handleAuthenticated" />

  <div v-else-if="authReady && isAuthenticated" class="app-shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">IziCrypto</p>
        <h1>Análise de mercado</h1>
      </div>
      <div class="status-wrap">
        <span class="status-badge" :class="status?.scanner_status === 'ONLINE' ? 'online' : 'offline'">
          {{ status?.scanner_status || 'OFFLINE' }}
        </span>
        <div class="header-meta">
          <span>{{ status?.market || 'N/D' }}</span>
          <span>Atualizado {{ formatDate(status?.last_update) }}</span>
        </div>
        <button class="logout-button" type="button" @click="handleLogout">Encerrar sessão</button>
        <span v-if="authError" class="auth-error" role="alert">{{ authError }}</span>
      </div>
    </header>

    <main v-if="!isLoading" class="content">
      <section class="market-overview panel" aria-label="Contexto atual do mercado">
        <div class="market-overview__price">
          <div class="section-kicker">Ativo analisado</div>
          <strong class="market-symbol">{{ status?.market || 'N/D' }}</strong>
          <span class="market-price">{{ formatNumber(latestHistory?.price_float ?? latestHistory?.price ?? status?.price, 2) }}</span>
          <small>Último preço registrado · {{ formatDate(status?.last_update || latestHistory?.timestamp) }}</small>
        </div>

        <div class="timeframe-roles" aria-label="Timeframes usados pelo scanner">
          <div>
            <span>Contexto</span>
            <strong>{{ contextTimeframe }}</strong>
            <small>Tendência por EMAs</small>
          </div>
          <div>
            <span>Estrutura</span>
            <strong>{{ structureTimeframe }}</strong>
            <small>Liquidez e estrutura</small>
          </div>
          <div>
            <span>Gatilho</span>
            <strong>{{ triggerTimeframe }}</strong>
            <small>Preço e indicadores</small>
          </div>
        </div>

        <div class="market-overview__trend">
          <div class="field-label">
            <span>Tendência · {{ contextTimeframe }}</span>
            <InfoPopover title="Tendência do contexto">
              <p>A tendência é definida comparando as EMAs 21 e 50 no timeframe de contexto ({{ contextTimeframe }}): EMA21 acima indica LONG; abaixo indica SHORT; valores iguais indicam FLAT.</p>
              <p>Ela descreve o contexto do mercado e não representa, sozinha, uma entrada.</p>
            </InfoPopover>
          </div>
          <strong :class="`direction-${getTrendBias(latestHistory).toLowerCase()}`">{{ getTrendBias(latestHistory) }}</strong>
          <small>Direção do contexto maior</small>
        </div>
      </section>

      <section v-if="alertEntry" class="alert-strip panel" aria-live="polite">
        <div class="alert-strip__title">Nova entrada reconhecida pelo scanner</div>
        <div class="alert-strip__body">
          <div>
            <strong>{{ alertEntry.direction }}</strong>
            <span>{{ status?.market || 'N/D' }}</span>
          </div>
          <div>Preço: {{ formatNumber(alertEntry.price, 2) }}</div>
          <div>Score: {{ alertEntry.score }}</div>
          <div>Tendência: {{ alertEntry.trend }}</div>
          <div>Horário: {{ formatDate(alertEntry.timestamp) }}</div>
        </div>
        <div class="alert-strip__components" v-if="alertEntry.components.length">
          <span v-for="item in alertEntry.components" :key="item">{{ item }}</span>
        </div>
      </section>

      <section class="operational-panel panel" aria-labelledby="operational-title">
        <div class="operational-heading">
          <div>
            <p class="section-kicker">Estado operacional</p>
            <h2 id="operational-title">Status do mercado</h2>
          </div>
          <span class="direction-pill" :class="`direction-${currentDirection.toLowerCase()}`">
            {{ currentDirection === 'WAIT' ? 'AGUARDANDO' : currentDirection }}
          </span>
        </div>

        <div class="market-stages">
          <article class="market-stage">
            <div class="field-label">
              <span>1 · Contexto</span>
              <InfoPopover title="Contexto, setup e entrada">
                <p><strong>Contexto</strong> é a direção estimada pelas EMAs 21 e 50 no timeframe maior ({{ contextTimeframe }}). Não indica que exista uma operação.</p>
                <p>O scanner marca <strong>NO_SETUP</strong> quando o lado permanece WAIT e <strong>SETUP</strong> quando reconhece um lado LONG/SHORT. Na implementação atual, SETUP e ENTRY aparecem juntos; não há uma etapa de setup independente antes da entrada.</p>
                <p><strong>ENTRY</strong> ocorre quando o score direcional atinge o threshold e supera o score oposto por mais de 5 pontos. É um estado calculado pelo scanner, não uma garantia nem uma recomendação.</p>
              </InfoPopover>
            </div>
            <strong :class="`direction-${getTrendBias(latestHistory).toLowerCase()}`">{{ getTrendBias(latestHistory) }}</strong>
            <small>Viés de EMAs · {{ contextTimeframe }}</small>
          </article>

          <div class="stage-connector" aria-hidden="true">→</div>

          <article class="market-stage">
            <div class="field-label">
              <span>2 · Setup</span>
              <InfoPopover title="Estado do setup">
                <p><strong>SETUP</strong> e <strong>NO_SETUP</strong> são estados produzidos pela classificação atual do scanner. WAIT resulta em NO_SETUP; um lado LONG/SHORT reconhecido resulta em SETUP.</p>
                <p>Como o cálculo atual também atribui ENTRY nesse mesmo caso, SETUP não é um filtro separado que antecede a entrada.</p>
              </InfoPopover>
            </div>
            <strong>{{ currentSetupState === 'SETUP' ? 'IDENTIFICADO' : currentSetupState === 'NO_SETUP' ? 'NÃO IDENTIFICADO' : currentSetupState }}</strong>
            <small>{{ currentSetupState }}</small>
          </article>

          <div class="stage-connector" aria-hidden="true">→</div>

          <article class="market-stage">
            <div class="field-label">
              <span>3 · Entrada</span>
              <InfoPopover title="Estado de entrada">
                <p>ENTRY é reconhecido quando o score do lado escolhido alcança o threshold ({{ scoreThreshold }}) e fica mais de 5 pontos acima do score oposto.</p>
                <p>Isso descreve a regra implementada no scanner. O estado não garante execução, acerto ou resultado financeiro.</p>
              </InfoPopover>
            </div>
            <strong>{{ currentEntryState === 'ENTRY' ? `ENTRY · ${currentDirection}` : currentEntryState }}</strong>
            <small>{{ entryGuidance }}</small>
          </article>
        </div>

        <div class="score-summary">
          <div class="field-label">
            <strong>Scores por direção</strong>
            <InfoPopover title="Score e threshold">
              <p>O score soma pontos dos componentes ativos de cada lado (LONG e SHORT), que avaliam tendência/EMAs, RSI, volume, Fibonacci, liquidez e estrutura. Os pontos e condições vêm do scanner.</p>
              <p>Threshold atual: {{ scoreThreshold }} pontos. A regra de entrada exige também que o score escolhido supere o oposto por mais de 5 pontos. Atingir o threshold não garante trade nem resultado.</p>
            </InfoPopover>
          </div>
          <div class="score-row">
            <div class="score-label-group">
              <span>LONG</span>
              <strong>{{ longScoreValue }} / {{ scoreThreshold }}</strong>
            </div>
            <div class="bar-track" role="meter" aria-label="Score LONG" :aria-valuenow="Math.min(longScoreValue, scoreThreshold)" :aria-valuemin="0" :aria-valuemax="scoreThreshold">
              <div class="bar long" :style="{ width: `${longPercent}%` }" />
            </div>
          </div>
          <div class="score-row">
            <div class="score-label-group">
              <span>SHORT</span>
              <strong>{{ shortScoreValue }} / {{ scoreThreshold }}</strong>
            </div>
            <div class="bar-track" role="meter" aria-label="Score SHORT" :aria-valuenow="Math.min(shortScoreValue, scoreThreshold)" :aria-valuemin="0" :aria-valuemax="scoreThreshold">
              <div class="bar short" :style="{ width: `${shortPercent}%` }" />
            </div>
          </div>
        </div>
      </section>

      <section class="indicator-grid" aria-label="Indicadores do último ciclo">
        <article class="indicator-card panel">
          <div class="field-label">
            <span>ATR · {{ triggerTimeframe }}</span>
            <InfoPopover title="ATR — Average True Range">
              <p>O ATR mede volatilidade, não direção. O valor é calculado com período 14 no timeframe de gatilho ({{ triggerTimeframe }}); valores maiores representam maior amplitude média recente, e menores, menor amplitude.</p>
              <p>O scanner usa ATR no limite do stop (1,2 ATR, respeitando também o mínimo de 0,2% do preço) e para medir a proximidade do nível Fibonacci. O alvo usa relação risco/retorno configurada em 2:1.</p>
              <p>ATR alto ou baixo não indica automaticamente compra, venda ou reversão.</p>
            </InfoPopover>
          </div>
          <strong>{{ formatNumber(latestHistory?.atr, 4) }}</strong>
          <small>Volatilidade média do ativo no período analisado.</small>
        </article>

        <article class="indicator-card panel">
          <div class="field-label">
            <span>RSI · {{ triggerTimeframe }}</span>
            <InfoPopover title="RSI — Relative Strength Index">
              <p>O RSI é um indicador de momentum em escala de 0 a 100, calculado pelo scanner com período 14 no timeframe {{ triggerTimeframe }}. Valores acima de 70 e abaixo de 30 são regiões tradicionalmente chamadas de sobrecompra e sobrevenda, mas não implicam reversão.</p>
              <p>Na pontuação atual, RSI 52–68 contribui para LONG (+12); RSI 32–48 para SHORT (+12); abaixo de 28 ativa componente extremo LONG (+6); acima de 72, extremo SHORT (+6). Essas condições não são, isoladamente, sinais de entrada.</p>
            </InfoPopover>
          </div>
          <strong>{{ formatNumber(latestHistory?.rsi, 2) }}</strong>
          <small>Momentum calculado no timeframe de gatilho.</small>
        </article>

        <article class="indicator-card panel">
          <div class="field-label">
            <span>Volume Ratio · {{ triggerTimeframe }}</span>
            <InfoPopover title="Volume Ratio">
              <p>Compara o volume do candle atual com a média móvel dos últimos 20 candles no timeframe {{ triggerTimeframe }}. 1,0 equivale à média; acima de 1,0 está acima da média; abaixo de 1,0 está abaixo.</p>
              <p>Para contribuir com +8, o scanner exige razão de pelo menos 1,2 e candle na direção do componente (alta para LONG, baixa para SHORT). É uma confirmação de volume, não uma entrada por si só.</p>
            </InfoPopover>
          </div>
          <strong>{{ formatNumber(latestHistory?.vol_ratio, 3) }}</strong>
          <small>Volume atual em relação à média móvel de 20 candles.</small>
        </article>
      </section>

      <section class="panel component-panel">
        <div class="section-head">
          <div class="section-title-wrap">
            <div class="field-label">
              <h2>Componentes do score</h2>
              <InfoPopover title="Configuração local dos componentes">
                <p>Os componentes representam condições técnicas calculadas pelo scanner e seus possíveis pontos para LONG ou SHORT. “Condição satisfeita” significa apenas que a condição específica está ativa no último registro disponível; não significa comprar ou vender.</p>
                <p>Os controles ON/OFF apenas mostram ou ocultam componentes nesta tela e neste navegador. Não mudam a estratégia, os pontos ou o scanner.</p>
                <p>Os pontos exibidos são do último ciclo. “Ativações no histórico” é a contagem agregada informada pela API e não representa o estado atual do componente.</p>
              </InfoPopover>
            </div>
            <span class="small-note">Estado do último ciclo · preferências visuais locais</span>
          </div>
        </div>

        <div v-if="visibleComponents.length" class="component-grid">
          <article v-for="item in visibleComponents" :key="item.name" class="component-card">
            <div class="component-card__heading">
              <div class="field-label">
                <strong>{{ getComponentLabel(item.name) }}</strong>
                <InfoPopover :title="getComponentLabel(item.name)">
                  <p>{{ componentInfo(item.name) }}</p>
                  <p>Quando ativa, a condição contribui com os pontos mostrados neste card para {{ item.name.startsWith('long_') ? 'LONG' : 'SHORT' }}. Não é recomendação automática de operação.</p>
                </InfoPopover>
              </div>
              <span class="component-direction" :class="item.name.startsWith('long_') ? 'direction-long' : 'direction-short'">
                {{ item.name.startsWith('long_') ? 'LONG' : 'SHORT' }}
              </span>
            </div>
            <div class="component-current">
              <span class="state-badge" :class="currentComponentActive(item.name) === true ? 'active' : 'inactive'">
                {{ currentComponentActive(item.name) === null ? 'Sem dado do ciclo' : currentComponentActive(item.name) ? '✓ Condição satisfeita' : '○ Condição não satisfeita' }}
              </span>
              <strong>{{ currentComponentActive(item.name) === null ? 'N/D' : `+${currentComponentActive(item.name) ? currentComponentPoints(item.name) ?? 0 : 0}` }}</strong>
            </div>
            <div class="component-card__meta">
              <span>Valor: {{ formatNumber(currentComponentValue(item.name), 4) }}</span>
              <span>{{ item.activation_count }} ativações no histórico</span>
            </div>
            <label class="component-toggle">
              <span>Exibir componente</span>
              <input
                type="checkbox"
                role="switch"
                :aria-label="`Exibir componente ${getComponentLabel(item.name)}`"
                :checked="isComponentEnabled(item.name)"
                @change="toggleComponent(item.name)"
              />
            </label>
          </article>
        </div>
        <p v-else class="small-note">Todos os componentes estão ocultos nesta visualização. Ative um filtro local para exibi-los.</p>
        <p v-if="!components.length" class="small-note">O histórico disponível não contém dados de componentes para exibir.</p>
      </section>

      <details class="panel secondary-panel history-panel" :open="historyExpanded" @toggle="syncHistoryExpanded">
        <summary>
          <span>Histórico de sinais</span>
          <span class="summary-meta">{{ history.length }} registros · {{ visibleHistory.length }} exibidos</span>
        </summary>
        <div class="secondary-content">
          <div class="section-head">
            <h2>Histórico recente</h2>
            <div class="history-actions">
              <button v-if="visibleCount > 5" class="load-more" type="button" @click="collapseHistory">Mostrar menos</button>
              <button v-if="visibleCount < history.length" class="load-more" type="button" @click="loadHistoryChunk(visibleCount + 20)">Carregar +20</button>
            </div>
          </div>
          <div class="filters" aria-label="Filtros de histórico">
            <button :class="historyFilter === 'ALL' ? 'filter active' : 'filter'" type="button" @click="historyFilter = 'ALL'">Todas</button>
            <button :class="historyFilter === 'LONG' ? 'filter active' : 'filter'" type="button" @click="historyFilter = 'LONG'">LONG</button>
            <button :class="historyFilter === 'SHORT' ? 'filter active' : 'filter'" type="button" @click="historyFilter = 'SHORT'">SHORT</button>
            <button :class="historyFilter === 'WAIT' ? 'filter active' : 'filter'" type="button" @click="historyFilter = 'WAIT'">WAIT</button>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Data/Hora</th>
                  <th>Preço</th>
                  <th>Tendência</th>
                  <th>LONG</th>
                  <th>SHORT</th>
                  <th>Setup</th>
                  <th>Entrada</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in visibleHistory" :key="`${row.timestamp}-${row.side ?? 'row'}`">
                  <td>{{ formatDate(row.timestamp) }}</td>
                  <td>{{ formatNumber(row.price_float ?? row.price, 2) }}</td>
                  <td>{{ getTrendBias(row) }}</td>
                  <td>{{ row.long_score ?? 'N/D' }}</td>
                  <td>{{ row.short_score ?? 'N/D' }}</td>
                  <td>{{ row.setup_state || 'N/D' }}</td>
                  <td>{{ row.entry_state || 'N/D' }}<template v-if="row.entry_state === 'ENTRY'"> · {{ getSignalSide(row) }}</template></td>
                </tr>
                <tr v-if="!visibleHistory.length">
                  <td colspan="7">Nenhum registro para o filtro atual.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </details>

      <details class="panel secondary-panel">
        <summary>
          <span>Entradas, avaliação e diagnóstico</span>
          <span class="summary-meta">{{ entries.length }} entradas · {{ status?.scanner_status || 'OFFLINE' }}</span>
        </summary>
        <div class="secondary-content">
          <section class="two-col">
            <div>
              <div class="section-head">
                <h2>Entradas reconhecidas</h2>
              </div>
              <div v-if="entries.length === 0">Nenhuma ENTRY registrada.</div>
              <div v-else class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Data/Hora</th>
                      <th>Direção</th>
                      <th>Preço</th>
                      <th>Score</th>
                      <th>RSI</th>
                      <th>ATR</th>
                      <th>Volume ratio</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in entries.slice(0, 12)" :key="`${row.timestamp}-${row.side ?? 'entry'}`">
                      <td>{{ formatDate(row.timestamp) }}</td>
                      <td>{{ getSignalSide(row) }}</td>
                      <td>{{ formatNumber(row.price_float ?? row.price, 2) }}</td>
                      <td>{{ row.score ?? row.score_int ?? 'N/D' }}</td>
                      <td>{{ formatNumber(row.rsi, 2) }}</td>
                      <td>{{ formatNumber(row.atr, 4) }}</td>
                      <td>{{ formatNumber(row.vol_ratio, 3) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div>
              <div class="section-head">
                <h2>Avaliação do sinal mais recente</h2>
              </div>
              <ul v-if="latestEvaluation" class="status-list">
                <li><span>Retorno após 1 candle</span><strong>{{ formatNumber(latestEvaluation?.ret_1, 4) }}</strong></li>
                <li><span>Retorno após 3 candles</span><strong>{{ formatNumber(latestEvaluation?.ret_3, 4) }}</strong></li>
                <li><span>Retorno após 5 candles</span><strong>{{ formatNumber(latestEvaluation?.ret_5, 4) }}</strong></li>
                <li><span>Retorno após 10 candles</span><strong>{{ formatNumber(latestEvaluation?.ret_10, 4) }}</strong></li>
                <li><span>MFE</span><strong>{{ formatNumber(latestEvaluation?.mfe, 4) }}</strong></li>
                <li><span>MAE</span><strong>{{ formatNumber(latestEvaluation?.mae, 4) }}</strong></li>
                <li><span>Resultado</span><strong>{{ latestEvaluation?.outcome || 'N/D' }}</strong></li>
              </ul>
              <div v-else>N/D</div>
            </div>
          </section>
          <section class="diagnostic-panel">
            <div class="section-head">
              <h2>Diagnóstico do scanner</h2>
            </div>
            <ul class="status-list">
              <li><span>Status</span><strong>{{ status?.scanner_status || 'OFFLINE' }}</strong></li>
              <li><span>Última atualização</span><strong>{{ formatDate(status?.last_update) }}</strong></li>
              <li><span>Total de sinais</span><strong>{{ status?.signals_total ?? 0 }}</strong></li>
              <li><span>Total de setups</span><strong>{{ status?.setup_total ?? 0 }}</strong></li>
              <li><span>Total de entradas</span><strong>{{ status?.entries_total ?? 0 }}</strong></li>
            </ul>
          </section>
        </div>
      </details>
    </main>
  </div>

  <div v-else class="loading-state">Verificando sessão...</div>
</template>

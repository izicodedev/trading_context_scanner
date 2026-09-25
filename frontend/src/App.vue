<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getAuthSession, getComponents, getEntries, getEvaluation, getHistory, getStatus, signOut } from './services/api'
import type { ComponentSummary, EvaluationRow, SignalRow, StatusPayload } from './types/api'
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
const scoreThreshold = 65
const visibleCount = ref(5)
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

const getTrendBias = (row: SignalRow | null | undefined) => {
  const trend = (row?.trend_bias ?? '').toString().trim().toUpperCase()
  return trend || 'N/D'
}

const getEntryState = (row: SignalRow | null | undefined) => {
  const state = (row?.entry_state ?? row?.side ?? '').toString().trim().toUpperCase()
  if (state === 'LONG' || state === 'SHORT') return state
  return 'WAIT'
}

const isSetupEnabled = (row: SignalRow | null | undefined) => {
  const state = (row?.setup_state ?? '').toString().trim().toUpperCase()
  return state === 'SETUP' || state === 'SIM' || state === 'YES'
}

const getComponentLabel = (name: string) => {
  return name
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
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

const longPercent = computed(() => Math.min(100, (longScoreValue.value / scoreThreshold) * 100))
const shortPercent = computed(() => Math.min(100, (shortScoreValue.value / scoreThreshold) * 100))

const currentTrendLabel = computed(() => {
  const trend = getTrendBias(latestHistory.value)
  if (trend === 'N/D') return 'Tendência: N/D'
  return `Tendência: ${trend}`
})

const currentSetupState = computed(() => {
  const row = latestHistory.value
  const setup = (row?.setup_state ?? '').toString().trim().toUpperCase()
  return setup === 'SETUP' || setup === 'SIM' || setup === 'YES'
})

const currentEntryState = computed(() => {
  const state = getEntryState(latestHistory.value)
  return state !== 'WAIT'
})

const visibleHistory = computed(() => {
  const rows = [...history.value]
  const filtered = historyFilter.value === 'ALL'
    ? rows
    : rows.filter((row) => normalizeSide(getEntryState(row) === 'WAIT' ? null : getEntryState(row)) === historyFilter.value)

  return filtered.slice(0, visibleCount.value)
})

const loadHistoryChunk = (nextCount: number) => {
  visibleCount.value = Math.min(Math.max(nextCount, 5), 200)
}

const collapseHistory = () => {
  visibleCount.value = 5
}

const alertEntry = computed(() => {
  const latestEntry = [...history.value].find((row) => {
    const state = getEntryState(row)
    return state === 'LONG' || state === 'SHORT'
  })

  if (!latestEntry) return null

  const direction = getEntryState(latestEntry)
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
    components: (components.value ?? [])
      .filter((component) => isComponentEnabled(component.name) && Number(component.points_total) > 0)
      .slice(0, 6)
      .map((component) => `${getComponentLabel(component.name)} (+${component.points_total})`),
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
        <h1>Dashboard</h1>
      </div>
      <div class="status-wrap">
        <span class="status-badge" :class="status?.scanner_status === 'ONLINE' ? 'online' : 'offline'">
          {{ status?.scanner_status || 'OFFLINE' }}
        </span>
        <div class="header-meta">
          <span>{{ status?.market || 'N/D' }}</span>
          <span>{{ status?.timeframe || 'N/D' }}</span>
          <span>Threshold: {{ status?.threshold ?? 'N/D' }}</span>
        </div>
        <button class="logout-button" type="button" @click="handleLogout">Encerrar sessão</button>
        <span v-if="authError" class="auth-error" role="alert">{{ authError }}</span>
      </div>
    </header>

    <main v-if="!isLoading" class="content">
      <section class="status-band panel">
        <div class="status-band__item">
          <span class="label">Tendência</span>
          <strong>{{ currentTrendLabel }}</strong>
          <small>Direção predominante do contexto maior. Não significa entrada.</small>
        </div>
        <div class="status-band__item">
          <span class="label">Score</span>
          <strong>{{ longScoreValue }}/{{ scoreThreshold }}</strong>
          <small>LONG / {{ scoreThreshold }}</small>
        </div>
        <div class="status-band__item">
          <span class="label">Setup</span>
          <strong>{{ currentSetupState ? 'SIM' : 'NÃO' }}</strong>
          <small>Condição ativa no último ciclo.</small>
        </div>
        <div class="status-band__item">
          <span class="label">Entrada</span>
          <strong>{{ currentEntryState ? 'SIM' : 'NÃO' }}</strong>
          <small>Presença de LONG/SHORT real.</small>
        </div>
      </section>

      <section v-if="alertEntry" class="alert-strip panel" aria-live="polite">
        <div class="alert-strip__title">🚨 NOVA ENTRADA</div>
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

      <section class="cards-grid" aria-label="Resumo do scanner">
        <article class="metric-card panel">
          <p class="label">Preço atual</p>
          <h2>{{ formatNumber(latestHistory?.price_float ?? latestHistory?.price ?? status?.price, 2) }}</h2>
          <small>Última atualização: {{ formatDate(status?.last_update || latestHistory?.timestamp) }}</small>
        </article>
        <article class="metric-card panel">
          <p class="label">LONG score</p>
          <h2>{{ longScoreValue }}</h2>
          <small>/ {{ scoreThreshold }}</small>
        </article>
        <article class="metric-card panel">
          <p class="label">SHORT score</p>
          <h2>{{ shortScoreValue }}</h2>
          <small>/ {{ scoreThreshold }}</small>
        </article>
        <article class="metric-card panel">
          <p class="label">Setup</p>
          <h2>{{ isSetupEnabled(latestHistory) ? 'SIM' : 'NÃO' }}</h2>
          <small>{{ latestHistory?.setup_state || 'UNSET' }}</small>
        </article>
        <article class="metric-card panel">
          <p class="label">Entrada</p>
          <h2>{{ getEntryState(latestHistory) }}</h2>
          <small>{{ latestHistory?.entry_state || 'NO_ENTRY' }}</small>
        </article>
        <article class="metric-card panel">
          <p class="label">ATR</p>
          <h2>{{ formatNumber(latestHistory?.atr, 4) }}</h2>
          <small>Indicador</small>
        </article>
        <article class="metric-card panel">
          <p class="label">RSI</p>
          <h2>{{ formatNumber(latestHistory?.rsi, 2) }}</h2>
          <small>Indicador</small>
        </article>
        <article class="metric-card panel">
          <p class="label">Volume ratio</p>
          <h2>{{ formatNumber(latestHistory?.vol_ratio, 3) }}</h2>
          <small>Indicador</small>
        </article>
      </section>

      <section class="score-panel panel">
        <div class="section-head">
          <h2>Score</h2>
        </div>
        <div class="score-row">
          <div class="score-label-group">
            <span>LONG</span>
            <strong>{{ longScoreValue }}/{{ scoreThreshold }}</strong>
          </div>
          <div class="bar-track">
            <div class="bar long" :style="{ width: `${longPercent}%` }" />
          </div>
        </div>
        <div class="score-row">
          <div class="score-label-group">
            <span>SHORT</span>
            <strong>{{ shortScoreValue }}/{{ scoreThreshold }}</strong>
          </div>
          <div class="bar-track">
            <div class="bar short" :style="{ width: `${shortPercent}%` }" />
          </div>
        </div>
      </section>

      <section class="panel component-panel">
        <div class="section-head">
          <h2>Configuração local</h2>
          <span class="small-note">A configuração é local neste navegador e não altera a estratégia do backend.</span>
        </div>

        <div class="component-layout">
          <div>
            <h3>LONG</h3>
            <ul class="component-list toggle-list">
              <li v-for="item in components.filter((component) => component.name.startsWith('long_'))" :key="item.name">
                <div class="component-title-wrap">
                  <strong>{{ getComponentLabel(item.name) }}</strong>
                  <span>{{ isComponentEnabled(item.name) ? 'ON' : 'OFF' }}</span>
                </div>
                <div class="switch-row">
                  <span class="state-badge" :class="item.activation_count > 0 ? 'active' : 'inactive'">
                    {{ item.activation_count > 0 ? '✓ Condição satisfeita' : '— Condição não satisfeita' }}
                  </span>
                  <label class="switch">
                    <input type="checkbox" :checked="isComponentEnabled(item.name)" @change="toggleComponent(item.name)" />
                    <span class="slider" />
                  </label>
                </div>
                <div class="component-points">Pontos: +{{ item.points_total }}</div>
              </li>
            </ul>
          </div>

          <div>
            <h3>SHORT</h3>
            <ul class="component-list toggle-list">
              <li v-for="item in components.filter((component) => component.name.startsWith('short_'))" :key="item.name">
                <div class="component-title-wrap">
                  <strong>{{ getComponentLabel(item.name) }}</strong>
                  <span>{{ isComponentEnabled(item.name) ? 'ON' : 'OFF' }}</span>
                </div>
                <div class="switch-row">
                  <span class="state-badge" :class="item.activation_count > 0 ? 'active' : 'inactive'">
                    {{ item.activation_count > 0 ? '✓ Condição satisfeita' : '— Condição não satisfeita' }}
                  </span>
                  <label class="switch">
                    <input type="checkbox" :checked="isComponentEnabled(item.name)" @change="toggleComponent(item.name)" />
                    <span class="slider" />
                  </label>
                </div>
                <div class="component-points">Pontos: +{{ item.points_total }}</div>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section class="panel table-panel">
        <div class="section-head">
          <h2>Histórico — {{ visibleHistory.length }} registros</h2>
          <div class="history-actions">
            <button v-if="visibleCount > 5" class="load-more" type="button" @click="collapseHistory">Recolher</button>
            <button class="load-more" type="button" @click="loadHistoryChunk(visibleCount + 20)">Carregar +20</button>
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
                <th>Score</th>
                <th>Setup</th>
                <th>Entrada</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in visibleHistory" :key="`${row.timestamp}-${row.side ?? 'row'}`">
                <td>{{ formatDate(row.timestamp) }}</td>
                <td>{{ formatNumber(row.price_float ?? row.price, 2) }}</td>
                <td>{{ getTrendBias(row) }}</td>
                <td>{{ row.long_score ?? row.short_score ?? 'N/D' }}</td>
                <td>{{ isSetupEnabled(row) ? 'SIM' : 'NÃO' }}</td>
                <td>{{ getEntryState(row) === 'WAIT' ? 'NÃO' : 'SIM' }}</td>
              </tr>
              <tr v-if="!visibleHistory.length">
                <td colspan="6">Nenhum registro para o filtro atual.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel two-col">
        <div>
          <div class="section-head">
            <h2>Entradas</h2>
          </div>
          <div v-if="entries.length === 0">Nenhuma ENTRY registrada.</div>
          <table v-else>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Direção</th>
                <th>Preço</th>
                <th>Score</th>
                <th>Threshold</th>
                <th>RSI</th>
                <th>ATR</th>
                <th>Volume</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in entries.slice(0, 12)" :key="`${row.timestamp}-${row.side ?? 'entry'}`">
                <td>{{ formatDate(row.timestamp) }}</td>
                <td>{{ row.side || 'N/D' }}</td>
                <td>{{ formatNumber(row.price_float ?? row.price, 2) }}</td>
                <td>{{ row.score ?? row.score_int ?? 'N/D' }}</td>
                <td>{{ scoreThreshold }}</td>
                <td>{{ formatNumber(row.rsi, 2) }}</td>
                <td>{{ formatNumber(row.atr, 4) }}</td>
                <td>{{ formatNumber(row.vol_ratio, 3) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div>
          <div class="section-head">
            <h2>Avaliação</h2>
          </div>
          <ul v-if="latestEvaluation" class="status-list">
            <li><span>Resultado 1 candle</span><strong>{{ formatNumber(latestEvaluation?.ret_1, 4) }}</strong></li>
            <li><span>Resultado 3 candles</span><strong>{{ formatNumber(latestEvaluation?.ret_3, 4) }}</strong></li>
            <li><span>Resultado 5 candles</span><strong>{{ formatNumber(latestEvaluation?.ret_5, 4) }}</strong></li>
            <li><span>Resultado 10 candles</span><strong>{{ formatNumber(latestEvaluation?.ret_10, 4) }}</strong></li>
            <li><span>MFE</span><strong>{{ formatNumber(latestEvaluation?.mfe, 4) }}</strong></li>
            <li><span>MAE</span><strong>{{ formatNumber(latestEvaluation?.mae, 4) }}</strong></li>
            <li><span>Outcome</span><strong>{{ latestEvaluation?.outcome || 'N/D' }}</strong></li>
          </ul>
          <div v-else>N/D</div>
        </div>
      </section>

      <section class="panel status-panel">
        <div class="section-head">
          <h2>Status do scanner</h2>
        </div>
        <ul class="status-list">
          <li><span>Status de scanner</span><strong>{{ status?.scanner_status || 'OFFLINE' }}</strong></li>
          <li><span>Última atualização</span><strong>{{ formatDate(status?.last_update) }}</strong></li>
          <li><span>Total de sinais</span><strong>{{ status?.signals_total ?? 0 }}</strong></li>
          <li><span>Total de setups</span><strong>{{ status?.setup_total ?? 0 }}</strong></li>
          <li><span>Total de entries</span><strong>{{ status?.entries_total ?? 0 }}</strong></li>
          <li><span>Último arquivo</span><strong>{{ formatDate(status?.last_file_update) }}</strong></li>
        </ul>
      </section>
    </main>
  </div>

  <div v-else class="loading-state">Verificando sessão...</div>
</template>

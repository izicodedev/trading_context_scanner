<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { getComponents, getEntries, getEvaluation, getHistory, getStatus } from './services/api'
import type { ComponentSummary, EvaluationRow, SignalRow, StatusPayload } from './types/api'

const status = ref<StatusPayload | null>(null)
const history = ref<SignalRow[]>([])
const components = ref<ComponentSummary[]>([])
const entries = ref<SignalRow[]>([])
const evaluation = ref<EvaluationRow[]>([])
const isLoading = ref(true)
const scoreThreshold = 65

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

const renderLineChart = (values: number[], color: string, width = 480, height = 180) => {
  if (!values.length) return ''
  const padding = 18
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const range = Math.max(max - min, 1)
  const points = values.map((value, index) => {
    const x = padding + (index / Math.max(values.length - 1, 1)) * (width - padding * 2)
    const y = height - padding - ((value - min) / range) * (height - padding * 2)
    return `${x},${y}`
  }).join(' ')

  return `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
      <polyline fill="none" stroke="${color}" stroke-width="2" points="${points}" />
    </svg>
  `
}

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
  } catch (error) {
    console.error('Erro ao carregar dados do dashboard', error)
  } finally {
    isLoading.value = false
  }
}

let intervalId: number | undefined

onMounted(() => {
  void loadData()
  intervalId = window.setInterval(() => {
    void loadData()
  }, 15000)
})

onBeforeUnmount(() => {
  if (intervalId) window.clearInterval(intervalId)
})

const latestHistory = () => history.value[0] ?? null
const latestEvaluation = () => evaluation.value[evaluation.value.length - 1] ?? null

const longScoreValue = () => toNumber((latestHistory()?.long_score as string | number | undefined) ?? status.value?.long_score) ?? 0
const shortScoreValue = () => toNumber((latestHistory()?.short_score as string | number | undefined) ?? status.value?.short_score) ?? 0

const longPercent = () => Math.min(100, (longScoreValue() / scoreThreshold) * 100)
const shortPercent = () => Math.min(100, (shortScoreValue() / scoreThreshold) * 100)

const charts = () => {
  const rows = [...history.value].slice().reverse()
  const priceValues = rows.map((row) => toNumber(row.price_float ?? row.price) ?? 0)
  const longValues = rows.map((row) => toNumber(row.long_score) ?? 0)
  const shortValues = rows.map((row) => toNumber(row.short_score) ?? 0)
  const rsiValues = rows.map((row) => toNumber(row.rsi) ?? 50)
  const volValues = rows.map((row) => toNumber(row.vol_ratio) ?? 1)

  return {
    price: renderLineChart(priceValues, '#60a5fa'),
    score: renderLineChart(longValues, '#22c55e') + renderLineChart(shortValues, '#ef4444'),
    rsi: renderLineChart(rsiValues, '#fbbf24'),
    vol: renderLineChart(volValues, '#a78bfa'),
  }
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Trading Context Scanner</p>
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
      </div>
    </header>

    <main v-if="!isLoading" class="content">
      <section class="cards-grid" aria-label="Resumo do scanner">
        <article class="metric-card panel">
          <p class="label">Preço atual</p>
          <h2>{{ formatNumber(latestHistory()?.price_float ?? latestHistory()?.price ?? status?.price, 2) }}</h2>
          <small>Última atualização: {{ formatDate(status?.last_update || latestHistory()?.timestamp) }}</small>
        </article>
        <article class="metric-card panel">
          <p class="label">LONG score</p>
          <h2>{{ longScoreValue() }}</h2>
          <small>/ {{ scoreThreshold }}</small>
        </article>
        <article class="metric-card panel">
          <p class="label">SHORT score</p>
          <h2>{{ shortScoreValue() }}</h2>
          <small>/ {{ scoreThreshold }}</small>
        </article>
        <article class="metric-card panel">
          <p class="label">Estado atual</p>
          <h2>{{ latestHistory()?.entry_state || status?.state || 'N/D' }}</h2>
          <small>{{ latestHistory()?.signal_state || status?.signal_state || 'N/D' }}</small>
        </article>
        <article class="metric-card panel">
          <p class="label">ATR</p>
          <h2>{{ formatNumber(latestHistory()?.atr, 4) }}</h2>
          <small>Indicador</small>
        </article>
        <article class="metric-card panel">
          <p class="label">RSI</p>
          <h2>{{ formatNumber(latestHistory()?.rsi, 2) }}</h2>
          <small>Indicador</small>
        </article>
        <article class="metric-card panel">
          <p class="label">Volume ratio</p>
          <h2>{{ formatNumber(latestHistory()?.vol_ratio, 3) }}</h2>
          <small>Indicador</small>
        </article>
        <article class="metric-card panel">
          <p class="label">Tendência</p>
          <h2>{{ latestHistory()?.trend_bias || 'N/D' }}</h2>
          <small>Bias</small>
        </article>
      </section>

      <section class="score-panel panel">
        <div class="section-head">
          <h2>Score</h2>
        </div>
        <div class="score-row">
          <div class="score-label-group">
            <span>LONG</span>
            <strong>{{ longScoreValue() }}/{{ scoreThreshold }}</strong>
          </div>
          <div class="bar-track">
            <div class="bar long" :style="{ width: `${longPercent()}%` }" />
          </div>
        </div>
        <div class="score-row">
          <div class="score-label-group">
            <span>SHORT</span>
            <strong>{{ shortScoreValue() }}/{{ scoreThreshold }}</strong>
          </div>
          <div class="bar-track">
            <div class="bar short" :style="{ width: `${shortPercent()}%` }" />
          </div>
        </div>
      </section>

      <section class="panel component-panel">
        <div class="section-head">
          <h2>Componentes do score</h2>
        </div>
        <div class="component-layout">
          <div>
            <h3>LONG</h3>
            <ul class="component-list">
              <li v-for="item in components.filter((component) => component.name.startsWith('long_'))" :key="item.name">
                <div>
                  <strong>{{ item.name }}</strong>
                  <span>{{ item.activation_count > 0 ? 'Ativo' : 'Inativo' }}</span>
                </div>
                <div>
                  <strong>{{ item.activation_count > 0 ? `+${item.points_total}` : '0' }}</strong>
                </div>
              </li>
              <li v-if="!components.some((component) => component.name.startsWith('long_'))">
                <span>N/D — dados de componentes não registrados pelo scanner.</span>
              </li>
            </ul>
          </div>
          <div>
            <h3>SHORT</h3>
            <ul class="component-list">
              <li v-for="item in components.filter((component) => component.name.startsWith('short_'))" :key="item.name">
                <div>
                  <strong>{{ item.name }}</strong>
                  <span>{{ item.activation_count > 0 ? 'Ativo' : 'Inativo' }}</span>
                </div>
                <div>
                  <strong>{{ item.activation_count > 0 ? `+${item.points_total}` : '0' }}</strong>
                </div>
              </li>
              <li v-if="!components.some((component) => component.name.startsWith('short_'))">
                <span>N/D — dados de componentes não registrados pelo scanner.</span>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section class="panel chart-panel">
        <div class="section-head">
          <h2>Gráficos</h2>
        </div>
        <div class="chart-grid">
          <div class="chart-box">
            <h3>Preço</h3>
            <div v-html="charts().price" />
          </div>
          <div class="chart-box">
            <h3>LONG / SHORT</h3>
            <div v-html="charts().score" />
          </div>
          <div class="chart-box">
            <h3>RSI</h3>
            <div v-html="charts().rsi" />
          </div>
          <div class="chart-box">
            <h3>Volume ratio</h3>
            <div v-html="charts().vol" />
          </div>
        </div>
      </section>

      <section class="panel table-panel">
        <div class="section-head">
          <h2>Histórico</h2>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Preço</th>
                <th>LONG</th>
                <th>SHORT</th>
                <th>Direção</th>
                <th>Signal</th>
                <th>Setup</th>
                <th>Entry</th>
                <th>RSI</th>
                <th>ATR</th>
                <th>Vol</th>
                <th>Trend</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in history.slice(0, 20)" :key="`${row.timestamp}-${row.side}`">
                <td>{{ formatDate(row.timestamp) }}</td>
                <td>{{ formatNumber(row.price_float ?? row.price, 2) }}</td>
                <td>{{ row.long_score ?? 'N/D' }}</td>
                <td>{{ row.short_score ?? 'N/D' }}</td>
                <td>{{ row.side || row.entry_state || 'WAIT' }}</td>
                <td><span class="badge signal">{{ row.signal_state || 'SIGNAL' }}</span></td>
                <td><span class="badge setup">{{ row.setup_state || 'UNSET' }}</span></td>
                <td><span class="badge entry">{{ row.entry_state || 'UNSET' }}</span></td>
                <td>{{ formatNumber(row.rsi, 2) }}</td>
                <td>{{ formatNumber(row.atr, 4) }}</td>
                <td>{{ formatNumber(row.vol_ratio, 3) }}</td>
                <td>{{ row.trend_bias || 'N/D' }}</td>
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
              <tr v-for="row in entries" :key="`${row.timestamp}-${row.side}`">
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
          <ul v-if="latestEvaluation()" class="status-list">
            <li><span>Resultado 1 candle</span><strong>{{ formatNumber(latestEvaluation()?.ret_1, 4) }}</strong></li>
            <li><span>Resultado 3 candles</span><strong>{{ formatNumber(latestEvaluation()?.ret_3, 4) }}</strong></li>
            <li><span>Resultado 5 candles</span><strong>{{ formatNumber(latestEvaluation()?.ret_5, 4) }}</strong></li>
            <li><span>Resultado 10 candles</span><strong>{{ formatNumber(latestEvaluation()?.ret_10, 4) }}</strong></li>
            <li><span>MFE</span><strong>{{ formatNumber(latestEvaluation()?.mfe, 4) }}</strong></li>
            <li><span>MAE</span><strong>{{ formatNumber(latestEvaluation()?.mae, 4) }}</strong></li>
            <li><span>Outcome</span><strong>{{ latestEvaluation()?.outcome || 'N/D' }}</strong></li>
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

    <div v-else class="loading-state">Carregando dados do scanner...</div>
  </div>
</template>

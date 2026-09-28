<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getLiveSimulation, setLiveSimulation, type LabStatus } from '../services/api'
import { strategyName } from '../services/strategyDisplay'

const state = ref<LabStatus | null>(null)
const busy = ref(false)
const loading = ref(true)
const error = ref('')
const now = ref(Date.now())
let polling: number | undefined
let fetching = false
let revision = 0
const number = (value: number | null | undefined, digits = 2) => value == null ? '—' : value.toLocaleString('pt-BR', { maximumFractionDigits: digits, minimumFractionDigits: digits })
const percent = (value: number | null | undefined) => value == null ? '—' : `${number(value)}%`
const date = (value?: string) => value ? new Date(value).toLocaleString('pt-BR') : '—'
const historical = (key: string) => state.value?.snapshot?.historical.find(item => item.strategy.key === key)
const sessionStrategies = computed(() => state.value?.snapshot ? state.value.strategies : [])
const live = (key: string) => state.value?.snapshot?.live.find(item => item.strategy.key === key)
const training = (key: string) => state.value?.snapshot?.research?.training.find(item => item.strategy.key === key)
const validation = (key: string) => state.value?.snapshot?.research?.validation.find(item => item.strategy.key === key)
const testedStrategies = computed(() => state.value?.snapshot?.research?.trials ?? [])
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
  try {
    const data = await getLiveSimulation()
    if (current === revision) { state.value = data; error.value = '' }
  } catch (reason) {
    if (current === revision) error.value = reason instanceof Error ? reason.message : 'Não foi possível consultar a simulação.'
  } finally { fetching = false; loading.value = false; now.value = Date.now() }
}
async function toggle() {
  if (busy.value) return
  busy.value = true; error.value = ''; revision++
  try { state.value = await setLiveSimulation(!state.value?.active) }
  catch (reason) { error.value = reason instanceof Error ? reason.message : 'Não foi possível atualizar a simulação.' }
  finally { busy.value = false; now.value = Date.now() }
}
onMounted(() => { void refresh(); polling = window.setInterval(() => { now.value = Date.now(); void refresh() }, 10000) })
onBeforeUnmount(() => { if (polling) window.clearInterval(polling); revision++ })
</script>

<template>
  <main class="sim-lab">
    <header class="sim-toolbar">
      <div>
        <p class="sim-label">BTCUSDT <span>·</span> 5 minutos <span>·</span> Paper trading</p>
        <h2>Estratégias da sessão</h2>
        <p class="sim-subtitle">Todas as estratégias acompanhadas nesta sessão, com resultados positivos e negativos.</p>
      </div>
      <div class="sim-controls">
        <span class="sim-status" :class="{ active: state?.active && !stale }"><i />{{ loading ? 'Carregando' : stale ? 'Dados atrasados' : state?.active ? 'Em execução' : 'Parada' }}</span>
        <button :disabled="busy || loading || !state" type="button" @click="toggle">{{ busy ? 'Processando…' : state?.active ? 'Parar simulação' : 'Ativar simulação' }}</button>
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
      <h3>Aguardando avaliação das estratégias</h3>
      <p>Ative a simulação para avaliar o histórico e acompanhar juntas as estratégias selecionadas.</p>
    </section>
    <p v-if="state?.snapshot" class="sim-caption">{{ sessionStrategies.length }} estratégias nesta sessão · {{ state.active ? 'Acompanhamento ativo' : 'Simulação parada — últimos resultados preservados' }}. Lucro histórico não garante lucro na sessão ao vivo.</p>
    <p class="sim-notice" v-if="state?.snapshot?.research">{{ state.snapshot.research.candidates_tested }} configurações comparadas nos primeiros 70% dos dados; os 30% seguintes foram reservados para avaliação. Amostra curta: nenhuma hipótese deve ser tratada como validada.</p>
    <section class="sim-details" v-if="state">
      <details>
        <summary>Todas as estratégias testadas <span>{{ testedStrategies.length }} configurações · {{ state.snapshot?.symbol ?? 'BTCUSDT' }}</span></summary>
        <div class="sim-detail-body sim-catalog">
          <p>Resultados desta pesquisa em {{ state.snapshot?.symbol ?? 'BTCUSDT' }} · {{ state.snapshot?.timeframe ?? '5m' }}. Inclui resultados negativos e positivos; uma estratégia pode ter comportamento diferente em outra moeda.</p>
          <p class="sim-muted">Todas foram comparadas na descoberta. Apenas as selecionadas passaram pela validação separada e pela simulação ao vivo. Retornos incluem os custos estimados.</p>
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
                <div><span>Retorno na validação</span><strong>{{ percent(validation(trial.strategy.key)?.total_return_pct) }}</strong></div>
                <div><span>Acerto na validação</span><strong>{{ percent(validation(trial.strategy.key)?.win_rate) }}</strong></div>
              </div>
              <p class="sim-muted">{{ validation(trial.strategy.key) ? `${assessment(trial.strategy.key)} · ${validation(trial.strategy.key)?.closed_trades} trades na validação` : 'Não selecionada para validação nesta pesquisa.' }}</p>
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
          <p>A seleção usa somente a descoberta, com preferência por amostra de pelo menos cinco trades e retorno descontado de uma penalidade de drawdown. A validação não escolhe os parâmetros. O acompanhamento ao vivo é o próximo teste.</p>
          <p>Três bancas independentes. Entrada no candle posterior ao sinal; stop primeiro quando o candle é ambíguo. Não somar retornos como se fossem uma carteira. Custos estimados: {{ number(state.configuration.fee_rate * 100, 3) }}% por execução, {{ number(state.configuration.slippage_rate * 100, 3) }}% de slippage e {{ number(state.configuration.hourly_funding_rate * 100, 5) }}% de funding por hora.</p>
          <p>Binance spot, liquidação aproximada; sem fills ou funding histórico da Hyperliquid. A meta de 5% não é uma previsão. Nenhuma ordem real é enviada.</p>
          <p>Ao parar, posições virtuais encerram no último fechamento. Reativar cria nova sessão; a anterior fica arquivada no banco. Os resultados continuam sendo processados com a página fechada.</p>
          <p class="sim-muted">Sessão iniciada: {{ date(state.started_at) }} · processamento: {{ date(state.heartbeat) }}</p>
        </div>
      </details>
    </section>
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
</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { LabStrategy } from '../services/api'
import { strategyName } from '../services/strategyDisplay'
const props = defineProps<{ network: string }>()
interface Run { active: boolean; managing: boolean; heartbeat: string | null; state: { phase: string; message: string; strategy: LabStrategy; quantity?: number; entry_price?: number; stop?: number; target?: number; daily_pnl?: number; entry_error?: { type: string; http_status?: number; response_code?: string; exchange_message?: string } } }
const data = ref<{ run: Run | null; mainnet_enabled: boolean; testnet_enabled: boolean } | null>(null)
const error = ref('')
const busy = ref(false)
const now = ref(Date.now())
let timer: number | undefined
const allowed = computed(() => props.network === 'mainnet' ? data.value?.mainnet_enabled : data.value?.testnet_enabled)
const stale = computed(() => data.value?.run?.managing && (!data.value.run.heartbeat || now.value - Date.parse(data.value.run.heartbeat) > 60000))
const status = computed(() => {
  if (!data.value) return 'Carregando'
  if (stale.value) return 'Processamento atrasado'
  if (data.value.run?.state.phase === 'submitting') return 'Entrada em verificação'
  if (data.value.run?.active) return 'Operando'
  if (data.value.run?.managing) return 'Gerenciando posição'
  return 'Parado'
})
const entryError = computed(() => {
  const diagnostic = data.value?.run?.state.entry_error
  if (!diagnostic || data.value?.run?.state.phase !== 'submitting') return ''
  if (diagnostic.exchange_message) return `Resposta da corretora: ${diagnostic.exchange_message}`
  if (diagnostic.response_code) return `Resposta da corretora sem confirmação (${diagnostic.response_code}).`
  if (['ConnectionError', 'ConnectTimeout', 'ReadTimeout', 'Timeout'].includes(diagnostic.type)) return 'Falha de rede durante o envio.'
  if (diagnostic.http_status) return `A API respondeu HTTP ${diagnostic.http_status} durante o envio.`
  return `Falha no envio: ${diagnostic.type}.`
})
const url = `${(import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')}/hyperliquid/execution`
async function request(active?: boolean) {
  if (busy.value) return
  busy.value = true
  try {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', ...(active === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-IziCrypto-Setup': '1' }, body: JSON.stringify({ active })
    }) })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error ?? 'Falha ao consultar execução.')
    data.value = result; error.value = ''
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'Falha na execução.' }
  finally { busy.value = false; now.value = Date.now() }
}
onMounted(() => { void request(); timer = window.setInterval(() => void request(), 10000) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>
<template>
  <section class="execution">
    <div class="execution-head"><span class="eyebrow">ROBÔ REAL · BTC</span><span class="status" :class="{ active: data?.run?.active && !stale, warning: stale }"><i />{{ status }}</span></div>
    <h2>{{ data?.run ? strategyName(data.run.state.strategy) : 'Nenhuma estratégia ativa' }}</h2>
    <p class="message">{{ data?.run?.state.message ?? 'Escolha uma estratégia e configure a carteira para começar.' }}</p>
    <p v-if="entryError" class="alert" role="alert">{{ entryError }}</p>
    <p v-if="data?.run?.managing" class="heartbeat">Último processamento: {{ data.run.heartbeat ? new Date(data.run.heartbeat).toLocaleString('pt-BR') : 'Aguardando worker' }}</p>
    <p v-if="stale" class="alert" role="alert">Processamento atrasado. Confira a posição e as proteções na Hyperliquid.</p>
    <div v-if="data?.run?.state.phase === 'open'" class="position"><div><span>Posição</span><strong>{{ data.run.state.quantity }} BTC</strong></div><div><span>Entrada</span><strong>{{ data.run.state.entry_price }}</strong></div><div><span>Stop</span><strong>{{ data.run.state.stop }}</strong></div><div><span>Alvo</span><strong>{{ data.run.state.target }}</strong></div></div>
    <div class="actions"><button v-if="data?.run?.active" class="stop" :disabled="busy" @click="request(false)">Parar novas entradas</button><button v-else :disabled="busy || !allowed || data?.run?.managing" @click="request(true)">Ativar estratégia</button><span v-if="data && !allowed">Execução nesta rede bloqueada no servidor</span><span v-else-if="data?.run?.managing && data.run.state.phase === 'submitting'">Entrada sem confirmação; nova ativação bloqueada até a conferência.</span><span v-else-if="data?.run?.managing && !data.run.active">A posição aberta continua sendo gerenciada</span></div>
    <p v-if="error" class="alert" role="alert">{{ error }}</p>
    <details><summary>Como funciona o controle</summary><p>Parar impede novas entradas. A gestão de uma posição já aberta continua, inclusive stop, alvo e prazo máximo. As regras ficam congeladas por sessão. Envios incertos exigem conferência na Hyperliquid.</p></details>
  </section>
</template>
<style scoped>
.execution { min-width: 0; padding: 28px; border: 1px solid #2b3d52; border-radius: 14px; background: #101f30; }
.execution-head,.actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }.eyebrow { color: #8ea1b7; letter-spacing: .12em; font-size: .68rem; font-weight: 700; }
.status { display: inline-flex; align-items: center; gap: 8px; padding: 7px 10px; border: 1px solid #34465b; border-radius: 999px; color: #b8c6d4; font-size: .73rem; white-space: nowrap; }.status i { width: 7px; height: 7px; border-radius: 50%; background: #92a1b0; }.status.active { color: #87d4b2; border-color: #326b55; background: #15392e; }.status.active i { background: #66d2a1; }.status.warning { color: #f5c583; border-color: #7c5b30; }.status.warning i { background: #f5c583; }
h2 { margin: 24px 0 10px; font-size: clamp(1.3rem, 2.5vw, 1.8rem); font-weight: 600; line-height: 1.3; letter-spacing: -.025em; }p { margin: 0; color: #a7b5c6; font-size: .83rem; line-height: 1.6; }.message { min-height: 2.6em; }.heartbeat { margin-top: 10px; color: #8193a9; font-size: .73rem; }
.position { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; border-top: 1px solid #2b3d52; margin-top: 20px; padding-top: 18px; }.position span { display: block; color: #8ea1b7; font-size: .68rem; }.position strong { display: block; margin-top: 6px; font-size: .85rem; font-weight: 600; }
.actions { justify-content: flex-start; margin-top: 26px; }.actions span { color: #8ea1b7; font-size: .75rem; }button { border: 0; border-radius: 8px; padding: 11px 18px; background: #dce8f3; color: #0a1928; font-size: .8rem; font-weight: 650; cursor: pointer; }button.stop { background: #283b4e; color: #e5edf7; }button:disabled { opacity: .45; cursor: not-allowed; }
.alert { margin-top: 12px; color: #f4a9a9; }details { margin-top: 24px; }summary { width: max-content; color: #8ea1b7; cursor: pointer; font-size: .75rem; }details p { margin-top: 12px; }button:focus-visible,summary:focus-visible { outline: 2px solid #93c5fd; outline-offset: 4px; }@media(max-width:650px) { .execution { padding: 20px; }.position { grid-template-columns: repeat(2, 1fr); } }
</style>

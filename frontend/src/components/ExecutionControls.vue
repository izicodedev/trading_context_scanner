<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { LabStrategy } from '../services/api'
import { strategyName } from '../services/strategyDisplay'
const props = defineProps<{ network: string }>()
interface Run { active: boolean; managing: boolean; heartbeat: string | null; state: { phase: string; message: string; strategy: LabStrategy; quantity?: number; entry_price?: number; stop?: number; target?: number; daily_pnl?: number } }
const data = ref<{ run: Run | null; mainnet_enabled: boolean; testnet_enabled: boolean } | null>(null)
const error = ref('')
const busy = ref(false)
const now = ref(Date.now())
let timer: number | undefined
const allowed = computed(() => props.network === 'mainnet' ? data.value?.mainnet_enabled : data.value?.testnet_enabled)
const stale = computed(() => data.value?.run?.managing && (!data.value.run.heartbeat || now.value - Date.parse(data.value.run.heartbeat) > 60000))
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
    <h3>Execução automática</h3>
    <p v-if="data?.run"><strong>{{ data.run.active ? 'Novas entradas habilitadas' : 'Novas entradas paradas' }}</strong> · {{ strategyName(data.run.state.strategy) }}</p>
    <p v-else>Nenhuma estratégia em execução.</p>
    <p v-if="data?.run">{{ data.run.state.message }}<br />Último processamento: {{ data.run.heartbeat ? new Date(data.run.heartbeat).toLocaleString('pt-BR') : 'Aguardando worker' }}</p>
    <p v-if="stale" role="alert">Processamento atrasado ou worker ausente. Confira a posição e as proteções na Hyperliquid.</p>
    <p v-if="data?.run?.state.phase === 'open'">Quantidade {{ data.run.state.quantity }} BTC · entrada {{ data.run.state.entry_price }} · stop {{ data.run.state.stop }} · alvo {{ data.run.state.target }}</p>
    <p v-if="data && !allowed">O envio de ordens nesta rede está bloqueado na configuração do servidor.</p>
    <button v-if="data?.run?.active" :disabled="busy" @click="request(false)">Parar novas entradas</button>
    <button v-else :disabled="busy || !allowed || data?.run?.managing" @click="request(true)">Ativar estratégia {{ network === 'mainnet' ? 'na conta real' : 'na testnet' }}</button>
    <p>Parar impede novas entradas. A gestão de uma posição já aberta continua, inclusive stop, alvo e prazo máximo. As regras ficam congeladas por sessão. Envios incertos são reconciliados sem repetir a entrada; se a confirmação continuar indisponível, confira a conta na Hyperliquid.</p>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.execution { border: 1px solid #455468; padding: 20px; border-radius: 8px; margin: 20px 0; }p { color: #94a3b8; font-size: .85rem; line-height: 1.7; }button { padding: 12px 16px; border-radius: 6px; border: 0; cursor: pointer; }button:disabled { opacity: .5; cursor: not-allowed; }[role=alert] { color: #f2b3b3; }
</style>

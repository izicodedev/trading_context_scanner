<script setup lang="ts">
import { onMounted, ref } from 'vue'

interface Limits { sizing_mode: 'fixed' | 'available_balance'; capital_usdc: string | null; margin_per_trade_usdc: string | null; max_leverage: string; daily_loss_usdc: string }
interface Setup { agent_address: string | null; agent_valid_until: number | null; risk_limits: Limits | null }
const limits = ref<Limits>({ sizing_mode: 'fixed', capital_usdc: '', margin_per_trade_usdc: '', max_leverage: '', daily_loss_usdc: '' })
const saved = ref<Setup | null>(null)
const privateKey = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')
const emit = defineEmits<{ configured: [setup: Setup] }>()
const url = `${(import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')}/hyperliquid/setup`
async function load() {
  busy.value = true
  try {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' })
    const data = await response.json()
    if (!response.ok) throw new Error(data.error ?? 'Falha ao consultar configuração.')
    saved.value = data
    if (data.risk_limits) limits.value = { ...data.risk_limits }
    emit('configured', data)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'Falha ao consultar configuração.' }
  finally { busy.value = false }
}
async function save() {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const response = await fetch(url, { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-IziCrypto-Setup': '1' },
      body: JSON.stringify({ limits: limits.value, ...(privateKey.value ? { private_key: privateKey.value.trim() } : {}) }) })
    const data = await response.json()
    if (!response.ok) throw new Error(data.error ?? 'Não foi possível salvar.')
    saved.value = data; emit('configured', data)
    notice.value = 'Configuração salva para a próxima sessão. A sessão em andamento mantém os limites definidos na ativação.'
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'Não foi possível salvar.' }
  finally { privateKey.value = ''; busy.value = false }
}
onMounted(load)
</script>

<template>
  <section class="setup-panel">
    <h3>Carteira de API e limites</h3>
    <p v-if="saved?.agent_address">Carteira de API cadastrada: <strong>{{ saved.agent_address }}</strong><br />Autorização verificada no cadastro · validade {{ saved.agent_valid_until ? new Date(saved.agent_valid_until).toLocaleString('pt-BR') : '—' }}.</p>
    <p v-else>Cadastre somente a chave da carteira de API izicrypto. Nunca use a chave da carteira principal ou seed phrase.</p>
    <form @submit.prevent="save">
      <label>Chave privada da carteira de API {{ saved?.agent_address ? '(deixe em branco para manter)' : '(opcional para salvar apenas limites)' }}
        <input v-model="privateKey" type="password" autocomplete="new-password" spellcheck="false" :disabled="busy" placeholder="Chave de API · não será exibida novamente" maxlength="66" />
      </label>
      <p>A chave é criptografada no servidor e sua autorização é consultada na Hyperliquid ao cadastrar. O campo é limpo após cada tentativa.</p>
      <label>Valor de cada entrada<select v-model="limits.sizing_mode" :disabled="busy"><option value="fixed">Margem fixa por entrada</option><option value="available_balance">Usar 100% da margem disponível</option></select></label>
      <p v-if="limits.sizing_mode === 'available_balance'">Recalcular a cada entrada com a margem livre atual, descontando a reserva necessária para taxas e execução. Lucros aumentam a próxima entrada; perdas a reduzem. Posições e ordens existentes consomem margem. Este modo não mantém um teto fixo de capital.</p>
      <div class="setup-grid">
        <template v-if="limits.sizing_mode === 'fixed'"><label>Capital máximo (USDC)<input v-model="limits.capital_usdc" type="number" step="0.01" min="0.01" required :disabled="busy" /></label><label>Margem por entrada (USDC)<input v-model="limits.margin_per_trade_usdc" type="number" step="0.01" min="0.01" required :disabled="busy" /></label></template>
        <label>Alavancagem máxima<input v-model="limits.max_leverage" type="number" min="1" max="40" step="1" required :disabled="busy" /></label>
        <label>Limite de perda diária (USDC)<input v-model="limits.daily_loss_usdc" type="number" min="0.01" step="0.01" required :disabled="busy" /></label>
      </div>
      <p>Os limites são fixados ao ativar cada sessão. Alterações salvas aqui valem para a próxima sessão. O limite diário bloqueia novas entradas e não garante um valor máximo de perda em posições abertas.</p>
      <button :disabled="busy" type="submit">{{ busy ? 'Verificando…' : 'Salvar carteira e limites' }}</button>
    </form>
    <p v-if="saved?.risk_limits">Modo salvo: <strong>{{ saved.risk_limits.sizing_mode === 'available_balance' ? '100% da margem disponível · saldo dinâmico' : 'Margem fixa' }}</strong> · alavancagem máxima {{ saved.risk_limits.max_leverage }}× · perda diária {{ saved.risk_limits.daily_loss_usdc }} USDC.</p>
    <p v-if="error" role="alert" class="setup-error">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
  </section>
</template>

<style scoped>
.setup-panel { padding: 24px; border: 1px solid #233044; border-radius: 10px; background: #0d1929; overflow-wrap: anywhere; }h3 { margin: 0 0 16px; }p { color: #94a3b8; font-size: .85rem; line-height: 1.7; }form,label { display: grid; gap: 10px; }form { gap: 16px; }label { font-size: .85rem; }input,select { min-width: 0; width: 100%; padding: 12px; border: 1px solid #455468; border-radius: 6px; color: #dce4ee; background: #101e30; }.setup-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }button { justify-self: start; padding: 12px 16px; border: 0; border-radius: 6px; cursor: pointer; background: #e4ebf4; color: #142032; }button:disabled { opacity: .5; }.setup-error { color: #f2b3b3; }@media(max-width:600px) { .setup-grid { grid-template-columns: 1fr; } }
</style>

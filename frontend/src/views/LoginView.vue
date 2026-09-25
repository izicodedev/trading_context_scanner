<script setup lang="ts">
import { ref } from 'vue'
import { signIn } from '../services/api'

const emit = defineEmits<{ authenticated: [] }>()
const login = ref('')
const password = ref('')
const isSubmitting = ref(false)
const errorMessage = ref('')

const submitLogin = async () => {
  if (isSubmitting.value) return
  isSubmitting.value = true
  errorMessage.value = ''
  try {
    await signIn(login.value.trim(), password.value)
    password.value = ''
    emit('authenticated')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Não foi possível entrar. Tente novamente.'
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-layout" aria-label="Acesso IziCrypto">
      <div class="login-intro">
        <a class="brand" href="/" aria-label="IziCrypto — página inicial">
          <span class="brand-mark" aria-hidden="true">I</span>
          <span>IziCrypto</span>
        </a>

        <div class="intro-copy">
          <p class="login-eyebrow">Análise de criptoativos</p>
          <h1>Contexto para decisões mais conscientes.</h1>
          <p class="login-description">
            Análise inteligente de mercado e estratégias de criptoativos
          </p>
        </div>

        <div class="product-summary">
          <div class="market-symbol">
            <span class="market-indicator" aria-hidden="true" />
            <strong>BTCUSDT</strong>
            <span>1h / 15m / 5m</span>
          </div>
          <ul class="product-features">
            <li><span aria-hidden="true">⌁</span> Scanner de mercado</li>
            <li><span aria-hidden="true">◫</span> Indicadores técnicos</li>
            <li><span aria-hidden="true">◇</span> Estratégias personalizáveis</li>
          </ul>
          <p class="analysis-note">Ferramenta de análise. Não garante resultados financeiros.</p>
        </div>
      </div>

      <div class="login-card">
        <div class="login-card-heading">
          <p class="login-eyebrow">Área do produto</p>
          <h2>Entrar na sua conta</h2>
          <p>Informe seus dados para continuar.</p>
        </div>

        <form class="login-form" @submit.prevent="submitLogin">
          <label for="login-email">E-mail ou login</label>
          <input
            id="login-email"
            v-model="login"
            type="text"
            name="login"
            autocomplete="username"
            required
            maxlength="254"
            placeholder="E-mail ou nome de usuário"
          />

          <div class="password-label-row">
            <label for="login-password">Senha</label>
            <button class="text-link" type="button">Esqueci minha senha</button>
          </div>
          <input
            id="login-password"
            v-model="password"
            type="password"
            name="password"
            autocomplete="current-password"
            required
            placeholder="Sua senha"
          />

          <button class="login-submit" type="submit" :disabled="isSubmitting">
            {{ isSubmitting ? 'Entrando...' : 'Entrar' }}
          </button>
          <p v-if="errorMessage" class="login-error" role="alert">
            {{ errorMessage }}
          </p>
        </form>

        <p class="signup-prompt">
          Ainda não tem conta?
          <button class="text-link" type="button">Criar conta</button>
        </p>
      </div>
    </section>
    <footer class="login-footer">© IziCrypto · Plataforma de análise de criptoativos</footer>
  </main>
</template>

<style scoped>
.login-page {
  --login-bg: #08111f;
  --login-panel: rgba(16, 29, 47, 0.88);
  --login-border: rgba(148, 163, 184, 0.18);
  --login-muted: #9aa9be;
  --login-text: #edf3fb;
  --login-accent: #68aafa;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 48px 24px 24px;
  color: var(--login-text);
  background:
    radial-gradient(ellipse at 16% 20%, rgba(37, 99, 160, 0.19), transparent 36rem),
    linear-gradient(145deg, #07111e, #0c192b 58%, #0a1422);
}

.login-layout {
  width: min(1040px, 100%);
  margin: auto;
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(330px, 0.8fr);
  align-items: center;
  gap: clamp(40px, 8vw, 112px);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 11px;
  color: var(--login-text);
  font-size: 1.3rem;
  font-weight: 750;
  letter-spacing: -0.04em;
  text-decoration: none;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 11px;
  color: #061322;
  background: linear-gradient(145deg, #86c1ff, #4c93ea);
  font-weight: 900;
}

.intro-copy {
  margin-top: clamp(52px, 9vh, 92px);
  max-width: 500px;
}

.login-eyebrow {
  margin: 0 0 14px;
  color: var(--login-accent);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.intro-copy h1 {
  max-width: 520px;
  margin: 0;
  font-size: clamp(2.35rem, 5.2vw, 4.2rem);
  line-height: 1.08;
  letter-spacing: -0.055em;
}

.login-description {
  max-width: 410px;
  margin: 20px 0 0;
  color: var(--login-muted);
  font-size: 1.05rem;
  line-height: 1.7;
}

.product-summary {
  margin-top: clamp(42px, 8vh, 76px);
}

.market-symbol {
  display: flex;
  align-items: center;
  gap: 10px;
  width: fit-content;
  padding: 10px 13px;
  border: 1px solid var(--login-border);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.035);
  font-size: 0.82rem;
}

.market-symbol span:last-child {
  margin-left: 4px;
  color: var(--login-muted);
}

.market-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #59d79a;
  box-shadow: 0 0 12px rgba(89, 215, 154, 0.55);
}

.product-features {
  display: flex;
  flex-wrap: wrap;
  gap: 13px 22px;
  margin: 22px 0 0;
  padding: 0;
  color: #c3cede;
  list-style: none;
  font-size: 0.82rem;
}

.product-features li {
  display: flex;
  align-items: center;
  gap: 7px;
}

.product-features li span {
  color: var(--login-accent);
  font-size: 1rem;
}

.analysis-note {
  margin: 22px 0 0;
  color: #8494aa;
  font-size: 0.72rem;
}

.login-card {
  padding: clamp(26px, 4vw, 38px);
  border: 1px solid var(--login-border);
  border-radius: 20px;
  background: var(--login-panel);
  box-shadow: 0 28px 80px rgba(0, 0, 0, 0.28);
  backdrop-filter: blur(14px);
}

.login-card-heading h2 {
  margin: 0;
  font-size: 1.65rem;
  letter-spacing: -0.035em;
}

.login-card-heading > p:last-child {
  margin: 9px 0 0;
  color: var(--login-muted);
  font-size: 0.88rem;
}

.login-form {
  display: flex;
  flex-direction: column;
  margin-top: 29px;
}

.login-form label {
  margin: 0 0 8px;
  color: #dce5f1;
  font-size: 0.82rem;
  font-weight: 600;
}

.login-form input {
  width: 100%;
  min-height: 48px;
  padding: 0 13px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 10px;
  outline: none;
  color: var(--login-text);
  background: rgba(4, 12, 22, 0.48);
  font-size: 0.88rem;
  transition: border-color 140ms ease, box-shadow 140ms ease;
}

.login-form input::placeholder {
  color: #708097;
}

.login-form input:focus {
  border-color: var(--login-accent);
  box-shadow: 0 0 0 3px rgba(104, 170, 250, 0.16);
}

.password-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 19px;
}

.password-label-row label {
  margin-bottom: 8px;
}

.text-link {
  padding: 0;
  border: 0;
  color: #84baff;
  background: transparent;
  font-size: 0.78rem;
  text-decoration: none;
  cursor: pointer;
}

.text-link:hover {
  color: #b2d4ff;
  text-decoration: underline;
}

.login-submit {
  min-height: 48px;
  margin-top: 23px;
  border: 0;
  border-radius: 10px;
  color: #061322;
  background: linear-gradient(105deg, #80bdff, #5599ed);
  font-size: 0.9rem;
  font-weight: 750;
  cursor: pointer;
  transition: filter 140ms ease, transform 140ms ease;
}

.login-submit:hover {
  filter: brightness(1.07);
}

.login-submit:disabled {
  cursor: wait;
  filter: saturate(0.7);
  opacity: 0.75;
}

.login-submit:active {
  transform: translateY(1px);
}

.login-submit:focus-visible,
.text-link:focus-visible,
.brand:focus-visible {
  outline: 3px solid rgba(132, 186, 255, 0.65);
  outline-offset: 3px;
}

.login-error {
  margin: 13px 0 0;
  color: #fca5a5;
  font-size: 0.72rem;
  line-height: 1.5;
  text-align: center;
}

.signup-prompt {
  margin: 22px 0 0;
  padding-top: 20px;
  border-top: 1px solid var(--login-border);
  color: var(--login-muted);
  font-size: 0.8rem;
  text-align: center;
}

.signup-prompt .text-link {
  margin-left: 4px;
  font-weight: 650;
}

.login-footer {
  width: min(1040px, 100%);
  margin: 36px auto 0;
  color: #74849a;
  font-size: 0.7rem;
  text-align: center;
}

@media (max-width: 760px) {
  .login-page {
    padding: 30px 18px 20px;
  }

  .login-layout {
    max-width: 440px;
    grid-template-columns: 1fr;
    gap: 34px;
  }

  .intro-copy {
    margin-top: 36px;
  }

  .intro-copy h1 {
    font-size: clamp(2.15rem, 10vw, 3.25rem);
  }

  .product-summary {
    margin-top: 25px;
  }

  .product-features {
    gap: 10px 16px;
  }

  .login-card {
    padding: 25px 22px;
  }
}

@media (max-width: 380px) {
  .market-symbol {
    gap: 7px;
    font-size: 0.74rem;
  }

  .product-features {
    flex-direction: column;
  }
}
</style>

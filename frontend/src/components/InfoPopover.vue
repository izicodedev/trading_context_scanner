<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

defineProps<{
  title: string
  label?: string
}>()

const isOpen = ref(false)
const container = ref<HTMLElement | null>(null)

const closeOnOutsideClick = (event: PointerEvent) => {
  if (event.target instanceof Node && !container.value?.contains(event.target)) {
    isOpen.value = false
  }
}

const closeOnEscape = (event: KeyboardEvent) => {
  if (event.key === 'Escape') isOpen.value = false
}

onMounted(() => {
  document.addEventListener('pointerdown', closeOnOutsideClick)
  document.addEventListener('keydown', closeOnEscape)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', closeOnOutsideClick)
  document.removeEventListener('keydown', closeOnEscape)
})
</script>

<template>
  <span ref="container" class="info-popover">
    <button
      class="info-popover__trigger"
      type="button"
      :aria-label="label || `Informações sobre ${title}`"
      :aria-expanded="isOpen"
      @click="isOpen = !isOpen"
    >
      <span aria-hidden="true">i</span>
    </button>

    <div v-if="isOpen" class="info-popover__panel" role="dialog" :aria-label="title">
      <div class="info-popover__heading">
        <strong>{{ title }}</strong>
        <button
          class="info-popover__close"
          type="button"
          :aria-label="`Fechar informações sobre ${title}`"
          @click="isOpen = false"
        >
          ×
        </button>
      </div>
      <div class="info-popover__content">
        <slot />
      </div>
    </div>
  </span>
</template>

<style scoped>
.info-popover {
  position: relative;
  display: inline-flex;
  vertical-align: middle;
}

.info-popover__trigger,
.info-popover__close {
  display: inline-grid;
  place-items: center;
  border: 1px solid rgba(148, 163, 184, 0.3);
  color: #a9bdd5;
  background: rgba(148, 163, 184, 0.08);
  cursor: pointer;
}

.info-popover__trigger {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  font-size: 0.72rem;
  font-weight: 800;
  line-height: 1;
}

.info-popover__trigger:hover,
.info-popover__trigger:focus-visible,
.info-popover__close:hover,
.info-popover__close:focus-visible {
  color: #eff6ff;
  border-color: rgba(96, 165, 250, 0.75);
  outline: none;
}

.info-popover__panel {
  position: absolute;
  z-index: 20;
  top: calc(100% + 9px);
  right: 0;
  width: min(320px, calc(100vw - 40px));
  padding: 13px 14px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 12px;
  color: #e5edf7;
  background: #102035;
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.38);
}

.info-popover__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 0.84rem;
}

.info-popover__close {
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
  border-radius: 6px;
  font-size: 1rem;
  line-height: 1;
}

.info-popover__content {
  color: #b8c6d8;
  font-size: 0.76rem;
  line-height: 1.55;
}

.info-popover__content :deep(p) {
  margin: 0 0 8px;
}

.info-popover__content :deep(p:last-child) {
  margin-bottom: 0;
}
</style>

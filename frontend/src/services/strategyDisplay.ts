import type { LabStrategy } from './api'

export function strategyName(strategy: LabStrategy): string {
  const suffix = strategy.key.split('_').at(-1) ?? ''
  const version = /^\d+$/.test(suffix) ? ` · V${Number(suffix) + 1}` : ''
  const format = (value: number) => value.toLocaleString('pt-BR', { maximumFractionDigits: 2 })
  return `${strategy.name}${version} · stop ${format(strategy.stop_floor * 100)}% · alvo ${format(strategy.reward_risk)}R · ${format(strategy.max_candles * 5 / 60)}h`
}

import type {
  ComponentSummary,
  EvaluationRow,
  SignalRow,
  StatusPayload,
  SummaryPayload,
} from '../types/api';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '');

export interface AuthSessionPayload {
  authenticated: boolean;
  user?: {
    id: number;
    name: string;
    login: string;
    role: 'MASTER' | 'USER';
  };
}

function resolveUrl(path: string): string {
  return `${API_BASE}${path}`;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(resolveUrl(path), { credentials: 'same-origin' });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: string } | null;
    throw new Error(payload?.error ?? `Não foi possível consultar o serviço (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(resolveUrl(path), {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  const payload = await response.json().catch(() => null) as { error?: string } | null;
  if (!response.ok) {
    throw new Error(payload?.error ?? `Request failed: ${path} (${response.status})`);
  }
  return payload as T;
}

export function getAuthSession(): Promise<AuthSessionPayload> {
  return getJson<AuthSessionPayload>('/auth/session');
}

export function signIn(login: string, password: string): Promise<{ user: NonNullable<AuthSessionPayload['user']> }> {
  return postJson('/auth/login', { login, password });
}

export function signOut(): Promise<void> {
  return postJson<void>('/auth/logout');
}

export type MarketSymbol = 'BTCUSDT' | 'ETHUSDT';
export interface MarketSelection { symbol: MarketSymbol; available_symbols: MarketSymbol[] }
export const getMarketSelection = () => getJson<MarketSelection>('/market/selection');
export const saveMarketSelection = (symbol: MarketSymbol) => postJson<MarketSelection>('/market/selection', { symbol });

export function getStatus(symbol: MarketSymbol = 'BTCUSDT'): Promise<StatusPayload> {
  return getJson<StatusPayload>(`/status?symbol=${symbol}`);
}

export function getHistory(limit = 200, symbol: MarketSymbol = 'BTCUSDT'): Promise<SignalRow[]> {
  return getJson<SignalRow[]>(`/history?limit=${limit}&symbol=${symbol}`);
}

export function getComponents(symbol: MarketSymbol = 'BTCUSDT'): Promise<ComponentSummary[]> {
  return getJson<ComponentSummary[]>(`/components?symbol=${symbol}`);
}

export function getEntries(symbol: MarketSymbol = 'BTCUSDT'): Promise<SignalRow[]> {
  return getJson<SignalRow[]>(`/entries?symbol=${symbol}`);
}

export function getEvaluation(symbol: MarketSymbol = 'BTCUSDT'): Promise<EvaluationRow[]> {
  return getJson<EvaluationRow[]>(`/evaluation?symbol=${symbol}`);
}

export function getSummary(): Promise<SummaryPayload> {
  return getJson<SummaryPayload>('/summary');
}

export interface SimulationResult {
  data_source: 'database' | 'manual';
  candles_loaded: number;
  status: 'TARGET' | 'STOP' | 'AMBIGUOUS' | 'TIMEOUT' | 'INSUFFICIENT_DATA';
  entry_price: number;
  exit_price: number | null;
  entry_time: string;
  exit_time: string | null;
  price_return_pct: number | null;
  duration_seconds: number | null;
  candles_held: number;
  ambiguous: boolean;
  ambiguity_policy: string;
  exit_time_basis: string | null;
}

export function simulateTrade(payload: unknown): Promise<SimulationResult> {
  return postJson<SimulationResult>('/simulator', payload);
}

export interface CandleDataset {
  source: string;
  symbol: string;
  timeframe: string;
  candles: number;
  start_time: string;
  end_time: string;
  first_open: number;
}

export function getCandleDatasets(): Promise<CandleDataset[]> {
  return getJson<CandleDataset[]>('/simulator/datasets');
}

export interface LabStrategy {
  key: string; name: string; description: string; leverage: number;
  stop_floor: number; atr_multiple: number; reward_risk: number; max_candles: number; threshold?: number;
  entry_rule?: string | null; direction?: 'BOTH' | 'LONG' | 'SHORT'; ema_filter?: boolean;
  volume_min?: number; rsi_lower?: number; rsi_upper?: number;
  entry_triggers?: string[] | null; trigger_mode?: 'ANY' | 'ALL'; entry_filters?: string[] | null;
}
export interface CustomStrategyInput {
  name: string; entry_rule: 'rule_builder'; entry_triggers: string[];
  trigger_mode: 'ANY' | 'ALL'; entry_filters: string[];
  direction: 'BOTH' | 'LONG' | 'SHORT'; volume_min: number;
  rsi_lower: number; rsi_upper: number; leverage: number; stop_pct: number;
  atr_multiple: number; reward_risk: number; max_candles: number;
}
export interface SimulationCatalog { strategies: LabStrategy[]; selected_keys: string[] }
export const getSimulationCatalog = (symbol: MarketSymbol = 'BTCUSDT') => getJson<SimulationCatalog>(`/simulator/strategies?symbol=${symbol}`);
export const createSimulationStrategy = (strategy: CustomStrategyInput) => postJson<LabStrategy>('/simulator/strategies', strategy);
export const saveSimulationSelection = (strategy_keys: string[], symbol: MarketSymbol = 'BTCUSDT') => postJson<{ selected_keys: string[] }>('/simulator/selection', { strategy_keys, symbol });
export interface LabTrade {
  side: string; entry_time: string; entry_price: number; stop_price: number;
  target_price: number; margin: number; quantity: number; candles_held: number;
  exit_time?: string; exit_price?: number; net_pnl?: number; estimated_net_pnl?: number;
  status?: string; ambiguous?: boolean;
}
export interface LabMetrics {
  strategy: LabStrategy; closed_trades: number; wins: number; losses: number;
  win_rate: number | null; net_pnl: number; equity: number; balance: number;
  total_return_pct: number; expectancy: number | null; profit_factor: number | null;
  max_drawdown_pct: number; max_consecutive_losses: number;
  fees: number; funding: number; slippage: number;
  daily: { day: string; return_pct: number | null; partial: boolean }[];
  open_position: LabTrade | null; recent_trades: LabTrade[];
  curve: { time: string; equity: number }[];
}
export interface LabStatus {
  active: boolean; started_at?: string; stopped_at?: string; heartbeat?: string;
  processed_through?: string; history_start?: string; history_end?: string; last_error?: string;
  strategies: LabStrategy[];
  configuration: { initial_equity: number; margin_fraction: number; fee_rate: number;
    slippage_rate: number; hourly_funding_rate: number; maintenance_margin_rate: number; daily_goal_pct: number };
  snapshot: { historical: LabMetrics[]; live: LabMetrics[]; source: string;
    symbol: string; timeframe: string; history_candles: number;
    research?: { method: string; candidates_tested: number; discovery_start: string; discovery_end: string;
      excluded_recent_candles?: number; selected_manually?: boolean; custom_tested?: number;
      eligible_count?: number; selection_message?: string | null;
      trials?: { strategy: LabStrategy; discovery_return: number; discovery_drawdown: number; win_rate?: number | null; trades: number;
        validation_return?: number; validation_win_rate?: number | null; validation_trades?: number; qualified?: boolean }[];
      validation_start: string; validation_end: string; training: LabMetrics[]; validation: LabMetrics[];
      assessments: { key: string; status: string; discovery_trades: number; validation_trades: number }[] } } | null;
}
export function getLiveSimulation(symbol: MarketSymbol = 'BTCUSDT'): Promise<LabStatus> { return getJson<LabStatus>(`/simulator/live?symbol=${symbol}`); }
export function setLiveSimulation(active: boolean, symbol: MarketSymbol = 'BTCUSDT'): Promise<LabStatus> { return postJson<LabStatus>('/simulator/live', { active, symbol }); }

export interface HyperliquidConnection {
  connection: { network: 'mainnet' | 'testnet'; account_address: string } | null;
  execution_enabled: false; mode: 'read_only';
}
export interface HyperliquidAccount {
  account_mode: string;
  trading_balance: { equity: number; available: number; source: string } | null;
  spot_balances: { coin: string; token: number; total: string; hold: string }[];
  network: 'mainnet' | 'testnet'; account_address: string; checked_at: string;
  margin: { accountValue: string; totalMarginUsed: string }; withdrawable?: string;
  positions: { coin: string; szi: string; entryPx?: string; unrealizedPnl: string }[];
  open_orders: { oid: number; coin: string; side: string; sz: string; limitPx: string }[];
}
export const getHyperliquidConnection = () => getJson<HyperliquidConnection>('/hyperliquid/connection');
export const saveHyperliquidConnection = (network: string, account_address: string) => postJson<HyperliquidConnection>('/hyperliquid/connection', { network, account_address });
export const getHyperliquidAccount = () => getJson<HyperliquidAccount>('/hyperliquid/account');
export interface HyperliquidStrategyConfiguration {
  selected: LabStrategy | null; strategies: LabStrategy[]; active_strategy: null;
  execution_enabled: false; blockers: string[];
}
export const getHyperliquidStrategy = () => getJson<HyperliquidStrategyConfiguration>('/hyperliquid/strategy');
export const saveHyperliquidStrategy = (strategy_key: string) => postJson<HyperliquidStrategyConfiguration>('/hyperliquid/strategy', { strategy_key });

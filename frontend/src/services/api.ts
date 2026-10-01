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

async function postActionJson<T>(path: string): Promise<T> {
  const response = await fetch(resolveUrl(path), {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-IziCrypto-Setup': '1' },
    body: '{}',
  });
  const payload = await response.json().catch(() => null) as { error?: string } | null;
  if (!response.ok) {
    throw new Error(payload?.error ?? `Request failed: ${path} (${response.status})`);
  }
  return payload as T;
}

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(resolveUrl(path), {
    method: 'PATCH',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
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
export const saveSimulationSelection = (strategy_keys: string[], symbol: MarketSymbol = 'BTCUSDT') => postJson<{ selected_keys: string[], applied: boolean, warning?: string }>('/simulator/selection', { strategy_keys, symbol });
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
  execution_enabled: boolean; blockers: string[];
}
export interface HyperliquidBot {
  id: number;
  name: string;
  market: string;
  wallet: string | null;
  subaccount: string | null;
  subaccount_name: string | null;
  account_address: string | null;
  network: 'mainnet' | 'testnet';
  strategy: { key: string | null; name: string | null; config: Record<string, unknown> };
  sizing_mode?: 'fixed' | 'available_balance';
  api_credential?: { configured: boolean; valid_until: number | null };
  can_start?: boolean;
  start_blocker?: string | null;
  risk_limits?: {
    sizing_mode?: 'fixed' | 'available_balance';
    capital_usdc?: string | number | null;
    margin_per_trade_usdc?: string | number | null;
    max_leverage?: string | number | null;
    daily_loss_usdc?: string | number | null;
  } | null;
  status: 'running' | 'paused' | 'stopped' | 'error';
  capital: {
    reserved: number | null; initial_bankroll: number | null; current_bankroll: number | null;
    balance: number | null; margin_used: number | null; margin_available: number | null;
    exposure: number | null; max_utilization_pct: number | null; configured_leverage: number | null;
    synced_at: string | null; source: string | null;
  };
  pnl: {
    current: number | null; percent: number | null; realized_24h: number | null;
    fees_24h: number | null; funding_24h: number | null; net_24h: number | null;
    run: number | null; realized_total: number | null; fees_total: number | null;
    funding_total: number | null; bot_total: number | null; basis: string | null;
  };
  position: null | {
    side: 'LONG' | 'SHORT'; size: number; entry_price: number | null; mark_price: number | null;
    position_value: number | null; leverage: number | null; margin_used: number | null;
    unrealized_pnl: number | null; return_on_equity_pct: number | null;
    liquidation_price: number | null; coin: string | null;
  };
  orders: null | {
    count: number; items: Record<string, unknown>[];
    protection: { status: 'protected' | 'unprotected' | 'not_applicable' | 'unknown'; stop_price: number | null; take_profit_price: number | null; orders: Record<string, unknown>[] };
  };
  protection: {
    status: 'protected' | 'unprotected' | 'not_applicable' | 'unknown';
    stop_price: number | null; take_profit_price: number | null;
  } | null;
  activity: { last_fill_at: string | null; last_order_at: string | null; fills_24h: number | null };
  strategy_state: { phase: string | null; message: string | null; last_signal: string | null; last_candle_at: string | null };
  health: {
    status: 'healthy' | 'warning' | 'error' | 'stopped'; reason: string | null;
    worker_active: boolean; last_worker_at: string | null; last_exchange_sync_at: string | null;
    last_error: string | null; exchange_connected: boolean; exchange_synced: boolean;
    position_protection: string; partial_data: boolean; partial_data_reasons: string[];
  };
  run: { id: number | null; phase: string | null; active: boolean; managing: boolean; created_at: string | null };
  created_at: string | null;
  updated_at: string | null;
}
export interface HyperliquidBotMarket { symbol: string; label: string }
export const getHyperliquidBotMarkets = () =>
  getJson<{ markets: HyperliquidBotMarket[] }>('/hyperliquid/bots/markets');
export const getHyperliquidStrategy = () => getJson<HyperliquidStrategyConfiguration>('/hyperliquid/strategy');
export const saveHyperliquidStrategy = (strategy_key: string) => postJson<HyperliquidStrategyConfiguration>('/hyperliquid/strategy', { strategy_key });
export const getHyperliquidBots = () => getJson<{ bots: HyperliquidBot[] }>('/hyperliquid/bots');
export interface HyperliquidBotUpdate {
  name?: string;
  market?: string;
  master_address?: string;
  account_address?: string;
  strategy_key?: string | null;
  strategy_config?: Record<string, unknown>;
  capital_reserved?: number;
  max_utilization_pct?: number;
  leverage?: number;
  sizing_mode?: 'fixed' | 'available_balance';
  risk_limits?: HyperliquidBot['risk_limits'];
}
export interface HyperliquidBotCreate {
  market: string;
  master_address: string;
  account_address: string;
  strategy_key: string;
  capital_reserved: number;
  max_utilization_pct: number;
  leverage: number;
  sizing_mode: 'fixed' | 'available_balance';
  risk_limits: NonNullable<HyperliquidBot['risk_limits']>;
}
export const createHyperliquidBot = (bot: HyperliquidBotCreate) =>
  postJson<HyperliquidBot>('/hyperliquid/bots', bot);
export const updateHyperliquidBot = (botId: number, changes: HyperliquidBotUpdate) =>
  patchJson<HyperliquidBot>(`/hyperliquid/bots/${botId}`, changes);
export const saveHyperliquidBotCredential = async (botId: number, private_key: string) => {
  const response = await fetch(resolveUrl(`/hyperliquid/bots/${botId}/credential`), {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-IziCrypto-Setup': '1' },
    body: JSON.stringify({ private_key }),
  });
  const payload = await response.json().catch(() => null) as {
    error?: string;
    api_credential?: HyperliquidBot['api_credential'];
  } | null;
  if (!response.ok || !payload?.api_credential) {
    throw new Error(payload?.error ?? `Não foi possível salvar a credencial (${response.status}).`);
  }
  return payload.api_credential;
};
export const startHyperliquidBot = (botId: number) =>
  postActionJson<{ status: string; run_id: number; bot: { id: number; status: string } }>(`/hyperliquid/bots/${botId}/start`);
export const pauseHyperliquidBot = (botId: number) =>
  postActionJson<{ status: string; bot: { id: number; status: string } }>(`/hyperliquid/bots/${botId}/pause`);
export const stopHyperliquidBot = (botId: number) =>
  postActionJson<{ status: string; bot: { id: number; status: string } }>(`/hyperliquid/bots/${botId}/stop`);

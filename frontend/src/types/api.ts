export type ScoreValue = number | string | null | undefined;

export interface StatusPayload {
  scanner_status: string;
  last_update: string;
  market: string;
  timeframe: string;
  threshold: number | string;
  price: number | string;
  long_score: number | string;
  short_score: number | string;
  state: string;
  signal_state: string;
  setup_state: string;
  entry_state: string;
  last_file_update: string;
  signals_total: number;
  entries_total: number;
  signal_total: number;
  setup_total: number;
}

export interface SignalRow {
  timestamp?: string;
  timestamp_dt?: string;
  side?: string;
  score?: ScoreValue;
  score_int?: number;
  price?: ScoreValue;
  price_float?: number;
  entry?: ScoreValue;
  stop?: ScoreValue;
  target?: ScoreValue;
  rsi?: number | null;
  atr?: number | null;
  vol_ratio?: number | null;
  trend_bias?: string;
  signal_state?: string;
  setup_state?: string;
  entry_state?: string;
  long_score?: ScoreValue;
  long_score_int?: number;
  short_score?: ScoreValue;
  short_score_int?: number;
  long_trend_ema_active?: boolean | string;
  long_trend_ema_points?: number | string;
  long_trend_ema_value?: number | string;
  short_trend_ema_active?: boolean | string;
  short_trend_ema_points?: number | string;
  short_trend_ema_value?: number | string;
  [key: string]: unknown;
}

export interface ComponentSummary {
  name: string;
  activation_count: number;
  points_total: number;
  points_avg: number;
}

export interface EvaluationRow {
  signal_timestamp?: string;
  signal_score?: number | null;
  price?: number | null;
  long_score?: number | null;
  short_score?: number | null;
  price_after_1?: number | null;
  price_after_3?: number | null;
  price_after_5?: number | null;
  price_after_10?: number | null;
  ret_1?: number | null;
  ret_3?: number | null;
  ret_5?: number | null;
  ret_10?: number | null;
  mfe?: number | null;
  mae?: number | null;
  max_favorable_move?: number | null;
  max_adverse_move?: number | null;
  outcome?: string;
  [key: string]: unknown;
}

export interface SummaryPayload {
  total_rows: number;
  status: StatusPayload;
  components: ComponentSummary[];
}

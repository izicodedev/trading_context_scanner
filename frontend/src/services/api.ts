import type {
  ComponentSummary,
  EvaluationRow,
  SignalRow,
  StatusPayload,
  SummaryPayload,
} from '../types/api';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '');

function resolveUrl(path: string): string {
  return `${API_BASE}${path}`;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(resolveUrl(path));
  if (!response.ok) {
    throw new Error(`Request failed: ${path} (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function getStatus(): Promise<StatusPayload> {
  return getJson<StatusPayload>('/status');
}

export function getHistory(limit = 200): Promise<SignalRow[]> {
  return getJson<SignalRow[]>(`/history?limit=${limit}`);
}

export function getComponents(): Promise<ComponentSummary[]> {
  return getJson<ComponentSummary[]>('/components');
}

export function getEntries(): Promise<SignalRow[]> {
  return getJson<SignalRow[]>('/entries');
}

export function getEvaluation(): Promise<EvaluationRow[]> {
  return getJson<EvaluationRow[]>('/evaluation');
}

export function getSummary(): Promise<SummaryPayload> {
  return getJson<SummaryPayload>('/summary');
}

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
    throw new Error(`Request failed: ${path} (${response.status})`);
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

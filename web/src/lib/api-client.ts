import { getToken, clearSession } from "./auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Generic fetch wrapper ──

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(`API error ${status}`);
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });

  if (res.status === 401) {
    clearSession();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new ApiError(401, { detail: "Unauthorized" });
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// ── Helpers ──

function get<T>(path: string) {
  return request<T>(path);
}

function post<T>(path: string, body?: unknown) {
  return request<T>(path, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });
}

function patch<T>(path: string, body: unknown) {
  return request<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

function put<T>(path: string, body: unknown) {
  return request<T>(path, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

function del<T = void>(path: string) {
  return request<T>(path, { method: "DELETE" });
}

// ── Auth API (uses X-API-Key, no Bearer) ──

import type * as T from "./types";

export const authApi = {
  login: (apiKey: string) =>
    request<T.LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey }),
    }),
  me: () => get<T.UserInfo>("/api/v1/auth/me"),
};

// ── V1 APIs (user) ──

export const usersApi = {
  list: () => get<T.UserResponse[]>("/api/v1/users"),
  get: (id: string) => get<T.UserWithKeys>(`/api/v1/users/${id}`),
  create: (data: T.UserCreate) => post<T.ApiKeyCreated>("/api/v1/users", data),
  update: (id: string, data: T.UserUpdate) =>
    patch<T.UserResponse>(`/api/v1/users/${id}`, data),
  remove: (id: string) => del(`/api/v1/users/${id}`),
  createApiKey: (userId: string, name?: string) =>
    post<T.ApiKeyCreated>(`/api/v1/users/${userId}/api-keys`, { name: name ?? "default" }),
  toggleApiKey: (userId: string, keyId: string) =>
    patch<T.ApiKeyResponse>(`/api/v1/users/${userId}/api-keys/${keyId}`, {}),
  removeApiKey: (userId: string, keyId: string) =>
    del(`/api/v1/users/${userId}/api-keys/${keyId}`),
};

export const watchlistApi = {
  list: () => get<T.WatchlistItemList>("/api/v1/watchlist"),
  add: (data: T.WatchlistItemCreate) =>
    post<T.WatchlistItemResponse>("/api/v1/watchlist", data),
  batchImport: (items: T.WatchlistBatchImportItem[]) =>
    post<T.WatchlistBatchImportResponse>("/api/v1/watchlist/batch", { items }),
  remove: (symbol: string) => del(`/api/v1/watchlist/${symbol}`),
  batchRemove: (symbols: string[]) =>
    post<T.WatchlistBatchRemoveResponse>("/api/v1/watchlist/batch-remove", {
      symbols,
    }),
};

export const signalsApi = {
  query: (params: T.SignalQuery = {}) => {
    const sp = new URLSearchParams();
    if (params.run_date) sp.set("run_date", params.run_date);
    if (params.symbol) sp.set("symbol", params.symbol);
    if (params.strategy) sp.set("strategy", params.strategy);
    if (params.signal) sp.set("signal", params.signal);
    if (params.limit) sp.set("limit", String(params.limit));
    if (params.offset) sp.set("offset", String(params.offset));
    const qs = sp.toString();
    return get<T.SignalList>(`/api/v1/signals${qs ? `?${qs}` : ""}`);
  },
};

export const reportsApi = {
  listUser: (params?: { run_date?: string; report_type?: string; limit?: number; offset?: number }) => {
    const sp = new URLSearchParams();
    if (params?.run_date) sp.set("run_date", params.run_date);
    if (params?.report_type) sp.set("report_type", params.report_type);
    if (params?.limit) sp.set("limit", String(params.limit));
    if (params?.offset) sp.set("offset", String(params.offset));
    const qs = sp.toString();
    return get<T.UserReportList>(`/api/v1/reports${qs ? `?${qs}` : ""}`);
  },
  getUser: (id: string) => get<T.UserReportDetail>(`/api/v1/reports/${id}`),
  listGlobal: (params?: { run_date?: string; symbol?: string; report_type?: string; limit?: number; offset?: number }) => {
    const sp = new URLSearchParams();
    if (params?.run_date) sp.set("run_date", params.run_date);
    if (params?.symbol) sp.set("symbol", params.symbol);
    if (params?.report_type) sp.set("report_type", params.report_type);
    if (params?.limit) sp.set("limit", String(params.limit));
    if (params?.offset) sp.set("offset", String(params.offset));
    const qs = sp.toString();
    return get<T.GlobalReportList>(`/api/v1/reports/global${qs ? `?${qs}` : ""}`);
  },
  getGlobal: (id: string) => get<T.GlobalReportDetail>(`/api/v1/reports/global/${id}`),
};

// ── Admin APIs ──

export const adminPipelineApi = {
  trigger: (runDate?: string) => {
    const sp = runDate ? `?run_date=${runDate}` : "";
    return post<T.PipelineTriggerResponse>(`/api/admin/pipeline/trigger${sp}`);
  },
  status: (runDate?: string) => {
    const sp = runDate ? `?run_date=${runDate}` : "";
    return get<T.PipelineRunResponse>(`/api/admin/pipeline/status${sp}`);
  },
};

export const adminLlmTokensApi = {
  list: () => get<T.LlmTokenListResponse>("/api/admin/llm-tokens"),
  add: (data: T.LlmTokenCreate) =>
    post<T.LlmTokenResponse>("/api/admin/llm-tokens", data),
  update: (id: string, data: T.LlmTokenUpdate) =>
    patch<T.LlmTokenResponse>(`/api/admin/llm-tokens/${id}`, data),
  remove: (id: string) => del(`/api/admin/llm-tokens/${id}`),
};

export const adminGlobalSymbolsApi = {
  list: (symbolType?: "macro" | "sector") => {
    const sp = symbolType ? `?symbol_type=${symbolType}` : "";
    return get<{ items: T.GlobalSymbolResponse[]; total: number }>(`/api/admin/global-symbols${sp}`);
  },
  batchAdd: (symbols: { symbol: string; symbol_type: "macro" | "sector"; description?: string }[]) =>
    post("/api/admin/global-symbols/batch", { items: symbols }),
  batchRemove: (symbols: string[]) =>
    post("/api/admin/global-symbols/batch-remove", { symbols }),
};

export const adminStrategiesApi = {
  list: () => get<T.StrategyListResponse>("/api/admin/strategies"),
  get: (name: string) =>
    get<T.StrategyWithPresets>(`/api/admin/strategies/${name}`),
  updateActivePreset: (name: string, presetId: string | null) =>
    patch(`/api/admin/strategies/${name}/active-preset`, {
      active_preset_id: presetId,
    }),
  listPresets: (name: string) =>
    get<{ presets: T.StrategyPresetResponse[]; total: number }>(
      `/api/admin/strategies/${name}/presets`,
    ),
  addPreset: (name: string, data: T.StrategyPresetCreate) =>
    post<T.StrategyPresetResponse>(
      `/api/admin/strategies/${name}/presets`,
      data,
    ),
  batchUpdatePresets: (name: string, presets: T.StrategyPresetCreate[]) =>
    put(`/api/admin/strategies/${name}/presets/batch`, { presets }),
  removePreset: (name: string, presetName: string) =>
    del(`/api/admin/strategies/${name}/presets/${presetName}`),
};

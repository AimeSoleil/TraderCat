// ── TypeScript types matching backend Pydantic schemas ──

// ── Auth ──
export interface LoginRequest {
  token: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserInfo;
}

export interface UserInfo {
  id: string;
  username: string;
  email: string;
  role: "admin" | "user";
}

// ── User ──
export interface UserResponse {
  id: string;
  username: string;
  email: string;
  role: "admin" | "user";
  is_active: boolean;
  max_symbols: number;
  preferred_lang: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserCreate {
  username: string;
  email: string;
  role?: "admin" | "user";
  max_symbols?: number;
  preferred_lang?: string | null;
}

export interface UserUpdate {
  email?: string | null;
  role?: "admin" | "user" | null;
  is_active?: boolean | null;
  max_symbols?: number | null;
  preferred_lang?: string | null;
}

export interface TokenResponse {
  id: string;
  key_prefix: string;
  name: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface TokenCreate {
  name?: string;
}

export interface TokenCreated {
  token: string;
  key_prefix: string;
  name: string;
  created_at: string;
}

export interface UserWithTokens extends UserResponse {
  tokens: TokenResponse[];
}

// Backward-compatible aliases
export type ApiKeyResponse = TokenResponse;
export type ApiKeyCreate = TokenCreate;
export type ApiKeyCreated = TokenCreated;
export type UserWithKeys = UserWithTokens;

// ── Watchlist ──
export interface WatchlistItemResponse {
  id: string;
  user_id: string;
  symbol: string;
  description: string | null;
  added_at: string;
}

export interface WatchlistItemCreate {
  symbol: string;
  description?: string | null;
}

export interface WatchlistItemList {
  items: WatchlistItemResponse[];
  total: number;
}

export interface WatchlistBatchImportItem {
  symbol: string;
  description?: string | null;
}

export interface WatchlistBatchImportResponse {
  created: number;
  skipped: number;
  errors: number;
  results: { symbol: string; status: string; detail?: string | null }[];
}

export interface WatchlistBatchRemoveResponse {
  removed: number;
  not_found: number;
  results: { symbol: string; status: string }[];
}

// ── Signals ──
export interface SignalResponse {
  id: string;
  run_date: string;
  symbol: string;
  strategy: string;
  signal: "buy" | "sell" | "hold" | "rebalance";
  confidence: number;
  reason: string | null;
  ohlcv: Record<string, unknown> | null;
  indicators: Record<string, unknown> | null;
  scope: "global" | "user";
  created_at: string;
}

export interface SignalList {
  signals: SignalResponse[];
  total: number;
}

export interface SignalQuery {
  run_date?: string;
  symbol?: string;
  strategy?: string;
  signal?: "buy" | "sell" | "hold" | "rebalance";
  limit?: number;
  offset?: number;
}

// ── Reports (Pipeline v2) ──

export interface MacroRegimeContextResponse {
  id: string;
  run_date: string;
  regime_label: string | null;
  regime_score: number | null;
  content_md: string;
  model_used: string | null;
  identity_used: string | null;
  created_at: string;
}

export interface MacroRegimeContextDetail extends MacroRegimeContextResponse {
  downstream_filters: Record<string, unknown> | null;
  input_context: Record<string, unknown> | null;
}

export interface MacroRegimeContextList {
  reports: MacroRegimeContextResponse[];
  total: number;
}

export interface SymbolExecutionPlanResponse {
  id: string;
  run_date: string;
  symbol: string;
  verdict: string | null;
  setup_quality: string | null;
  content_md: string;
  model_used: string | null;
  identity_used: string | null;
  created_at: string;
}

export interface SymbolExecutionPlanDetail extends SymbolExecutionPlanResponse {
  input_context: Record<string, unknown> | null;
}

export interface SymbolExecutionPlanList {
  reports: SymbolExecutionPlanResponse[];
  total: number;
}

export interface UserBriefingResponse {
  id: string;
  user_id: string;
  run_date: string;
  content_md: string;
  model_used: string | null;
  identity_used: string | null;
  created_at: string;
}

export interface UserBriefingDetail extends UserBriefingResponse {
  input_context: Record<string, unknown> | null;
}

export interface UserBriefingList {
  reports: UserBriefingResponse[];
  total: number;
}

// ── Strategy ──
export interface StrategyPresetResponse {
  id: string;
  strategy_id: string;
  name: string;
  description: string | null;
  parameters: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface StrategyPresetCreate {
  name: string;
  description?: string | null;
  parameters: Record<string, unknown>;
}

export interface StrategyResponse {
  id: string;
  name: string;
  description: string | null;
  strategy_class: string;
  default_preset_name: string;
  active_preset_id: string | null;
  active_preset: StrategyPresetResponse | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface StrategyWithPresets extends StrategyResponse {
  presets: StrategyPresetResponse[];
}

export interface StrategyListResponse {
  strategies: StrategyResponse[];
  total: number;
}

// ── Global Symbols ──
export interface GlobalSymbolResponse {
  id: string;
  symbol: string;
  symbol_type: "macro" | "sector";
  description: string | null;
  added_at: string;
}

// ── LLM Tokens ──
export interface LlmTokenResponse {
  id: string;
  provider_name: string;
  token_preview: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LlmTokenListResponse {
  items: LlmTokenResponse[];
  total: number;
}

export interface LlmTokenCreate {
  provider_name: string;
  token: string;
  description?: string | null;
  is_active?: boolean;
}

export interface LlmTokenUpdate {
  provider_name?: string;
  token?: string;
  description?: string | null;
  is_active?: boolean;
}

// ── Pipeline ──
export interface PipelineRunResponse {
  id: string;
  run_date: string;
  status: string;
  step: string | null;
  total_symbols: number;
  processed_symbols: number;
  total_reports: number;
  processed_reports: number;
  error_log: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface PipelineTriggerResponse {
  message: string;
  run_date: string;
  pipeline_run_id: string;
}

export interface PipelineRunListResponse {
  runs: PipelineRunResponse[];
  total: number;
}

export interface PipelineCancelResponse {
  message: string;
  run_id: string;
  run_date: string;
  previous_status: string;
  new_status: string;
}

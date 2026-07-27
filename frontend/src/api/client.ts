// Minimal typed REST client. We avoid axios so the bundle stays tiny and so
// SSE/streaming can use the native fetch + EventSource without interceptors.

const BASE_URL = "/api/v1";

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let code = `http_${res.status}`;
    let message = res.statusText;
    try {
      const data = await res.json();
      code = data.error_code ?? code;
      message = data.message ?? data.detail ?? message;
    } catch {
      /* non-JSON body â€” keep status text */
    }
    throw new ApiError(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

async function upload<T>(path: string, files: File[], field = "files"): Promise<T> {
  const form = new FormData();
  for (const f of files) form.append(field, f);
  // No explicit Content-Type â€” the browser sets the multipart boundary.
  const res = await fetch(`${BASE_URL}${path}`, { method: "POST", body: form });
  if (!res.ok) {
    let code = `http_${res.status}`;
    let message = res.statusText;
    try {
      const data = await res.json();
      code = data.error_code ?? code;
      message = data.message ?? data.detail ?? message;
    } catch {
      /* non-JSON body â€” keep status text */
    }
    throw new ApiError(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
  upload,
};

export const mediaUrl = (path: string, bust?: string | number | null) => {
  const base = `${BASE_URL}${path.replace(/^\/api\/v1/, "")}`;
  return bust ? `${base}?v=${bust}` : base;
};

// ---------------------------------------------------------------------------
// Types â€” hand-written; mirror the backend Pydantic schemas.
// ---------------------------------------------------------------------------
export interface HealthResponse {
  status: string;
  app_mode: string;
  version: string;
  components: Record<string, string>;
}

export interface ProviderPreferences {
  primary: string;
  fallback_chain: string[];
  model_hints: string[];
  budget_usd_per_episode: number | null;
  latency_priority: string;
}

export interface PodConfigPayload {
  series_name: string;
  target_audience: string;
  language: string;
  art_style: string | null;
  style_profile: string;
  content_type: ContentType;
  character_mode: CharacterMode;
  duration_seconds: number;
  max_clip_seconds: number;
  interactive_questions: number;
  narration_style: NarrationStyle;
  setting_mode: SettingMode;
  provider_preferences: ProviderPreferences;
  series_context: string | null;
  universe_memory: string | null;
  extra: Record<string, unknown>;
}

export type ContentType =
  | "story" | "meme" | "scene_recreation" | "educational" | "other";
export type CharacterMode =
  | "reference" | "optional" | "none" | "narrator_pip" | "scene_native";
export type NarrationStyle = "fourth_wall" | "immersive" | "voiceover";
export type SettingMode = "in_scene" | "framing_device";

export interface Pod {
  id: string;
  owner_id: string;
  name: string;
  config: PodConfigPayload;
  created_at: string;
  updated_at: string;
}

export interface Character {
  id: string;
  pod_id: string;
  name: string;
  role: string;
  personality: string | null;
  look_description: string | null;
  voice: Record<string, unknown> | null;
  reference_image_keys: string[];
  higgsfield_ref_id: string | null;
  higgsfield_ref_kind: string | null;
  created_at: string;
}

export interface Topic {
  id: string;
  pod_id: string;
  title: string;
  description: string | null;
  status: string;
  educational_value: string | null;
  created_at: string;
}

export interface Scene {
  id: string;
  index: number;
  visual_prompt: string;
  audio_text: string | null;
  duration_s: number;
  camera_shot: string | null;
  camera_movement: string | null;
  camera_angle: string | null;
  transition: string;
}

export interface Script {
  id: string;
  pod_id: string;
  topic_id: string | null;
  version: number;
  title: string;
  summary: string | null;
  moral: string | null;
  ambient_audio_prompt: string | null;
  scenes: Scene[];
  reviewed: boolean;
  created_at: string;
}

export type EpisodeState =
  | "draft" | "scripting" | "reviewing" | "rendering" | "ready" | "published" | "failed";

export interface Episode {
  id: string;
  pod_id: string;
  topic_id: string | null;
  script_id: string | null;
  title: string;
  number: number;
  state: EpisodeState;
  final_video_key: string | null;
  dubbed_video_key: string | null;
  youtube_video_id: string | null;
  video_provider: string | null;
  video_model: string | null;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface MediaAsset {
  kind: "video" | "image" | "audio" | "subtitle" | "data";
  name: string;
  url: string;
  group: string | null;
  content_type: string | null;
  size_bytes: number | null;
}

export interface SeoMetadata {
  id: string;
  pod_id: string;
  episode_id: string;
  description: string;
  tags: string[];
  hashtags: string[];
  title_variants: string[];
  selected_title: string | null;
  created_at: string;
  updated_at: string;
}

export interface EpisodeDetail {
  episode: Episode;
  script: Script | null;
  seo: SeoMetadata | null;
  media: MediaAsset[];
}

export interface RecommendTitleResponse {
  title: string;
  score: number;
  scores: Record<string, number>;
}

export interface DashboardCounts {
  pods: number;
  episodes: number;
  shorts: number;
  jobs_running: number;
}
export interface DashboardEpisode {
  id: string;
  pod_id: string;
  pod_name: string;
  title: string;
  number: number;
  state: string;
  thumb_url: string | null;
  video_url: string | null;
}
export interface DashboardShort {
  id: string;
  pod_id: string;
  pod_name: string;
  hook_text: string | null;
  duration_s: number;
  video_url: string | null;
}
export interface DashboardResponse {
  counts: DashboardCounts;
  recent_episodes: DashboardEpisode[];
  recent_shorts: DashboardShort[];
}

export const getDashboard = () => api.get<DashboardResponse>("/dashboard");

export const generateSeo = (podId: string, episodeId: string, variantCount = 4) =>
  api.post<SeoMetadata>(`/pods/${podId}/episodes/${episodeId}/seo`, { variant_count: variantCount });

export const recommendTitle = (podId: string, episodeId: string) =>
  api.post<RecommendTitleResponse>(`/pods/${podId}/episodes/${episodeId}/seo/recommend`);

export interface Short {
  id: string;
  pod_id: string;
  source_episode_id: string | null;
  aspect: string;
  duration_s: number;
  hook_text: string | null;
  rendered_video_key: string | null;
  target_platform: string;
  created_at: string;
}

export interface Job {
  id: string;
  owner_id: string;
  kind: string;
  state: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  message: string | null;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProviderHealth {
  name: string;
  available: boolean;
  message: string | null;
  cost_per_second_usd: number | null;
}

export interface ProviderCatalogEntry {
  name: string;
  available: boolean;
  message: string | null;
  models: string[];
  label?: string | null;
}

export interface VoiceOption {
  voice_id: string;
  name: string;
  preview_url: string | null;
  description: string | null;
  gender: string | null;
  age: string | null;
  accent: string | null;
  language: string | null;
}

export interface SdkModel {
  id: string;
  family: string;
  capabilities: string[];
  max_duration_s: number;
  credits: number;
  cost_per_second_usd: number;
  est_usd_per_clip: number;
  unlimited: boolean;
  copyright_strict: boolean;
  good_for: string[];
  strengths: string[];
}

export interface SdkProvider {
  id: string;
  name: string;
  capabilities: string[];
  tags: string[];
  adapter_type: string;
  cost_per_second_usd: number;
  models: SdkModel[];
}

export const getSdkProviders = () => api.get<SdkProvider[]>("/system/providers/sdk");

export interface ModelRecommendation {
  provider_id: string;
  model_id: string;
  est_credits: number;
  est_usd: number;
  fits_content: boolean;
  within_duration: boolean;
  unlimited: boolean;
  copyright_safe: boolean;
  recommended: boolean;
  reason: string;
  backend: string;
  experimental: boolean;
}

export interface RecommendResponse {
  content_type: string;
  duration_s: number;
  copyright_flagged: boolean;
  recommendations: ModelRecommendation[];
}

export const CONTENT_TYPES = [
  "animation_2d", "animation_3d", "talking_head",
  "realistic", "cinematic", "quick_draft",
] as const;
export type ProviderContentType = (typeof CONTENT_TYPES)[number];

export const recommendModels = (params: {
  content_type: string;
  duration_s?: number;
  capability?: string;
  copyright_flagged?: boolean;
  provider?: string | null;
}) => {
  const q = new URLSearchParams();
  q.set("content_type", params.content_type);
  if (params.duration_s != null) q.set("duration_s", String(params.duration_s));
  if (params.capability) q.set("capability", params.capability);
  if (params.copyright_flagged != null) q.set("copyright_flagged", String(params.copyright_flagged));
  if (params.provider) q.set("provider", params.provider);
  return api.get<RecommendResponse>(`/system/providers/recommend?${q.toString()}`);
};

export interface CopyrightScreenResult {
  has_real_people: boolean;
  real_people: string[];
  copyrighted_characters: string[];
  notes: string;
  risky: boolean;
  cached: boolean;
}

export const copyrightScreen = (text: string, force = false) =>
  api.post<CopyrightScreenResult>("/system/copyright-screen", { text, force });

export interface ModelHandle {
  id: string;
  family: string;
  capabilities: string[];
  max_duration_s: number;
  max_resolution: [number, number];
  cost_per_second_usd: number;
  latency_p95_s: number;
  strengths: string[];
}

// --- System / LLM ---------------------------------------------------------
export interface OllamaStatus {
  running: boolean;
  base_url: string;
  models: string[];
  current_model_installed: boolean;
  error: string | null;
}
export interface LlmConfig {
  provider: "gemini" | "ollama";
  gemini_model: string;
  ollama_model: string;
  gemini_key_present: boolean;
  ollama: OllamaStatus;
}
export interface OllamaModelOption {
  name: string;
  label: string;
  params: string;
  min_vram_gb: number;
  notes: string;
  fits: boolean;
  installed: boolean;
}
export interface RecommendedModels {
  vram_gb: number | null;
  models: OllamaModelOption[];
}
export interface FileContent {
  name: string;
  content: string;
}

// --- Wizard ---------------------------------------------------------------
export interface PodBlueprint {
  series_name: string;
  bible: {
    genre: string; audience: string; tone: string | null;
    narrative_arc: string | null; format: string | null; language: string;
  };
  style_profile: string;
  art_style: string | null;
  characters: { name: string; role: string; personality: string | null; look_description: string | null }[];
  topic_seeds: string[];
  content_type: ContentType;
  character_mode: CharacterMode;
  duration_seconds: number;
  max_clip_seconds: number;
  interactive_questions: number;
  narration_style: NarrationStyle;
  setting_mode: SettingMode;
}

// ---------------------------------------------------------------------------
// SSE â€” live job progress
// ---------------------------------------------------------------------------
export interface JobEvent {
  event: string;
  job_id: string;
  progress?: number;
  message?: string | null;
  error?: string;
  result?: Record<string, unknown>;
}

export function subscribeToJob(
  jobId: string,
  handlers: { onEvent: (e: JobEvent) => void; onError?: (e: Event) => void },
): () => void {
  const src = new EventSource(`${BASE_URL}/jobs/${jobId}/events`);
  src.onmessage = (msg) => {
    try {
      handlers.onEvent(JSON.parse(msg.data) as JobEvent);
    } catch {
      /* skip malformed event */
    }
  };
  if (handlers.onError) src.onerror = handlers.onError;
  return () => src.close();
}

// ---------------------------------------------------------------------------
// Templates / Director / Runs (DAG recipes)
// ---------------------------------------------------------------------------
export interface DagNodeDto {
  id: string;
  capability: string;
  params: Record<string, unknown>;
  depends_on: string[];
  max_retries: number;
}

export interface DagSpecDto {
  nodes: DagNodeDto[];
}

export interface Template {
  id: string;
  name: string;
  description: string;
  tags: string[];
  preview: string | null;
  dag: DagSpecDto;
}

export interface JsonPatchOp {
  op: string;
  path: string;
  value?: unknown;
  from?: string;
}

export interface DirectorChatResponse {
  patch: JsonPatchOp[];
  explanation: string;
  spec: DagSpecDto;
}

export type RunNodeState = "pending" | "running" | "done" | "failed" | "cancelled";

export interface RunNodeStatus {
  state: RunNodeState;
  error: string | null;
  retries_left: number;
  output: Record<string, unknown> | null;
}

export interface RunSnapshot {
  run_id: string;
  is_complete: boolean;
  has_failures: boolean;
  nodes: Record<string, RunNodeStatus>;
  video_url: string | null;
  artifacts: string[];
}

export const getTemplates = () => api.get<Template[]>("/templates");
export const getTemplate = (id: string) => api.get<Template>(`/templates/${id}`);
export const directorChat = (spec: DagSpecDto, message: string) =>
  api.post<DirectorChatResponse>("/director/chat", { spec, message });
export const getRun = (runId: string) => api.get<RunSnapshot>(`/runs/${runId}`);
export const startRun = (spec: DagSpecDto) => api.post<RunSnapshot>("/runs", spec);

// ---------------------------------------------------------------------------
// SSE â€” live run progress
// ---------------------------------------------------------------------------
export interface RunEvent {
  event: "node_running" | "node_done" | "node_retry" | "node_failed" | "node_cancelled" | "run_complete";
  node?: string;
  error?: string;
  failed?: boolean;
}

export function subscribeToRun(
  runId: string,
  handlers: { onEvent: (e: RunEvent) => void; onError?: (e: Event) => void },
): () => void {
  const src = new EventSource(`${BASE_URL}/runs/${runId}/events`);
  src.onmessage = (msg) => {
    try {
      handlers.onEvent(JSON.parse(msg.data) as RunEvent);
    } catch {
      /* skip malformed event */
    }
  };
  if (handlers.onError) src.onerror = handlers.onError;
  return () => src.close();
}

// ---------------------------------------------------------------------------
// Recreations â€” famous-scene recreation planner (Â§16)
// ---------------------------------------------------------------------------
export interface FairUse {
  closeness: number;
  transformative: number;
  risk: "low" | "medium" | "high";
  guidance: string;
  requires_confirmation: boolean;
}

export interface RecreationBeat {
  beat: string;
  duration_s: number;
  description: string;
}

export interface RecreationPlan {
  id: string;
  title: string;
  v2v_prompt: string;
  reference_description: string;
  beats: RecreationBeat[];
  audio_note: string;
  fair_use: FairUse;
  provider_hint: string[];
}

export interface Recreation {
  id: string;
  owner_id: string;
  state: string;
  run_id: string | null;
  title: string;
  original: string;
  niche: string;
  twist: string;
  v2v_prompt: string;
  beats: RecreationBeat[];
  audio_note: string;
  reference_description: string;
  fair_use: FairUse;
  provider: string | null;
  model: string | null;
  source_id: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface RecreationListResponse {
  recreations: Recreation[];
}

export interface UpdateRecreationRequest {
  title?: string;
  v2v_prompt?: string;
  reference_description?: string;
  beats?: RecreationBeat[];
  audio_note?: string;
  provider?: string;
  video_model?: string;
  /** Attach/replace the real clip (ingested via the Alternate-Ending upload/
   * YouTube endpoints) this recreation edits via video_to_video. */
  source_id?: string;
}

export interface SceneCandidate {
  term: string;
  scene: string;
  why_trending: string;
}

/** Where the trend terms behind a trend-match came from — "live" when Google
 * Trends answered, "cache" when a same-day cached fetch was reused, and
 * "fallback" when neither was available (generic evergreen terms). */
export type TrendsSource = "live" | "cache" | "fallback";

export interface SceneTrendMatchResponse {
  candidates: SceneCandidate[];
  trends_source: TrendsSource;
}

export const planRecreation = (original: string, niche: string, twist: string) =>
  api.post<RecreationPlan>("/brain/recreations/plan", { original, niche, twist });

export const getRecreations = () => api.get<RecreationListResponse>("/brain/recreations");
export const getRecreation = (id: string) => api.get<Recreation>(`/brain/recreations/${id}`);
export const updateRecreation = (id: string, updates: UpdateRecreationRequest) =>
  api.patch<Recreation>(`/brain/recreations/${id}`, updates);
export const runRecreation = (id: string) => api.post<{ run_id: string }>(`/brain/recreations/${id}/run`);
export const deleteRecreation = (id: string) => api.delete<void>(`/brain/recreations/${id}`);

export const sceneTrendMatch = (terms: string[]) =>
  api.post<SceneTrendMatchResponse>("/brain/recreations/trend-match", { terms });

// ---- Alternate Ending (keep clip head, regenerate tail via i2v) ------------
export interface IngestResponse { source_id: string; duration_s: number; }
export interface AlternateEndingResponse { video_url: string | null; duration_s: number; }

export const ingestAltUpload = (file: File) =>
  api.upload<IngestResponse>("/brain/recreations/ingest/upload", [file], "file");
export const ingestAltYoutube = (url: string, rights_ack: boolean) =>
  api.post<IngestResponse>("/brain/recreations/ingest/youtube", { url, rights_ack });

/** "i2v" (default, back-compat): regenerate the tail from a still frame via
 * image_to_video. "edit": feed the real tail clip to a video_to_video editing
 * model (e.g. Gemini Omni Flash) instead of regenerating it from scratch. */
export type AlternateEndingMode = "i2v" | "edit";

export const runAlternateEnding = (
  source_id: string, cut_at_s: number, prompt: string, tail_duration_s = 5,
  opts: { mode?: AlternateEndingMode; provider?: string; model?: string } = {},
) => api.post<AlternateEndingResponse>("/brain/recreations/alternate-ending", {
  source_id, cut_at_s, prompt, tail_duration_s,
  mode: opts.mode ?? "i2v", provider: opts.provider, model: opts.model,
});

// ---------------------------------------------------------------------------
// Channels Hub (multi-account publishing) â€” gated behind a Settings switch
// ---------------------------------------------------------------------------
export type ChannelPlatform = "youtube" | "tiktok" | "instagram";

export interface AppConfig {
  channels_feature_enabled: boolean;
  public_media_base_url: string | null;
}

export interface Channel {
  id: string;
  platform: ChannelPlatform;
  display_name: string;
  handle: string | null;
  status: "connected" | "expired" | "error";
}

/** Human label for an account that stays distinguishable even when two
 *  accounts share a generic display_name (e.g. two YouTube channels both
 *  stored as "Youtube" before the channel-identity fetch existed): prefer the
 *  @handle, else fall back to a short id suffix so they never look identical. */
export function accountLabel(a: Channel): string {
  if (a.handle) return `${a.display_name} · ${a.handle}`;
  const generic = a.display_name.toLowerCase() === a.platform.toLowerCase();
  if (generic) return `${a.display_name} · #${a.id.slice(-4)}`;
  return a.display_name;
}

export interface PublishJob {
  id: string;
  account_id: string;
  platform: ChannelPlatform;
  source: "episode" | "short";
  source_id: string;
  status: "pending" | "uploading" | "published" | "error";
  result_url: string | null;
  error: string | null;
  scheduled_at: string | null;
}

export interface EnqueueUploadRequest {
  source: "episode" | "short";
  source_id: string;
  account_ids: string[];
  metadata?: Record<string, unknown>;
  scheduled_at?: string | null;
}

export const getAppConfig = () => api.get<AppConfig>("/system/config");
export const setAppConfig = (patch: Partial<AppConfig>) =>
  api.put<AppConfig>("/system/config", patch);

// ---------------------------------------------------------------------------
// Gameplay b-roll (local "split" layout folder)
// ---------------------------------------------------------------------------
export interface BrollClip {
  name: string;
  duration_s: number;
  author: string | null;
  source: string | null;
  source_url: string | null;
}

export interface BrollLibrary {
  folder: string;
  clips: BrollClip[];
}

export const getBrollLibrary = () => api.get<BrollLibrary>("/system/broll");
export const populateBroll = (count = 5) =>
  api.post<{ downloaded: BrollClip[] }>("/system/broll/populate", { count });

export const listChannels = () => api.get<Channel[]>("/channels");
export const connectChannel = (platform: ChannelPlatform, client_id: string, client_secret: string) =>
  api.post<Channel>(`/channels/${platform}/connect`, { client_id, client_secret });
export const disconnectChannel = (accountId: string) => api.delete<void>(`/channels/${accountId}`);
export const verifyChannel = (accountId: string) => api.post<Channel>(`/channels/${accountId}/verify`);
export const enqueueUpload = (body: EnqueueUploadRequest) =>
  api.post<PublishJob[]>("/channels/upload", body);
export const listUploads = () => api.get<PublishJob[]>("/channels/uploads");

// ---------------------------------------------------------------------------
// Streaming NDJSON (Ollama model pull progress)
// ---------------------------------------------------------------------------
export async function streamOllamaPull(
  model: string,
  onLine: (obj: Record<string, unknown>) => void,
): Promise<void> {
  const res = await fetch(`${BASE_URL}/system/llm/ollama/pull`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
  if (!res.body) throw new ApiError(res.status, "no_body", "pull stream unavailable");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      try { onLine(JSON.parse(line)); } catch { /* ignore */ }
    }
  }
}

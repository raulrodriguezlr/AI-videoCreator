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
      /* non-JSON body — keep status text */
    }
    throw new ApiError(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

async function upload<T>(path: string, files: File[], field = "files"): Promise<T> {
  const form = new FormData();
  for (const f of files) form.append(field, f);
  // No explicit Content-Type — the browser sets the multipart boundary.
  const res = await fetch(`${BASE_URL}${path}`, { method: "POST", body: form });
  if (!res.ok) {
    let code = `http_${res.status}`;
    let message = res.statusText;
    try {
      const data = await res.json();
      code = data.error_code ?? code;
      message = data.message ?? data.detail ?? message;
    } catch {
      /* non-JSON body — keep status text */
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

export const mediaUrl = (path: string) => `${BASE_URL}${path.replace(/^\/api\/v1/, "")}`;

// ---------------------------------------------------------------------------
// Types — hand-written; mirror the backend Pydantic schemas.
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
  provider_preferences: ProviderPreferences;
  series_context: string | null;
  universe_memory: string | null;
  extra: Record<string, unknown>;
}

export type ContentType =
  | "story" | "meme" | "scene_recreation" | "educational" | "other";
export type CharacterMode =
  | "reference" | "optional" | "none" | "narrator_pip" | "scene_native";

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
}

// ---------------------------------------------------------------------------
// SSE — live job progress
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

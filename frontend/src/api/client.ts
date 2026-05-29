// Minimal typed REST client. We avoid axios so the bundle stays tiny and so
// SSE can use the native EventSource without conflicting interceptors.

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
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let code = `http_${res.status}`;
    let message = res.statusText;
    try {
      const data = await res.json();
      code = data.error_code ?? code;
      message = data.message ?? message;
    } catch {
      /* response body was not JSON — fall back to status text */
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
  delete: <T>(path: string) => request<T>("DELETE", path),
};

// ---------------------------------------------------------------------------
// Shared types — kept hand-written for now; we'll replace these with codegen
// from /api/v1/openapi.json in a later pass.
// ---------------------------------------------------------------------------
export interface HealthResponse {
  status: string;
  app_mode: string;
  version: string;
  components: Record<string, string>;
}

export interface PodConfigPayload {
  series_name: string;
  target_audience: string;
  language: string;
  art_style: string | null;
  style_profile: string;
  duration_seconds: number;
  provider_preferences: {
    primary: string;
    fallback_chain: string[];
    model_hints: string[];
    budget_usd_per_episode: number | null;
    latency_priority: string;
  };
  series_context: string | null;
  extra: Record<string, unknown>;
}

export interface Pod {
  id: string;
  owner_id: string;
  name: string;
  config: PodConfigPayload;
  created_at: string;
  updated_at: string;
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
  scenes: Scene[];
  reviewed: boolean;
  created_at: string;
}

export interface Episode {
  id: string;
  pod_id: string;
  topic_id: string | null;
  script_id: string | null;
  title: string;
  number: number;
  state: string;
  final_video_key: string | null;
  dubbed_video_key: string | null;
  youtube_video_id: string | null;
  created_at: string;
  updated_at: string;
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

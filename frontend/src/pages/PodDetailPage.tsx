import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Episode, type Pod, type Script, type Topic } from "../api/client";

export function PodDetailPage() {
  const { podId } = useParams<{ podId: string }>();
  const queryClient = useQueryClient();

  const pod = useQuery<Pod>({
    queryKey: ["pod", podId],
    queryFn: () => api.get(`/pods/${podId}`),
    enabled: !!podId,
  });
  const topics = useQuery<Topic[]>({
    queryKey: ["topics", podId],
    queryFn: () => api.get(`/pods/${podId}/topics`),
    enabled: !!podId,
  });
  const scripts = useQuery<Script[]>({
    queryKey: ["scripts", podId],
    queryFn: () => api.get(`/pods/${podId}/scripts`),
    enabled: !!podId,
  });
  const episodes = useQuery<Episode[]>({
    queryKey: ["episodes", podId],
    queryFn: () => api.get(`/pods/${podId}/episodes`),
    enabled: !!podId,
  });

  const generateTopics = useMutation({
    mutationFn: () => api.post<Topic[]>(`/pods/${podId}/topics/generate`, { count: 5 }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["topics", podId] }),
  });

  if (pod.isLoading) return <div className="muted">Loading pod…</div>;
  if (!pod.data) return <div className="card">Pod not found.</div>;

  return (
    <>
      <Link to="/" className="muted">
        ← All pods
      </Link>
      <h2 style={{ marginTop: 8 }}>{pod.data.name}</h2>
      <div className="muted" style={{ marginBottom: 24 }}>
        {pod.data.config.series_name} · {pod.data.config.language} · target audience:{" "}
        {pod.data.config.target_audience} · {pod.data.config.duration_seconds}s
      </div>

      <Section title="Topics">
        <button
          onClick={() => generateTopics.mutate()}
          disabled={generateTopics.isPending}
          style={{ marginBottom: 12 }}
        >
          {generateTopics.isPending ? "Generating…" : "Generate 5 topics with LLM"}
        </button>
        {generateTopics.error && (
          <div className="muted" style={{ color: "var(--err)", marginBottom: 8 }}>
            {String(generateTopics.error)}
          </div>
        )}
        {topics.data?.length === 0 && <div className="muted">No topics yet.</div>}
        {topics.data?.map((t) => (
          <div className="card" key={t.id}>
            <div className="row">
              <div>
                <div style={{ fontWeight: 600 }}>{t.title}</div>
                <div className="muted">{t.description ?? "(no description)"}</div>
              </div>
              <span className="badge">{t.status}</span>
            </div>
          </div>
        ))}
      </Section>

      <Section title="Scripts">
        {scripts.data?.length === 0 && <div className="muted">No scripts yet.</div>}
        {scripts.data?.map((s) => (
          <div className="card" key={s.id}>
            <div className="row">
              <div>
                <div style={{ fontWeight: 600 }}>{s.title}</div>
                <div className="muted">
                  v{s.version} · {s.scenes.length} scenes
                </div>
              </div>
              <span className="badge">{s.reviewed ? "reviewed" : "draft"}</span>
            </div>
          </div>
        ))}
      </Section>

      <Section title="Episodes">
        {episodes.data?.length === 0 && <div className="muted">No episodes yet.</div>}
        {episodes.data?.map((ep) => (
          <div className="card" key={ep.id}>
            <div className="row">
              <div>
                <div style={{ fontWeight: 600 }}>
                  #{ep.number} · {ep.title}
                </div>
                <div className="muted">{ep.id}</div>
              </div>
              <span
                className={`badge ${
                  ep.state === "ready" ? "ok" : ep.state === "failed" ? "err" : ""
                }`}
              >
                {ep.state}
              </span>
            </div>
          </div>
        ))}
      </Section>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 32 }}>
      <h3 style={{ marginBottom: 8 }}>{title}</h3>
      {children}
    </section>
  );
}

import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Pod } from "../api/client";

export function PodsListPage() {
  const queryClient = useQueryClient();
  const pods = useQuery<Pod[]>({ queryKey: ["pods"], queryFn: () => api.get("/pods") });
  const [showForm, setShowForm] = useState(false);

  const createPod = useMutation({
    mutationFn: (body: { name: string; series_name: string; language: string }) =>
      api.post<Pod>("/pods", {
        name: body.name,
        config: {
          series_name: body.series_name,
          language: body.language,
          duration_seconds: 120,
        },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["pods"] });
      setShowForm(false);
    },
  });

  return (
    <>
      <div className="row" style={{ marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Pods</h2>
        <button onClick={() => setShowForm((v) => !v)}>{showForm ? "Cancel" : "New pod"}</button>
      </div>

      {showForm && (
        <NewPodForm
          onSubmit={(v) => createPod.mutate(v)}
          loading={createPod.isPending}
          error={createPod.error ? String(createPod.error) : null}
        />
      )}

      {pods.isLoading && <div className="muted">Loading pods…</div>}
      {pods.error && <div className="card">Error: {String(pods.error)}</div>}
      {pods.data?.length === 0 && (
        <div className="card muted">
          No pods yet. Click <em>New pod</em> or run <code>videocreator pods import</code> from
          the CLI to bring in your legacy <code>pods/</code> folders.
        </div>
      )}
      {pods.data?.map((pod) => (
        <Link key={pod.id} to={`/pods/${pod.id}`} className="card" style={{ display: "block" }}>
          <div className="row">
            <div>
              <div style={{ fontSize: 16, fontWeight: 600 }}>{pod.name}</div>
              <div className="muted">
                {pod.config.series_name} · {pod.config.language} · {pod.config.duration_seconds}s
              </div>
            </div>
            <span className="badge">{pod.config.style_profile}</span>
          </div>
        </Link>
      ))}
    </>
  );
}

function NewPodForm({
  onSubmit,
  loading,
  error,
}: {
  onSubmit: (v: { name: string; series_name: string; language: string }) => void;
  loading: boolean;
  error: string | null;
}) {
  const [name, setName] = useState("");
  const [seriesName, setSeriesName] = useState("");
  const [language, setLanguage] = useState("es");

  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ name, series_name: seriesName, language });
      }}
    >
      <div className="field">
        <label>Pod name (slug)</label>
        <input value={name} onChange={(e) => setName(e.target.value)} required minLength={1} />
      </div>
      <div className="field">
        <label>Series name (display)</label>
        <input value={seriesName} onChange={(e) => setSeriesName(e.target.value)} required />
      </div>
      <div className="field">
        <label>Language</label>
        <select value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option value="es">Español</option>
          <option value="en">English</option>
          <option value="pt">Português</option>
        </select>
      </div>
      {error && <div className="muted" style={{ color: "var(--err)" }}>{error}</div>}
      <button type="submit" disabled={loading}>
        {loading ? "Creating…" : "Create pod"}
      </button>
    </form>
  );
}

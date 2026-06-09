import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, subscribeToJob, type Job, type JobEvent } from "../api/client";
import { Button, Empty, ErrorState, Loading, StateBadge, useToast } from "../ui/primitives";
import { IcTrash } from "../ui/icons";

export function JobsPage() {
  const jobs = useQuery<Job[]>({
    queryKey: ["jobs"], queryFn: () => api.get("/jobs"), refetchInterval: 6_000,
  });

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Sistema</div>
          <h1>Trabajos</h1>
          <p className="sub">Renders y tareas en segundo plano, en tiempo real.</p>
        </div>
      </div>
      {jobs.isLoading && <Loading />}
      {jobs.isError && <ErrorState error={jobs.error} />}
      {jobs.data?.length === 0 && <Empty emoji="🛠️" title="Sin trabajos">Cuando lances un render aparecerá aquí.</Empty>}
      <div className="stack">{jobs.data?.map((j) => <JobCard key={j.id} job={j} />)}</div>
    </div>
  );
}

function JobCard({ job }: { job: Job }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [progress, setProgress] = useState(job.progress);
  const [message, setMessage] = useState(job.message);
  const [state, setState] = useState(job.state);
  const del = useMutation({
    mutationFn: () => api.delete(`/jobs/${job.id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["jobs"] }); toast.ok("Trabajo borrado"); },
    onError: (e) => toast.err("No se pudo borrar", (e as Error).message),
  });
  const finished = state !== "queued" && state !== "running";

  useEffect(() => {
    if (job.state !== "queued" && job.state !== "running") return;
    return subscribeToJob(job.id, {
      onEvent: (e: JobEvent) => {
        if (typeof e.progress === "number") setProgress(e.progress);
        if (typeof e.message === "string") setMessage(e.message);
        if (e.event === "running") setState("running");
        if (e.event === "completed") setState("succeeded");
        if (e.event === "failed") setState("failed");
        if (e.event === "cancelled") setState("cancelled");
      },
    });
  }, [job.id, job.state]);

  return (
    <div className="card card-pad">
      <div className="between">
        <div>
          <div style={{ fontWeight: 600 }}>{job.kind}</div>
          <div className="dim mono" style={{ fontSize: 11 }}>{job.id}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <StateBadge state={state} />
          {finished && (
            <Button size="sm" variant="ghost" loading={del.isPending} onClick={() => del.mutate()}><IcTrash /></Button>
          )}
        </div>
      </div>
      <div style={{ marginTop: 12 }}>
        <div className="progress"><i style={{ width: `${Math.round(progress * 100)}%` }} /></div>
        <div className="muted" style={{ marginTop: 7, fontSize: 12.5 }}>
          {message ?? "—"} · {Math.round(progress * 100)}%
        </div>
      </div>
      {job.error && <pre className="mono" style={{ color: "var(--red)", fontSize: 12, marginTop: 10, whiteSpace: "pre-wrap" }}>{job.error}</pre>}
    </div>
  );
}

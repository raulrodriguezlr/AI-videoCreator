import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, subscribeToJob, type Job, type JobEvent } from "../api/client";

export function JobsPage() {
  const jobs = useQuery<Job[]>({
    queryKey: ["jobs"],
    queryFn: () => api.get("/jobs"),
    refetchInterval: 5_000,
  });

  return (
    <>
      <h2 style={{ marginTop: 0 }}>Jobs</h2>
      {jobs.isLoading && <div className="muted">Loading…</div>}
      {jobs.data?.length === 0 && <div className="muted">No jobs yet.</div>}
      {jobs.data?.map((j) => (
        <JobCard key={j.id} job={j} />
      ))}
    </>
  );
}

function JobCard({ job }: { job: Job }) {
  // Subscribe to SSE for any in-flight job so the progress bar updates in real time.
  const [progress, setProgress] = useState(job.progress);
  const [message, setMessage] = useState(job.message);
  const [state, setState] = useState(job.state);

  useEffect(() => {
    if (job.state !== "queued" && job.state !== "running") return;
    const close = subscribeToJob(job.id, {
      onEvent: (e: JobEvent) => {
        if (typeof e.progress === "number") setProgress(e.progress);
        if (typeof e.message === "string") setMessage(e.message);
        if (e.event === "running") setState("running");
        if (e.event === "completed") setState("succeeded");
        if (e.event === "failed") setState("failed");
        if (e.event === "cancelled") setState("cancelled");
      },
    });
    return close;
  }, [job.id, job.state]);

  const badgeClass =
    state === "succeeded" ? "ok" : state === "failed" ? "err" : state === "running" ? "warn" : "";

  return (
    <div className="card">
      <div className="row">
        <div>
          <div style={{ fontWeight: 600 }}>{job.kind}</div>
          <div className="muted">{job.id}</div>
        </div>
        <span className={`badge ${badgeClass}`}>{state}</span>
      </div>
      <div style={{ marginTop: 10 }}>
        <div className="progress">
          <div style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
        <div className="muted" style={{ marginTop: 6 }}>
          {message ?? "(no message)"} · {Math.round(progress * 100)}%
        </div>
      </div>
      {job.error && <pre style={{ color: "var(--err)" }}>{job.error}</pre>}
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getRun, mediaUrl, subscribeToRun, type RunNodeState, type RunSnapshot,
} from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../ui/primitives";
import { IcCheck, IcFilm, IcRefresh, IcX } from "../ui/icons";

const POLL_MS = 3_000;

const STATE_LABEL: Record<RunNodeState, string> = {
  pending: "pendiente", running: "en curso", done: "completado", failed: "fallido", cancelled: "cancelado",
};
const STATE_TONE: Record<RunNodeState, "default" | "ok" | "warn" | "err" | "accent"> = {
  pending: "default", running: "accent", done: "ok", failed: "err", cancelled: "warn",
};

export function RunPage() {
  const { runId = "" } = useParams();
  const qc = useQueryClient();
  const [live, setLive] = useState(true);
  const sseFailedRef = useRef(false);

  const run = useQuery<RunSnapshot>({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    enabled: !!runId,
    refetchInterval: () => (live ? false : POLL_MS),
  });

  // Subscribe to SSE; on error, fall back to polling getRun every 3s.
  useEffect(() => {
    if (!runId) return;
    sseFailedRef.current = false;
    setLive(true);

    const stop = subscribeToRun(runId, {
      onEvent: (e) => {
        qc.setQueryData<RunSnapshot | undefined>(["run", runId], (prev) => {
          if (!prev) return prev;
          const nodes = { ...prev.nodes };
          if (e.node && nodes[e.node]) {
            const current = nodes[e.node];
            if (e.event === "node_running") {
              nodes[e.node] = { ...current, state: "running", error: null };
            } else if (e.event === "node_done") {
              nodes[e.node] = { ...current, state: "done", error: null };
            } else if (e.event === "node_retry") {
              nodes[e.node] = { ...current, state: "pending", retries_left: Math.max(0, current.retries_left - 1) };
            } else if (e.event === "node_failed") {
              nodes[e.node] = { ...current, state: "failed", error: e.error ?? current.error };
            } else if (e.event === "node_cancelled") {
              nodes[e.node] = { ...current, state: "cancelled" };
            }
          }
          let { is_complete, has_failures } = prev;
          if (e.event === "run_complete") {
            is_complete = true;
            has_failures = !!e.failed || prev.has_failures;
          }
          return { ...prev, nodes, is_complete, has_failures };
        });
        if (e.event === "run_complete") {
          // Final refetch to make sure state matches the server exactly.
          qc.invalidateQueries({ queryKey: ["run", runId] });
        }
      },
      onError: () => {
        if (sseFailedRef.current) return;
        sseFailedRef.current = true;
        setLive(false);
        qc.invalidateQueries({ queryKey: ["run", runId] });
      },
    });

    return () => stop();
  }, [runId, qc]);

  if (run.isLoading) return <div className="page"><Loading /></div>;
  if (run.isError || !run.data) return <div className="page"><ErrorState error={run.error} /></div>;

  const data = run.data;
  const entries = Object.entries(data.nodes);
  const total = entries.length;
  const done = entries.filter(([, n]) => n.state === "done").length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  // Stop polling once the run reaches a terminal state.
  const isFinished = data.is_complete;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Ejecución</div>
          <h1 className="mono" style={{ fontSize: 22 }}>{data.run_id}</h1>
          <p className="sub">Progreso del DAG en tiempo real{!live && !isFinished ? " (modo sondeo)" : ""}.</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {isFinished ? (
            data.has_failures
              ? <Badge tone="err"><IcX width={13} height={13} /> Con errores</Badge>
              : <Badge tone="ok"><IcCheck width={13} height={13} /> Completado</Badge>
          ) : (
            <Badge tone="accent" live><IcRefresh width={13} height={13} /> En ejecución</Badge>
          )}
        </div>
      </div>

      <div className="card card-pad run-summary" style={{ marginBottom: 22 }}>
        <div className="run-progress-wrap">
          <div className="run-progress-label">
            <span>Nodos completados</span>
            <span>{done} / {total}</span>
          </div>
          <div className="progress"><i style={{ width: `${pct}%` }} /></div>
        </div>
      </div>

      {isFinished && !data.has_failures && (data.video_url || data.artifacts.length > 0) && (
        <div className="card" style={{ marginBottom: 22 }}>
          <div className="card-head"><IcFilm width={16} height={16} /><h3>Resultado</h3></div>
          <div className="card-pad stack">
            {data.video_url && (
              <>
                <div className="stage">
                  <video src={mediaUrl(data.video_url)} controls preload="metadata" />
                </div>
                <div className="btn-row" style={{ justifyContent: "flex-end" }}>
                  <a className="btn sm" href={mediaUrl(data.video_url)} download target="_blank" rel="noreferrer">
                    Descargar vídeo
                  </a>
                </div>
              </>
            )}
            {data.artifacts.filter((a) => a !== data.video_url).length > 0 && (
              <div className="stack" style={{ gap: 8 }}>
                <div className="dim" style={{ fontSize: 11.5, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                  Artefactos
                </div>
                <div className="tag-list">
                  {data.artifacts.filter((a) => a !== data.video_url).map((a) => (
                    <a key={a} className="badge" href={mediaUrl(a)} target="_blank" rel="noreferrer"
                      style={{ cursor: "pointer" }}>
                      {a.split("/").pop()}
                    </a>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {total === 0 ? (
        <Empty emoji="🗺️" title="Sin nodos">Esta ejecución no tiene nodos registrados.</Empty>
      ) : (
        <div className="stack">
          {entries.map(([nodeId, node]) => (
            <div key={nodeId} className={`run-node-row ${node.state === "running" ? "is-running" : ""} ${node.state === "failed" ? "is-failed" : ""}`}>
              <div className="run-node-main">
                <span className="run-node-id">{nodeId}</span>
                {node.error && <span className="run-node-error">{node.error}</span>}
              </div>
              <div className="run-node-meta">
                {node.retries_left > 0 && node.state !== "done" && (
                  <Badge>{node.retries_left} reintentos</Badge>
                )}
                <Badge tone={STATE_TONE[node.state]} live={node.state === "running"}>
                  {STATE_LABEL[node.state]}
                </Badge>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

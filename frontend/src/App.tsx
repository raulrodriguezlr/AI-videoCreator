import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type HealthResponse } from "./api/client";

export function App() {
  const health = useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: () => api.get("/health"),
    refetchInterval: 15_000,
  });

  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>VideoCreator</h1>
        <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
          Pods
        </NavLink>
        <NavLink to="/jobs" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
          Jobs
        </NavLink>
        <div style={{ marginTop: "auto", paddingTop: 24 }}>
          <HealthBadge data={health.data} loading={health.isLoading} />
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}

function HealthBadge({ data, loading }: { data?: HealthResponse; loading: boolean }) {
  if (loading) return <span className="badge">checking…</span>;
  if (!data) return <span className="badge err">offline</span>;
  return (
    <div className="muted" style={{ fontSize: 12 }}>
      <div>
        <span className="badge ok">{data.status}</span> · {data.app_mode} · v{data.version}
      </div>
      <div style={{ marginTop: 6 }}>
        {Object.entries(data.components).map(([k, v]) => (
          <div key={k}>
            {k}: <span style={{ color: v === "configured" || v === "inprocess" ? "var(--ok)" : "var(--warn)" }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type HealthResponse, type LlmConfig } from "../api/client";
import { IcActivity, IcCloud, IcCpu, IcFilm, IcLaugh, IcLayout, IcMessageCircle, IcRadar, IcSliders } from "../ui/icons";

export function AppShell() {
  const location = useLocation();
  const health = useQuery<HealthResponse>({
    queryKey: ["health"], queryFn: () => api.get("/health"), refetchInterval: 20_000,
  });
  const llm = useQuery<LlmConfig>({
    queryKey: ["llm-config"], queryFn: () => api.get("/system/llm"), refetchInterval: 30_000,
  });
  const hf = useQuery<HiggsfieldBalance>({
    queryKey: ["hf-balance"], queryFn: () => api.get("/system/higgsfield/balance"),
    refetchInterval: 60_000,
  });

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <svg viewBox="0 0 24 24" fill="none"><path d="M9 6.5c0-.9 1-1.5 1.8-1l7 4.5c.7.5.7 1.5 0 2l-7 4.5c-.8.5-1.8-.1-1.8-1z" fill="#0A0B0F"/></svg>
          </span>
          <div>
            <div className="brand-name">Aurora</div>
            <div className="brand-sub">AI Video Studio</div>
          </div>
        </div>

        <div className="nav-section">Estudio</div>
        <NavLink to="/" end className={navCls}><IcFilm /> Pods</NavLink>
        <NavLink to="/templates" className={navCls}><IcLayout /> Plantillas</NavLink>
        <NavLink to="/director" className={navCls}><IcMessageCircle /> Director</NavLink>
        <NavLink to="/memes" className={navCls}><IcLaugh /> Memes</NavLink>
        <NavLink to="/recreations" className={navCls}><IcRadar /> Recreaciones</NavLink>
        <NavLink to="/jobs" className={navCls}><IcActivity /> Trabajos</NavLink>

        <div className="nav-section">Sistema</div>
        <NavLink to="/settings" className={navCls}><IcSliders /> Ajustes</NavLink>

        <div className="sidebar-foot">
          <LlmChip llm={llm.data} />
          <HiggsfieldChip data={hf.data} />
          <div className="muted" style={{ fontSize: 11.5, marginTop: 10, display: "flex", gap: 8, alignItems: "center" }}>
            <span className={`badge ${health.data ? "ok" : "err"}`}>
              <span className="dot" />{health.data ? health.data.status : "offline"}
            </span>
            <span className="dim mono">{health.data ? `${health.data.app_mode} · v${health.data.version}` : "—"}</span>
          </div>
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <div className="crumbs"><span className="cur">{routeLabel(location.pathname)}</span></div>
          <div className="topbar-spacer" />
          {llm.data && (
            <span className="badge accent" title={`Proveedor LLM: ${llm.data.provider}`}>
              {llm.data.provider === "ollama" ? <IcCpu width={13} height={13} /> : <IcCloud width={13} height={13} />}
              {llm.data.provider === "ollama" ? llm.data.ollama_model : llm.data.gemini_model}
            </span>
          )}
        </div>
        <div key={location.pathname} className="fade-in" style={{ flex: 1 }}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function LlmChip({ llm }: { llm?: LlmConfig }) {
  if (!llm) return null;
  const isOllama = llm.provider === "ollama";
  const healthy = isOllama ? llm.ollama.running && llm.ollama.current_model_installed : llm.gemini_key_present;
  return (
    <div className="statpill">
      {isOllama ? <IcCpu width={16} height={16} /> : <IcCloud width={16} height={16} />}
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="label">Motor de texto</div>
        <div className="val" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {isOllama ? "Ollama" : "Gemini"}
        </div>
      </div>
      <span className="dot" style={{ width: 8, height: 8, borderRadius: "50%", background: healthy ? "var(--mint)" : "var(--amber)" }} />
    </div>
  );
}

type HiggsfieldBalance = {
  available: boolean; credits: number | null; plan: string | null; detail: string;
};

function HiggsfieldChip({ data }: { data?: HiggsfieldBalance }) {
  if (!data?.available) return null;  // hide until `hf auth login` is done
  return (
    <div className="statpill" style={{ marginTop: 8 }} title={data.detail}>
      <IcCloud width={16} height={16} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="label">Higgsfield{data.plan ? ` · ${data.plan}` : ""}</div>
        <div className="val">{data.credits != null ? `${data.credits.toFixed(2)} cr` : "—"}</div>
      </div>
      <span className="dot" style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--mint)" }} />
    </div>
  );
}

const navCls = ({ isActive }: { isActive: boolean }) => `nav-link ${isActive ? "active" : ""}`;

function routeLabel(path: string): string {
  if (path === "/") return "Pods";
  if (path.startsWith("/jobs")) return "Trabajos";
  if (path.startsWith("/settings")) return "Ajustes";
  if (path.startsWith("/create")) return "Crear pod";
  if (path.startsWith("/templates")) return "Plantillas";
  if (path.startsWith("/director")) return "Director";
  if (path.startsWith("/memes")) return "Memes";
  if (path.startsWith("/recreations")) return "Recreaciones";
  if (path.startsWith("/runs/")) return "Ejecución";
  if (path.includes("/episodes/")) return "Episodio";
  if (path.startsWith("/pods/")) return "Pod";
  return "Aurora";
}

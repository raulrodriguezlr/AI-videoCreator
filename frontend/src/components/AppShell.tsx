import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { api, type HealthResponse, type LlmConfig, type AppConfig } from "../api/client";
import {
  IcActivity, IcCloud, IcCpu, IcFilm, IcLaugh, IcLayout, IcMenu, IcMessageCircle,
  IcMoon, IcRadar, IcSliders, IcSparkles, IcSun, IcX,
} from "../ui/icons";
import { useTheme } from "../ui/useTheme";

const NAV_ITEMS: { to: string; end?: boolean; label: string; icon: JSX.Element }[] = [
  { to: "/", end: true, label: "Inicio", icon: <IcSparkles /> },
  { to: "/pods", label: "Pods", icon: <IcFilm /> },
  { to: "/templates", label: "Plantillas", icon: <IcLayout /> },
  { to: "/director", label: "Director", icon: <IcMessageCircle /> },
  { to: "/memes", label: "Memes", icon: <IcLaugh /> },
  { to: "/recreations", label: "Recreaciones", icon: <IcRadar /> },
  { to: "/jobs", label: "Trabajos", icon: <IcActivity /> },
];

export function AppShell() {
  const location = useLocation();
  const { theme, toggle } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
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
  const appConfig = useQuery<AppConfig>({
    queryKey: ["app-config"], queryFn: () => api.get("/system/config"),
  });

  const items = appConfig.data?.channels_feature_enabled
    ? [...NAV_ITEMS, { to: "/channels", label: "Canales", icon: <IcCloud width={16} height={16} /> }]
    : NAV_ITEMS;

  return (
    <div className="shell">
      <header className="topnav">
        <div className="brand">
          <span className="brand-mark">
            <svg viewBox="0 0 24 24" fill="none"><path d="M9 6.5c0-.9 1-1.5 1.8-1l7 4.5c.7.5.7 1.5 0 2l-7 4.5c-.8.5-1.8-.1-1.8-1z" fill="#fff"/></svg>
          </span>
          <div>
            <div className="brand-name">Estudio</div>
            <div className="brand-sub">AI Video Studio</div>
          </div>
        </div>

        <nav className="topnav-links">
          {items.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={navCls}>
              {({ isActive }) => (
                <>
                  {item.icon} {item.label}
                  {isActive && (
                    <motion.span layoutId="nav-indicator" className="nav-link-indicator" transition={{ type: "spring", stiffness: 420, damping: 34 }} />
                  )}
                </>
              )}
            </NavLink>
          ))}
          <NavLink to="/settings" className={navCls}>
            {({ isActive }) => (
              <>
                <IcSliders /> Ajustes
                {isActive && (
                  <motion.span layoutId="nav-indicator" className="nav-link-indicator" transition={{ type: "spring", stiffness: 420, damping: 34 }} />
                )}
              </>
            )}
          </NavLink>
        </nav>

        <div className="topnav-right">
          <LlmChip llm={llm.data} />
          <HiggsfieldChip data={hf.data} />
          <span className={`badge ${health.data ? "ok" : "err"}`} title="Estado del backend">
            <span className="dot" />{health.data ? health.data.app_mode : "offline"}
          </span>
          <button className="theme-toggle" onClick={toggle} aria-label={theme === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro"} title={theme === "dark" ? "Tema claro" : "Tema oscuro"}>
            {theme === "dark" ? <IcSun /> : <IcMoon />}
          </button>
          <button className="nav-burger" onClick={() => setMenuOpen((v) => !v)} aria-label="Abrir menú" aria-expanded={menuOpen}>
            {menuOpen ? <IcX /> : <IcMenu />}
          </button>
        </div>
      </header>

      {menuOpen && (
        <div className="mobile-menu">
          <div className="stack" style={{ gap: 4 }}>
            {items.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end} className={navCls} onClick={() => setMenuOpen(false)}>
                {item.icon} {item.label}
              </NavLink>
            ))}
            <NavLink to="/settings" className={navCls} onClick={() => setMenuOpen(false)}>
              <IcSliders /> Ajustes
            </NavLink>
          </div>
        </div>
      )}

      <main className="main">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            style={{ flex: 1, display: "flex", flexDirection: "column" }}
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}

function LlmChip({ llm }: { llm?: LlmConfig }) {
  if (!llm) return null;
  const isOllama = llm.provider === "ollama";
  const healthy = isOllama ? llm.ollama.running && llm.ollama.current_model_installed : llm.gemini_key_present;
  return (
    <div className="statpill compact" title="Motor de texto">
      {isOllama ? <IcCpu width={15} height={15} /> : <IcCloud width={15} height={15} />}
      <div style={{ minWidth: 0 }}>
        <div className="val" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 96 }}>
          {isOllama ? "Ollama" : "Gemini"}
        </div>
      </div>
      <span className="dot" style={{ width: 7, height: 7, borderRadius: "50%", background: healthy ? "var(--mint)" : "var(--amber)" }} />
    </div>
  );
}

type HiggsfieldBalance = {
  available: boolean; credits: number | null; plan: string | null; detail: string;
};

function HiggsfieldChip({ data }: { data?: HiggsfieldBalance }) {
  if (!data?.available) return null;  // hide until `hf auth login` is done
  return (
    <div className="statpill compact" title={data.detail}>
      <IcCloud width={15} height={15} />
      <div className="val">{data.credits != null ? `${data.credits.toFixed(0)} cr` : "—"}</div>
    </div>
  );
}

const navCls = ({ isActive }: { isActive: boolean }) => `nav-link ${isActive ? "active" : ""}`;

// Reusable design-system primitives. Pure presentation — keep page code lean.
import {
  createContext, useCallback, useContext, useEffect, useState, type ReactNode, type ButtonHTMLAttributes,
} from "react";
import { motion } from "framer-motion";
import { IcCheck, IcX } from "./icons";

// --------------------------------------------------------------------------
// Button
// --------------------------------------------------------------------------
type Variant = "default" | "primary" | "mint" | "ghost" | "danger";
interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
}
export function Button({ variant = "default", size = "md", loading, children, className = "", disabled, ...rest }: BtnProps) {
  const cls = ["btn", variant !== "default" ? variant : "", size === "sm" ? "sm" : "", className]
    .filter(Boolean).join(" ");
  return (
    <button className={cls} disabled={disabled || loading} {...rest}>
      {loading && <span className="spinner" style={{ width: 14, height: 14 }} />}
      {children}
    </button>
  );
}

// --------------------------------------------------------------------------
// Badge
// --------------------------------------------------------------------------
export function Badge({ tone = "default", live, children }: {
  tone?: "default" | "ok" | "warn" | "err" | "accent" | "pink" | "violet"; live?: boolean; children: ReactNode;
}) {
  return (
    <span className={`badge ${tone} ${live ? "live" : ""}`}>
      {live && <span className="dot" />}{children}
    </span>
  );
}

const STATE_TONE: Record<string, "default" | "ok" | "warn" | "err" | "accent"> = {
  ready: "ok", published: "ok", succeeded: "ok",
  rendering: "accent", running: "accent", scripting: "accent", reviewing: "accent", queued: "accent",
  failed: "err", cancelled: "err", draft: "default", pending: "default",
};
export function StateBadge({ state }: { state: string }) {
  const tone = STATE_TONE[state] ?? "default";
  const live = state === "rendering" || state === "running";
  return <Badge tone={tone} live={live}>{state}</Badge>;
}

// --------------------------------------------------------------------------
// Spinner / loading / empty
// --------------------------------------------------------------------------
export const Spinner = ({ lg }: { lg?: boolean }) => <span className={`spinner ${lg ? "lg" : ""}`} />;

/** Rotating, playful copy for long-running renders. Kept short — one thought each. */
const LOADING_LINES = [
  "Convenciendo a los píxeles de cooperar…",
  "Negociando con el algoritmo…",
  "Afilando los fotogramas…",
  "Calentando la sala de guion…",
  "Puliendo los últimos detalles con cariño…",
  "Sincronizando labios y buena suerte…",
  "Persuadiendo a la GPU con café…",
  "Enseñándole al modelo el sentido del humor…",
];

/** Clapperboard loader — the sticks clap shut on a loop. Domain-flavoured
 * stand-in for the old generic ring spinner. */
export function ClapperLoader({ size = 56 }: { size?: number }) {
  return (
    <svg className="clapper-loader" width={size} height={size} viewBox="0 0 56 56" fill="none" aria-hidden>
      <rect x="8" y="20" width="40" height="28" rx="4" fill="var(--surface-2)" stroke="var(--border-strong)" strokeWidth="2" />
      <path d="M8 24l3-10h6l-3 10z" fill="var(--accent)" />
      <path d="M20 24l3-10h6l-3 10z" fill="var(--text)" opacity="0.85" />
      <path d="M32 24l3-10h6l-3 10z" fill="var(--accent)" />
      <motion.g
        style={{ transformOrigin: "8px 20px" }}
        animate={{ rotate: [0, -22, 0] }}
        transition={{ duration: 1.1, repeat: Infinity, repeatDelay: 0.35, ease: "easeInOut" }}
      >
        <path d="M8 20l3-10h6l-3 10z" fill="var(--accent)" />
        <path d="M20 20l3-10h6l-3 10z" fill="var(--text)" opacity="0.85" />
        <path d="M32 20l3-10h6l-3 10z" fill="var(--accent)" />
        <rect x="8" y="14" width="40" height="6" rx="2" fill="var(--surface-2)" stroke="var(--border-strong)" strokeWidth="2" />
      </motion.g>
    </svg>
  );
}

/** Audio-wave loader — bars dance to a silent beat. Use for audio/voice steps. */
export function WaveLoader() {
  return (
    <div className="wave-loader" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <i key={i} style={{ animationDelay: `${i * 0.11}s` }} />
      ))}
    </div>
  );
}

/** Full loading block: themed loader + rotating message. Pass `variant="wave"`
 * for audio-flavoured steps; defaults to the clapperboard. */
export function Loading({ lg, variant = "clapper", messages }: {
  lg?: boolean; variant?: "clapper" | "wave"; messages?: string[];
}) {
  const lines = messages ?? LOADING_LINES;
  const [i, setI] = useState(() => Math.floor(Math.random() * lines.length));
  useEffect(() => {
    const id = setInterval(() => setI((v) => (v + 1) % lines.length), 2200);
    return () => clearInterval(id);
  }, [lines.length]);
  return (
    <div className="center-load">
      {variant === "wave" ? <WaveLoader /> : <ClapperLoader size={lg ? 64 : 48} />}
      <motion.p key={i} className="center-load-msg" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        {lines[i]}
      </motion.p>
    </div>
  );
}

export function Empty({ emoji = "✨", title, children, action }: {
  emoji?: string; title: string; children?: ReactNode; action?: ReactNode;
}) {
  return (
    <motion.div className="empty" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
      <div className="emoji">{emoji}</div>
      <div><h3>{title}</h3>{children && <p className="muted" style={{ marginTop: 6 }}>{children}</p>}</div>
      {action}
    </motion.div>
  );
}

// --------------------------------------------------------------------------
// Skeleton — shimmer placeholder while a query is loading
// --------------------------------------------------------------------------
export function Skeleton({ lines = 3, card }: { lines?: number; card?: boolean }) {
  if (card) return <div className="skeleton skeleton-card" />;
  return (
    <div>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton skeleton-text" />
      ))}
    </div>
  );
}

/** Grid of shimmer cards — drop-in placeholder for `.grid.cols` while a list query loads. */
export function SkeletonGrid({ count = 6 }: { count?: number }) {
  return (
    <div className="grid cols">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="skeleton skeleton-card" />
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------
// Tabs
// --------------------------------------------------------------------------
export function Tabs<T extends string>({ value, onChange, tabs }: {
  value: T; onChange: (t: T) => void; tabs: { id: T; label: string; count?: number }[];
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id}
          className={`tab ${value === t.id ? "active" : ""}`} onClick={() => onChange(t.id)}>
          {t.label}
          {t.count !== undefined && <span className="count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------
// Field wrappers
// --------------------------------------------------------------------------
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

// --------------------------------------------------------------------------
// Combobox — free-text input with curated suggestions (click or keyboard)
// --------------------------------------------------------------------------
export function Combobox({ value, onChange, options, placeholder, icon }: {
  value: string; onChange: (v: string) => void; options: string[]; placeholder?: string; icon?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [activeIx, setActiveIx] = useState(-1);

  const query = value.trim().toLowerCase();
  const filtered = query
    ? options.filter((o) => o.toLowerCase().includes(query))
    : options;

  const commit = (v: string) => { onChange(v); setOpen(false); setActiveIx(-1); };

  return (
    <div className="combobox">
      <input
        className="input"
        value={value}
        placeholder={placeholder}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActiveIx(-1); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (!open) return;
          if (e.key === "ArrowDown") { e.preventDefault(); setActiveIx((i) => Math.min(i + 1, filtered.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActiveIx((i) => Math.max(i - 1, 0)); }
          else if (e.key === "Enter" && activeIx >= 0 && filtered[activeIx]) { e.preventDefault(); commit(filtered[activeIx]); }
          else if (e.key === "Escape") setOpen(false);
        }}
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
      />
      {open && (
        <div className="combobox-list" role="listbox">
          {filtered.length === 0 && (
            <div className="combobox-empty">Sin coincidencias — se usará tu texto libre.</div>
          )}
          {filtered.map((opt, i) => (
            <button
              key={opt}
              type="button"
              role="option"
              aria-selected={i === activeIx}
              className={`combobox-option ${i === activeIx ? "active" : ""}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => commit(opt)}
            >
              {icon && <span className="ic">{icon}</span>}
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Modal
// --------------------------------------------------------------------------
export function Modal({ title, onClose, children, footer, wide }: {
  title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  return (
    <div className="overlay" onClick={onClose}>
      <div className={`modal ${wide ? "wide" : ""}`} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal>
        <div className="modal-head between">
          <h2>{title}</h2>
          <Button variant="ghost" size="sm" className="icon" onClick={onClose} aria-label="Cerrar"><IcX /></Button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Callout — inline warning/info/error banner (wizard steps, guardrails)
// --------------------------------------------------------------------------
export function Callout({ tone = "info", icon, children }: {
  tone?: "info" | "warn" | "err"; icon?: ReactNode; children: ReactNode;
}) {
  return (
    <div className={`callout ${tone}`}>
      {icon}
      <div>{children}</div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Toasts (context + hook)
// --------------------------------------------------------------------------
interface Toast { id: number; tone: "ok" | "err" | "info"; title: string; msg?: string }
interface ToastApi { push: (t: Omit<Toast, "id">) => void; ok: (title: string, msg?: string) => void; err: (title: string, msg?: string) => void; }
const ToastCtx = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const remove = useCallback((id: number) => setItems((x) => x.filter((t) => t.id !== id)), []);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { ...t, id }]);
    setTimeout(() => remove(id), 4200);
  }, [remove]);
  const api: ToastApi = {
    push,
    ok: (title, msg) => push({ tone: "ok", title, msg }),
    err: (title, msg) => push({ tone: "err", title, msg }),
  };
  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div className="toasts">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`} onClick={() => remove(t.id)}>
            <span style={{ marginTop: 1 }}>{t.tone === "ok" ? <IcCheck /> : <IcX />}</span>
            <div><div className="t-title">{t.title}</div>{t.msg && <div className="t-msg">{t.msg}</div>}</div>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export function useToast(): ToastApi {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}

// --------------------------------------------------------------------------
// Error surface for queries
// --------------------------------------------------------------------------
export function ErrorState({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : "Algo salió mal";
  return <Empty emoji="⚠️" title="No se pudo cargar">{msg}</Empty>;
}

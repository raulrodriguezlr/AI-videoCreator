// Reusable design-system primitives. Pure presentation — keep page code lean.
import {
  createContext, useCallback, useContext, useState, type ReactNode, type ButtonHTMLAttributes,
} from "react";
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
export const Loading = () => <div className="center-load"><Spinner lg /></div>;

export function Empty({ emoji = "✨", title, children, action }: {
  emoji?: string; title: string; children?: ReactNode; action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="emoji">{emoji}</div>
      <div><h3>{title}</h3>{children && <p className="muted" style={{ marginTop: 6 }}>{children}</p>}</div>
      {action}
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
// Modal
// --------------------------------------------------------------------------
export function Modal({ title, onClose, children, footer }: {
  title: string; onClose: () => void; children: ReactNode; footer?: ReactNode;
}) {
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal>
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

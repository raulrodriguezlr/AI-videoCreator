import { useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  getDashboard, mediaUrl, getAppConfig, listUploads,
  type DashboardEpisode, type DashboardResponse, type DashboardShort,
  type AppConfig, type PublishJob,
} from "../api/client";
import { Badge, Button, Empty, ErrorState, Loading } from "../ui/primitives";
import {
  IcArrowRight, IcCalendar, IcFilm, IcLayout, IcPlay, IcPlus, IcRocket, IcSparkles, IcWand,
} from "../ui/icons";

export function DashboardPage() {
  const nav = useNavigate();
  const dash = useQuery<DashboardResponse>({ queryKey: ["dashboard"], queryFn: getDashboard });

  if (dash.isLoading) return <div className="page"><Loading /></div>;
  if (dash.isError || !dash.data) return <div className="page"><ErrorState error={dash.error} /></div>;

  const { counts, recent_episodes, recent_shorts } = dash.data;
  const isEmpty = counts.pods === 0 && counts.episodes === 0;

  return (
    <div className="page">
      <section className="dash-hero">
        <div className="dash-hero-glow" aria-hidden />
        <div className="dash-hero-inner">
          <div className="dash-eyebrow"><IcSparkles width={15} height={15} /> Aurora · AI Video Studio</div>
          <h1 className="dash-title">De la idea al short,<br />con un solo motor.</h1>
          <p className="dash-lede">
            Genera episodios completos con IA, multiplícalos en shorts verticales y publícalos.
            Local-first, multi-proveedor, sin fricción.
          </p>
          <div className="btn-row" style={{ marginTop: 22 }}>
            <Button variant="mint" onClick={() => nav("/create")}><IcPlus /> Nuevo pod</Button>
            <Button onClick={() => nav("/templates")}><IcLayout /> Plantillas</Button>
            <Button variant="ghost" onClick={() => nav("/director")}><IcWand /> Director</Button>
          </div>
        </div>
      </section>

      <TodaySection />

      <div className="dash-stats">
        <StatCard label="Pods" value={counts.pods} tone="accent" icon={<IcFilm width={18} height={18} />} onClick={() => nav("/pods")} />
        <StatCard label="Episodios" value={counts.episodes} tone="violet" icon={<IcPlay width={18} height={18} />} onClick={() => nav("/pods")} />
        <StatCard label="Shorts" value={counts.shorts} tone="pink" icon={<IcRocket width={18} height={18} />} onClick={() => nav("/pods")} />
        <StatCard label="En curso" value={counts.jobs_running} tone="mint" icon={<IcArrowRight width={18} height={18} />} onClick={() => nav("/jobs")} live={counts.jobs_running > 0} />
      </div>

      {isEmpty ? (
        <div style={{ marginTop: 28 }}>
          <Empty emoji="✨" title="Lienzo en blanco, ideas infinitas">
            Crea tu primer pod y en minutos tendrás episodios y shorts esperando aquí mismo.
          </Empty>
        </div>
      ) : (
        <>
          <SectionHead title="Episodios recientes" hint="Lo último que has renderizado" onMore={() => nav("/pods")} />
          {recent_episodes.length > 0 ? (
            <div className="dash-rail">
              {recent_episodes.map((ep) => (
                <EpisodeCard key={ep.id} ep={ep} onOpen={() => nav(`/pods/${ep.pod_id}/episodes/${ep.id}`)} />
              ))}
            </div>
          ) : (
            <p className="muted" style={{ fontSize: 13 }}>Aún no hay episodios renderizados.</p>
          )}

          <SectionHead title="Shorts recientes" hint="Verticales listos para publicar" onMore={() => nav("/pods")} />
          {recent_shorts.length > 0 ? (
            <div className="dash-rail">
              {recent_shorts.map((s) => (
                <ShortCard key={s.id} short={s} onOpen={() => nav(`/pods/${s.pod_id}`)} />
              ))}
            </div>
          ) : (
            <p className="muted" style={{ fontSize: 13 }}>Aún no hay shorts. Multiplica un episodio para crearlos.</p>
          )}
        </>
      )}
    </div>
  );
}

function StatCard({ label, value, tone, icon, onClick, live }: {
  label: string; value: number; tone: "accent" | "violet" | "pink" | "mint";
  icon: React.ReactNode; onClick: () => void; live?: boolean;
}) {
  return (
    <button className={`stat-card tone-${tone}`} onClick={onClick}>
      <span className="stat-icon">{icon}</span>
      <span className="stat-value">{value}{live && <span className="stat-live" />}</span>
      <span className="stat-label">{label}</span>
    </button>
  );
}

function SectionHead({ title, hint, onMore }: { title: string; hint: string; onMore: () => void }) {
  return (
    <div className="dash-section-head">
      <div>
        <h2>{title}</h2>
        <span className="dim" style={{ fontSize: 12.5 }}>{hint}</span>
      </div>
      <button className="btn ghost sm" onClick={onMore}>Ver todo <IcArrowRight width={14} height={14} /></button>
    </div>
  );
}

/** Hover-to-play preview: shows a poster frame, plays the muted video on hover. */
function EpisodeCard({ ep, onOpen }: { ep: DashboardEpisode; onOpen: () => void }) {
  const vid = useRef<HTMLVideoElement>(null);
  const hasVideo = !!ep.video_url;
  return (
    <button className="ep-card" onClick={onOpen}
      onMouseEnter={() => vid.current?.play().catch(() => {})}
      onMouseLeave={() => { if (vid.current) { vid.current.pause(); vid.current.currentTime = 0; } }}>
      <div className="ep-thumb">
        {ep.thumb_url && <img src={mediaUrl(ep.thumb_url)} alt="" loading="lazy" />}
        {hasVideo && (
          <video ref={vid} src={mediaUrl(ep.video_url!)} muted loop playsInline preload="none"
            className={ep.thumb_url ? "ep-thumb-hover" : ""} />
        )}
        {!ep.thumb_url && !hasVideo && <span className="ep-thumb-ic"><IcFilm width={30} height={30} /></span>}
        <span className="ep-num">#{String(ep.number).padStart(2, "0")}</span>
      </div>
      <div className="ep-meta">
        <span className="ep-title">{ep.title}</span>
        <span className="ep-pod">{ep.pod_name}</span>
      </div>
    </button>
  );
}

function ShortCard({ short, onOpen }: { short: DashboardShort; onOpen: () => void }) {
  const vid = useRef<HTMLVideoElement>(null);
  return (
    <button className="short-card" onClick={onOpen}
      onMouseEnter={() => vid.current?.play().catch(() => {})}
      onMouseLeave={() => { if (vid.current) { vid.current.pause(); vid.current.currentTime = 0; } }}>
      <div className="short-thumb">
        {short.video_url
          ? <video ref={vid} src={mediaUrl(short.video_url)} muted loop playsInline preload="none" />
          : <span className="ep-thumb-ic"><IcRocket width={26} height={26} /></span>}
        <span className="short-dur">{Math.round(short.duration_s)}s</span>
      </div>
      <div className="ep-meta">
        <span className="ep-title">{short.hook_text ?? "Short"}</span>
        <span className="ep-pod">{short.pod_name}</span>
      </div>
    </button>
  );
}

// "Hoy": what's scheduled/queued for today — only when the channels feature is
// on. An empty day nudges toward making a short instead of showing nothing.
const PLATFORM_TONE: Record<string, "ok" | "warn" | "err" | "accent"> = {
  youtube: "err", tiktok: "accent", instagram: "warn",
};

function TodaySection() {
  const cfg = useQuery<AppConfig>({ queryKey: ["app-config"], queryFn: getAppConfig });
  const enabled = cfg.data?.channels_feature_enabled ?? false;
  const uploads = useQuery<PublishJob[]>({
    queryKey: ["channel-uploads"], queryFn: listUploads,
    refetchInterval: 15_000, enabled,
  });

  if (!enabled) return null;

  const now = new Date();
  const isToday = (iso: string | null) => {
    if (!iso) return false;
    const d = new Date(iso);
    return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()
      && d.getDate() === now.getDate();
  };
  const jobs = uploads.data ?? [];
  const today = jobs.filter((j) => isToday(j.scheduled_at));
  const active = jobs.filter((j) => j.status === "pending" || j.status === "uploading");

  return (
    <section className="card" style={{ marginBottom: 22 }}>
      <div className="card-head between">
        <h2><IcCalendar width={17} height={17} style={{ verticalAlign: "-3px", marginRight: 6 }} />Hoy</h2>
        <Link to="/calendar" className="btn ghost sm">Ver calendario <IcArrowRight width={15} height={15} /></Link>
      </div>
      <div className="card-pad stack" style={{ gap: 10 }}>
        {today.length === 0 && active.length === 0 && (
          <div className="between" style={{ fontSize: 14, alignItems: "center" }}>
            <span className="muted">Hoy no sale nada programado. ¿Un short rápido? 🎬</span>
            <Link to="/recreations" className="btn primary sm"><IcSparkles width={15} height={15} /> Crear</Link>
          </div>
        )}
        {today.map((j) => (
          <div key={j.id} className="between" style={{ fontSize: 13 }}>
            <span>
              <strong>{new Date(j.scheduled_at!).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}</strong>
              {" · "}{j.source === "short" ? "Short" : "Episodio"}
            </span>
            <Badge tone={PLATFORM_TONE[j.platform] ?? "default"}>{j.platform}</Badge>
          </div>
        ))}
        {active.length > 0 && (
          <div className="muted" style={{ fontSize: 12.5 }}>
            {active.length} subida(s) en cola / subiendo ahora mismo.
          </div>
        )}
      </div>
    </section>
  );
}

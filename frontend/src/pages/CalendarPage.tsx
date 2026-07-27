import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  listUploads, getAppConfig, api,
  type PublishJob, type AppConfig, type Pod,
} from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../ui/primitives";
import { IcCalendar } from "../ui/icons";

// The cadence baseline from docs/CHANNEL_STRATEGY.md: one short per day at a
// Spain/LATAM prime-time slot. The calendar surfaces these as dotted "suggested"
// slots on any day that has no publish job yet, so an empty day nudges instead
// of just looking empty.
const SUGGESTED_HOUR = 20; // 20:00 ES prime
const SUGGESTED_LABEL = "20:00";

const DAY_NAMES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const PLATFORM_TONE: Record<string, "ok" | "warn" | "err" | "accent"> = {
  youtube: "err", tiktok: "accent", instagram: "warn",
};
const STATUS_TONE: Record<PublishJob["status"], "ok" | "warn" | "err" | "default"> = {
  published: "ok", uploading: "warn", pending: "default", error: "err",
};

function startOfWeek(base: Date): Date {
  const d = new Date(base);
  const dow = (d.getDay() + 6) % 7; // Mon=0
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - dow);
  return d;
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate();
}

export function CalendarPage() {
  const cfg = useQuery<AppConfig>({ queryKey: ["app-config"], queryFn: getAppConfig });
  const enabled = cfg.data?.channels_feature_enabled ?? false;

  const [weekOffset, setWeekOffset] = useState(0);
  const uploads = useQuery<PublishJob[]>({
    queryKey: ["channel-uploads"], queryFn: listUploads,
    refetchInterval: 15_000, enabled,
  });
  const pods = useQuery<Pod[]>({
    queryKey: ["pods"], queryFn: () => api.get("/pods"), enabled,
  });

  const weekStart = useMemo(() => {
    const s = startOfWeek(new Date());
    s.setDate(s.getDate() + weekOffset * 7);
    return s;
  }, [weekOffset]);

  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => {
      const d = new Date(weekStart);
      d.setDate(d.getDate() + i);
      return d;
    }),
    [weekStart],
  );

  if (cfg.data && !enabled) {
    return (
      <div className="page">
        <Empty emoji="🔒" title="Calendario desactivado">
          Se activa junto al <strong>Centro de canales</strong> en{" "}
          <strong>Ajustes → Funciones experimentales</strong>.
        </Empty>
      </div>
    );
  }

  const jobs = uploads.data ?? [];
  const scheduled = jobs.filter((j) => j.scheduled_at);
  const unscheduled = jobs.filter((j) => !j.scheduled_at);
  const firstPod = pods.data?.[0];
  const createLink = firstPod ? `/pods/${firstPod.id}` : "/pods";

  const weekLabel = `${days[0].toLocaleDateString("es", { day: "numeric", month: "short" })} – ${days[6].toLocaleDateString("es", { day: "numeric", month: "short" })}`;

  return (
    <div className="page">
      <div className="page-head between">
        <div>
          <div className="eyebrow">Publicación</div>
          <h1>Calendario</h1>
          <p className="sub">Tus subidas programadas y huecos sugeridos según tu cadencia (1 short/día).</p>
        </div>
        <div className="btn-row" style={{ alignItems: "center", gap: 10 }}>
          <button className="btn ghost sm" onClick={() => setWeekOffset((w) => w - 1)}>←</button>
          <span className="mono" style={{ minWidth: 130, textAlign: "center" }}>
            {weekOffset === 0 ? "Esta semana" : weekLabel}
          </span>
          <button className="btn ghost sm" onClick={() => setWeekOffset((w) => w + 1)}>→</button>
        </div>
      </div>

      {uploads.isLoading && <Loading />}
      {uploads.isError && <ErrorState error={uploads.error} />}

      {uploads.data && (
        <div className="cal-grid">
          {days.map((day, i) => {
            const dayJobs = scheduled.filter((j) => sameDay(new Date(j.scheduled_at!), day));
            const isToday = sameDay(day, new Date());
            return (
              <motion.div
                key={day.toISOString()}
                className={`cal-col${isToday ? " cal-today" : ""}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.03 }}
              >
                <div className="cal-col-head">
                  <span className="cal-dow">{DAY_NAMES[i]}</span>
                  <span className="cal-date">{day.getDate()}</span>
                </div>
                <div className="cal-slots">
                  {dayJobs.map((j) => (
                    <div key={j.id} className="cal-job">
                      <div className="between" style={{ gap: 6 }}>
                        <Badge tone={PLATFORM_TONE[j.platform] ?? "default"}>{j.platform}</Badge>
                        <Badge tone={STATUS_TONE[j.status]}>{j.status}</Badge>
                      </div>
                      <div className="cal-job-time">
                        {new Date(j.scheduled_at!).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}
                        {" · "}{j.source === "short" ? "Short" : "Episodio"}
                      </div>
                    </div>
                  ))}
                  {dayJobs.length === 0 && (
                    <Link to={createLink} className="cal-suggest" title="Crear contenido para este hueco">
                      <IcCalendar width={15} height={15} />
                      <span>Hueco {SUGGESTED_LABEL}</span>
                      <span className="cal-suggest-cta">+ crear</span>
                    </Link>
                  )}
                </div>
              </motion.div>
            );
          })}
        </div>
      )}

      {unscheduled.length > 0 && (
        <div className="card" style={{ marginTop: 20 }}>
          <div className="card-head"><h2>Sin programar</h2></div>
          <div className="card-pad stack" style={{ gap: 8 }}>
            {unscheduled.map((j) => (
              <div key={j.id} className="between" style={{ fontSize: 13 }}>
                <span>{j.source === "short" ? "Short" : "Episodio"} · <span className="mono">{j.source_id.slice(0, 8)}</span></span>
                <div className="btn-row" style={{ gap: 6 }}>
                  <Badge tone={PLATFORM_TONE[j.platform] ?? "default"}>{j.platform}</Badge>
                  <Badge tone={STATUS_TONE[j.status]}>{j.status}</Badge>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

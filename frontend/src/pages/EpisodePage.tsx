import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api, getTemplate, startRun,
  type EpisodeDetail, type ProviderCatalogEntry, type Script, type SeoMetadata,
} from "../api/client";
import { MediaViewer } from "../components/MediaViewer";
import {
  Badge, Button, ErrorState, Field, Loading, StateBadge, useToast,
} from "../ui/primitives";
import { IcEdit, IcRocket } from "../ui/icons";

export function EpisodePage() {
  const { podId = "", episodeId = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();

  const detail = useQuery<EpisodeDetail>({
    queryKey: ["episode-detail", episodeId],
    queryFn: () => api.get(`/pods/${podId}/episodes/${episodeId}/detail`),
  });
  const providers = useQuery<ProviderCatalogEntry[]>({
    queryKey: ["provider-catalog"], queryFn: () => api.get("/providers/catalog"),
  });
  const anyAvailable = (providers.data ?? []).some((p) => p.available);

  const toast = useToast();

  const multiplyRun = useMutation({
    mutationFn: async () => {
      if (!detail.data) throw new Error("Datos no cargados");
      const template = await getTemplate("multiply-full");
      const spec = template.dag;
      const master = spec.nodes.find((n) => n.id === "master");
      if (master) {
        master.params = { ...master.params, concept: detail.data.episode.title };
      }
      return startRun(spec);
    },
    onSuccess: (run) => { toast.ok("Multiplicación iniciada"); nav(`/runs/${run.run_id}`); },
    onError: (e) => toast.err("No se pudo iniciar", (e as Error).message),
  });

  if (detail.isLoading) return <div className="page"><Loading /></div>;
  if (detail.isError || !detail.data) return <div className="page"><ErrorState error={detail.error} /></div>;

  const { episode, script, seo, media } = detail.data;

  return (
    <div className="page">
      <div className="page-head between">
        <div>
          <button className="btn ghost sm" onClick={() => nav(`/pods/${podId}`)} style={{ marginBottom: 8 }}>← Volver al pod</button>
          <div className="eyebrow">Episodio #{String(episode.number).padStart(2, "0")}</div>
          <h1>{episode.title}</h1>
          <div className="tag-list" style={{ marginTop: 10 }}>
            <StateBadge state={episode.state} />
            <Badge>{media.length} archivos</Badge>
            {providers.data && !anyAvailable && (
              <Badge tone="warn">sin proveedor de vídeo activo</Badge>
            )}
          </div>
        </div>
        <div style={{ alignSelf: "flex-end" }}>
          <Button variant="mint" loading={multiplyRun.isPending} onClick={() => multiplyRun.mutate()}>
            <IcRocket /> Multiplicar (DAG)
          </Button>
        </div>
      </div>

      <div className="viewer">
        <div><MediaViewer media={media} /></div>
        <div className="stack">
          {/* RenderConfig owns the render button — it saves then renders atomically */}
          <RenderConfig
            podId={podId}
            episodeId={episodeId}
            detail={detail.data}
            providers={providers.data ?? []}
            episodeState={episode.state}
            onSaved={() => qc.invalidateQueries({ queryKey: ["episode-detail", episodeId] })}
            onRendered={() => nav("/jobs")}
          />
          {seo && <SeoPanel seo={seo} />}
          {script && <ScriptPanel script={script} />}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Render config
function RenderConfig({ podId, episodeId, detail, providers, episodeState, onSaved, onRendered }: {
  podId: string;
  episodeId: string;
  detail: EpisodeDetail;
  providers: ProviderCatalogEntry[];
  episodeState: string;
  onSaved: () => void;
  onRendered: () => void;
}) {
  const toast = useToast();
  const [title, setTitle] = useState(detail.episode.title);
  const [provider, setProvider] = useState(detail.episode.video_provider ?? "");
  const [model, setModel] = useState(detail.episode.video_model ?? "");
  const [isRendering, setIsRendering] = useState(false);

  const selected = providers.find((p) => p.name === provider);
  const models = selected?.models ?? [];

  const save = useMutation({
    mutationFn: () => api.patch(`/pods/${podId}/episodes/${episodeId}`, {
      title,
      video_provider: provider || null,
      video_model: model || null,
    }),
    onSuccess: () => { toast.ok("Episodio actualizado"); onSaved(); },
    onError: (e) => toast.err("No se pudo guardar", (e as Error).message),
  });

  const renderOnly = useMutation({
    mutationFn: () => api.post<{ job_id: string }>(`/pods/${podId}/episodes/${episodeId}/render`),
    onSuccess: (r) => { toast.ok("Render encolado", `Job ${r.job_id.slice(0, 12)}…`); onRendered(); },
    onError: (e) => { toast.err("No se pudo encolar", (e as Error).message); setIsRendering(false); },
  });
  // Resume an interrupted render: continues from the last completed scene
  // (clips already on disk are kept; the engine seeds the next scene i2v).
  const resumeRender = useMutation({
    mutationFn: () => api.post<{ job_id: string }>(`/pods/${podId}/episodes/${episodeId}/render?resume=true`),
    onSuccess: (r) => { toast.ok("Render reanudado", `Job ${r.job_id.slice(0, 12)}…`); onRendered(); },
    onError: (e) => toast.err("No se pudo reanudar", (e as Error).message),
  });

  /**
   * Save current provider/model/title first, then trigger the render.
   * This ensures the job always sees exactly what the user has selected —
   * no need to click "Guardar" manually before "Renderizar".
   */
  const handleRender = async () => {
    setIsRendering(true);
    try {
      await api.patch(`/pods/${podId}/episodes/${episodeId}`, {
        title,
        video_provider: provider || null,
        video_model: model || null,
      });
      onSaved();
      renderOnly.mutate();
    } catch (e) {
      toast.err("No se pudo guardar antes del render", (e as Error).message);
      setIsRendering(false);
    }
  };

  return (
    <div className="card">
      <div className="card-head"><IcEdit width={16} height={16} /><h3>Configuración del render</h3></div>
      <div className="card-pad">
        <Field label="Título"><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label="Proveedor de vídeo" hint="Vacío = el del pod (según el estilo)">
          <select className="select" value={provider}
            onChange={(e) => { setProvider(e.target.value); setModel(""); }}>
            <option value="">— por defecto del pod —</option>
            {providers.map((p) => (
              <option key={p.name} value={p.name}>
                {p.label ?? p.name}{p.available ? " ✓" : " · no disponible"}
              </option>
            ))}
          </select>
        </Field>
        {selected && !selected.available && (
          <p className="dim" style={{ fontSize: 12, margin: "-8px 0 12px" }}>
            ⚠️ {selected.message ?? "Proveedor no disponible — configura su clave en Ajustes."}
          </p>
        )}
        <Field label="Modelo" hint={provider ? "Modelos del proveedor seleccionado" : "Elige un proveedor primero"}>
          {models.length > 0 ? (
            <select className="select mono" value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">auto</option>
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : (
            <input className="input mono" value={model} placeholder="auto" onChange={(e) => setModel(e.target.value)} />
          )}
        </Field>
        <div className="btn-row" style={{ justifyContent: "flex-end", gap: 8 }}>
          <Button variant="ghost" size="sm" loading={save.isPending && !isRendering} onClick={() => save.mutate()}>
            Guardar
          </Button>
          {episodeState === "failed" && (
            <Button variant="default" size="sm" loading={resumeRender.isPending}
              onClick={() => resumeRender.mutate()} title="Continuar desde la última escena buena">
              <IcRocket /> Continuar
            </Button>
          )}
          <Button variant="mint" size="sm" loading={isRendering} onClick={handleRender}>
            <IcRocket /> {episodeState === "ready" ? "Re-renderizar" : "Renderizar"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- SEO panel
function SeoPanel({ seo }: { seo: SeoMetadata }) {
  return (
    <div className="card">
      <div className="card-head"><h3>SEO / Publicación</h3></div>
      <div className="card-pad stack">
        {seo.selected_title && <div><div className="dim" style={{ fontSize: 11.5 }}>TÍTULO</div><div style={{ fontWeight: 600 }}>{seo.selected_title}</div></div>}
        {seo.description && <div><div className="dim" style={{ fontSize: 11.5 }}>DESCRIPCIÓN</div><p className="muted" style={{ fontSize: 13, whiteSpace: "pre-wrap", marginTop: 4 }}>{seo.description.slice(0, 400)}{seo.description.length > 400 ? "…" : ""}</p></div>}
        {seo.hashtags.length > 0 && <div className="tag-list">{seo.hashtags.map((h) => <Badge key={h} tone="accent">{h}</Badge>)}</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Script panel
function ScriptPanel({ script }: { script: Script }) {
  const [open, setOpen] = useState(false);
  const shown = open ? script.scenes : script.scenes.slice(0, 3);
  return (
    <div className="card">
      <div className="card-head between"><h3>Guión</h3><span className="dim mono" style={{ fontSize: 11 }}>{script.scenes.length} escenas</span></div>
      <div className="card-pad stack">
        {script.moral && (
          <div style={{ fontSize: 12.5, color: "var(--c-accent)", borderLeft: "3px solid var(--c-accent)", paddingLeft: 8 }}>
            <span className="dim" style={{ fontSize: 11, display: "block" }}>MORALEJA</span>
            {script.moral}
          </div>
        )}
        {shown.map((s) => (
          <div key={s.id} className="scene">
            <span className="ix">ESCENA {String(s.index + 1).padStart(2, "0")} · {s.duration_s}s</span>
            <div className="vp">{s.visual_prompt}</div>
            {s.audio_text && <div className="at">{s.audio_text}</div>}
          </div>
        ))}
        {script.scenes.length > 3 && (
          <Button variant="ghost" size="sm" onClick={() => setOpen(!open)}>
            {open ? "Ver menos" : `Ver las ${script.scenes.length} escenas`}
          </Button>
        )}
      </div>
    </div>
  );
}

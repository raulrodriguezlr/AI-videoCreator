import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api, getTemplate, startRun,
  type EpisodeDetail, type MediaAsset, type ProviderCatalogEntry, type Script, type SeoMetadata,
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

  // Delete one media artifact (a single clip/frame/audio) from storage.
  const deleteMedia = useMutation({
    mutationFn: (asset: MediaAsset) =>
      api.delete(`/pods/${podId}/episodes/${episodeId}/media/${asset.name}`),
    onSuccess: () => {
      toast.ok("Archivo eliminado");
      qc.invalidateQueries({ queryKey: ["episode-detail", episodeId] });
    },
    onError: (e) => toast.err("No se pudo eliminar", (e as Error).message),
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
        <div><MediaViewer media={media} onDelete={(a) => deleteMedia.mutate(a)} /></div>
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
          {episode.state === "ready" && script && (
            <JoinClipsPanel
              podId={podId} episodeId={episodeId} script={script}
              onJoined={() => nav("/jobs")}
            />
          )}
          {seo && <SeoPanel seo={seo} />}
          {script && <ScriptPanel script={script} episodeId={episodeId} />}
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
  // Re-dub EVERY clip (replace existing dubs) and recompile the dubbed final.
  const redubAll = useMutation({
    mutationFn: () => api.post<{ job_id: string }>(`/pods/${podId}/episodes/${episodeId}/redub`),
    onSuccess: (r) => { toast.ok("Redoblando episodio", `Job ${r.job_id.slice(0, 12)}…`); onRendered(); },
    onError: (e) => toast.err("No se pudo redoblar", (e as Error).message),
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
          {episodeState === "ready" && (
            <Button variant="default" size="sm" loading={redubAll.isPending}
              onClick={() => redubAll.mutate()} title="Redoblar todos los clips y recompilar">
              🎙 Redoblar todo
            </Button>
          )}
          {(episodeState === "failed" || episodeState === "completed") && (
            <Button variant="default" size="sm" loading={resumeRender.isPending}
              onClick={() => resumeRender.mutate()} title="Recompilar reutilizando clips ya generados">
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

// ---------------------------------------------------------------- Join clips
// Recompile the final from a chosen subset of scene clips (e.g. all-except-one).
// Clips on disk are kept, so it's reversible — re-check all and join again.
function JoinClipsPanel({ podId, episodeId, script, onJoined }: {
  podId: string; episodeId: string; script: Script; onJoined: () => void;
}) {
  const toast = useToast();
  const [keep, setKeep] = useState<Set<number>>(() => new Set(script.scenes.map((s) => s.index)));
  const join = useMutation({
    mutationFn: () => api.post<{ job_id: string }>(`/pods/${podId}/episodes/${episodeId}/join`, {
      indices: [...keep].sort((a, b) => a - b),
    }),
    onSuccess: (r) => { toast.ok("Recompilando vídeo", `Job ${r.job_id.slice(0, 12)}…`); onJoined(); },
    onError: (e) => toast.err("No se pudo juntar", (e as Error).message),
  });
  const toggle = (ix: number) => setKeep((prev) => {
    const next = new Set(prev);
    if (next.has(ix)) next.delete(ix); else next.add(ix);
    return next;
  });
  const nKeep = keep.size;
  const total = script.scenes.length;
  return (
    <div className="card">
      <div className="card-head between">
        <h3>Juntar clips</h3>
        <span className="dim mono" style={{ fontSize: 11 }}>{nKeep}/{total}</span>
      </div>
      <div className="card-pad stack">
        <p className="dim" style={{ fontSize: 12, margin: 0 }}>
          Desmarca las escenas que quieras quitar del vídeo final y recompila con el resto.
        </p>
        <div className="stack" style={{ gap: 4 }}>
          {script.scenes.map((s) => (
            <label key={s.id} className="row" style={{ gap: 8, alignItems: "center", cursor: "pointer" }}>
              <input type="checkbox" checked={keep.has(s.index)} onChange={() => toggle(s.index)} />
              <span className="ix">E{String(s.index + 1).padStart(2, "0")}</span>
              <span className="dim" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {s.audio_text || s.visual_prompt}
              </span>
            </label>
          ))}
        </div>
        <div className="btn-row" style={{ justifyContent: "space-between" }}>
          <Button variant="ghost" size="sm"
            onClick={() => setKeep(new Set(script.scenes.map((s) => s.index)))}>
            Todas
          </Button>
          <Button variant="mint" size="sm" loading={join.isPending}
            disabled={nKeep === 0} onClick={() => join.mutate()}>
            Juntar {nKeep} clip{nKeep === 1 ? "" : "s"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Script panel
function ScriptPanel({ script, episodeId }: { script: Script; episodeId: string }) {
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
          <SceneRow key={s.id} podId={script.pod_id} scriptId={script.id} episodeId={episodeId} scene={s} />
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

// One scene row: read-only, with an inline editor to fix the visual prompt /
// dialogue before re-rendering (the render reads the edited values).
function SceneRow({ podId, scriptId, episodeId, scene }: {
  podId: string; scriptId: string; episodeId: string;
  scene: { id: string; index: number; visual_prompt: string; audio_text: string | null; duration_s: number };
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [vp, setVp] = useState(scene.visual_prompt);
  const [at, setAt] = useState(scene.audio_text ?? "");
  const save = useMutation({
    mutationFn: () => api.patch(`/pods/${podId}/scripts/${scriptId}/scenes/${scene.index}`, {
      visual_prompt: vp, audio_text: at || null,
    }),
    onSuccess: () => {
      toast.ok("Escena actualizada", "Pulsa Regenerar para rehacer solo este clip");
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["episode-detail", episodeId] });
    },
    onError: (e) => toast.err("No se pudo guardar", (e as Error).message),
  });
  // Redo ONLY this scene's clip (keep the rest) and recompile the final video.
  const regen = useMutation({
    mutationFn: () => api.post<{ job_id: string }>(
      `/pods/${podId}/episodes/${episodeId}/scenes/${scene.index}/regenerate`),
    onSuccess: (r) => toast.ok("Regenerando escena", `Job ${r.job_id.slice(0, 12)}… · recompila el vídeo al acabar`),
    onError: (e) => toast.err("No se pudo regenerar", (e as Error).message),
  });
  // Re-dub ONLY this scene's audio (no video regen) and recompile.
  const redub = useMutation({
    mutationFn: () => api.post<{ job_id: string }>(
      `/pods/${podId}/episodes/${episodeId}/scenes/${scene.index}/redub`),
    onSuccess: (r) => toast.ok("Redoblando escena", `Job ${r.job_id.slice(0, 12)}…`),
    onError: (e) => toast.err("No se pudo redoblar", (e as Error).message),
  });

  if (editing) {
    return (
      <div className="scene" style={{ display: "grid", gap: 6 }}>
        <span className="ix">ESCENA {String(scene.index + 1).padStart(2, "0")} · editar</span>
        <textarea className="input mono" rows={3} value={vp}
          placeholder="Visual prompt (inglés)" onChange={(e) => setVp(e.target.value)} />
        <textarea className="input" rows={2} value={at}
          placeholder="Diálogo (audio_text)" onChange={(e) => setAt(e.target.value)} />
        <div className="btn-row">
          <Button variant="primary" size="sm" loading={save.isPending} onClick={() => save.mutate()}>Guardar</Button>
          <Button variant="ghost" size="sm" onClick={() => { setVp(scene.visual_prompt); setAt(scene.audio_text ?? ""); setEditing(false); }}>Cancelar</Button>
        </div>
      </div>
    );
  }
  return (
    <div className="scene">
      <div className="between">
        <span className="ix">ESCENA {String(scene.index + 1).padStart(2, "0")} · {scene.duration_s}s</span>
        <div className="btn-row" style={{ gap: 4 }}>
          <Button variant="ghost" size="sm" onClick={() => setEditing(true)} title="Editar prompt / diálogo"><IcEdit width={13} height={13} /></Button>
          <Button variant="ghost" size="sm" loading={redub.isPending} onClick={() => redub.mutate()} title="Redoblar solo el audio de esta escena">🎙</Button>
          <Button variant="ghost" size="sm" loading={regen.isPending} onClick={() => regen.mutate()} title="Regenerar solo este clip y recompilar"><IcRocket width={13} height={13} /></Button>
        </div>
      </div>
      <div className="vp">{scene.visual_prompt}</div>
      {scene.audio_text && <div className="at">{scene.audio_text}</div>}
    </div>
  );
}

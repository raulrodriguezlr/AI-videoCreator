import { useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import {
  api, mediaUrl, subscribeToJob,
  type Character, type Episode, type Pod, type Script, type Short, type Topic, type VoiceOption,
} from "../api/client";
import {
  Badge, Button, Empty, ErrorState, Field, Loading, Modal, StateBadge, Tabs, useToast,
} from "../ui/primitives";
import { IcEdit, IcFile, IcImage, IcPlus, IcRocket, IcSparkles, IcTrash, IcUpload, IcWand } from "../ui/icons";
import { JsonEditor } from "../components/JsonEditor";
import { prettyStyle } from "./PodsListPage";

type TabId = "episodes" | "topics" | "scripts" | "shorts" | "characters" | "files" | "settings";

/** Run `fn` only after the user confirms a destructive action. */
function confirmThen(message: string, fn: () => void): void {
  if (window.confirm(message)) fn();
}

export function PodDetailPage() {
  const { podId = "" } = useParams();
  const [tab, setTab] = useState<TabId>("episodes");
  const pod = useQuery<Pod>({ queryKey: ["pod", podId], queryFn: () => api.get(`/pods/${podId}`) });
  const eps = useQuery<Episode[]>({ queryKey: ["episodes", podId], queryFn: () => api.get(`/pods/${podId}/episodes`) });
  const topics = useQuery<Topic[]>({ queryKey: ["topics", podId], queryFn: () => api.get(`/pods/${podId}/topics`) });
  const scripts = useQuery<Script[]>({ queryKey: ["scripts", podId], queryFn: () => api.get(`/pods/${podId}/scripts`) });
  const shorts = useQuery<Short[]>({ queryKey: ["shorts", podId], queryFn: () => api.get(`/pods/${podId}/shorts`) });
  const chars = useQuery<Character[]>({ queryKey: ["chars", podId], queryFn: () => api.get(`/pods/${podId}/characters`) });

  if (pod.isLoading) return <div className="page"><Loading /></div>;
  if (pod.isError || !pod.data) return <div className="page"><ErrorState error={pod.error} /></div>;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Pod</div>
          <h1>{pod.data.config.series_name || pod.data.name}</h1>
          <p className="sub">{pod.data.config.series_context || pod.data.config.target_audience}</p>
          <div className="tag-list" style={{ marginTop: 12 }}>
            <Badge tone="accent">{prettyStyle(pod.data.config.style_profile)}</Badge>
            <Badge>{pod.data.config.language}</Badge>
            <Badge>{pod.data.config.duration_seconds}s</Badge>
            <span className="mono dim" style={{ fontSize: 11 }}>{pod.data.id}</span>
          </div>
        </div>
      </div>

      <Tabs<TabId> value={tab} onChange={setTab} tabs={[
        { id: "episodes", label: "Episodios", count: eps.data?.length },
        { id: "topics", label: "Temas", count: topics.data?.length },
        { id: "scripts", label: "Guiones", count: scripts.data?.length },
        { id: "shorts", label: "Shorts", count: shorts.data?.length },
        { id: "characters", label: "Personajes", count: chars.data?.length },
        { id: "files", label: "Archivos" },
        { id: "settings", label: "Ajustes" },
      ]} />

      {tab === "episodes" && <EpisodesTab podId={podId} q={eps} />}
      {tab === "topics" && <TopicsTab podId={podId} q={topics} />}
      {tab === "scripts" && <ScriptsTab podId={podId} q={scripts} />}
      {tab === "shorts" && <ShortsTab podId={podId} q={shorts} episodes={eps.data ?? []} />}
      {tab === "characters" && <CharactersTab podId={podId} q={chars} />}
      {tab === "files" && <FilesTab podId={podId} />}
      {tab === "settings" && <SettingsTab pod={pod.data} />}
    </div>
  );
}

// ---------------------------------------------------------------- Episodes
function EpisodesTab({ podId, q }: { podId: string; q: UseQueryResult<Episode[]> }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/pods/${podId}/episodes/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["episodes", podId] }); toast.ok("Episodio borrado"); },
    onError: (e) => toast.err("No se pudo borrar", (e as Error).message),
  });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState error={q.error} />;
  if (!q.data?.length) return <Empty emoji="🎞️" title="Sin episodios">Genera un guión desde un tema y créalo como episodio.</Empty>;
  return (
    <div className="stack">
      {q.data.map((ep) => (
        <div key={ep.id} className="card card-pad between" style={{ cursor: "pointer" }}
          onClick={() => nav(`/pods/${podId}/episodes/${ep.id}`)}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
            <span className="mono dim" style={{ fontSize: 13 }}>#{String(ep.number).padStart(2, "0")}</span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ep.title}</div>
              <div className="muted" style={{ fontSize: 12.5 }}>
                {ep.video_model ? <span className="mono">{ep.video_model}</span> : "modelo por defecto"}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <StateBadge state={ep.state} />
            <Button size="sm" variant="ghost" loading={del.isPending && del.variables === ep.id}
              onClick={(e) => { e.stopPropagation(); confirmThen(`¿Borrar el episodio "${ep.title}"?`, () => del.mutate(ep.id)); }}>
              <IcTrash />
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- Topics
const TOPIC_STATUSES = ["pending", "in_progress", "completed", "rejected"] as const;

function TopicsTab({ podId, q }: { podId: string; q: UseQueryResult<Topic[]> }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [useTrends, setUseTrends] = useState(false);
  const [editing, setEditing] = useState<Topic | null>(null);
  const invalidate = () => qc.invalidateQueries({ queryKey: ["topics", podId] });
  const gen = useMutation({
    mutationFn: () => api.post<Topic[]>(`/pods/${podId}/topics/generate`, { count: 5, use_trends: useTrends }),
    onSuccess: () => { invalidate(); toast.ok("Temas generados"); },
    onError: (e) => toast.err("No se pudieron generar", (e as Error).message),
  });
  const makeScript = useMutation({
    mutationFn: (topicId: string) => api.post<Script>(`/pods/${podId}/scripts/generate`, { topic_id: topicId }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["scripts", podId] }); toast.ok("Guión generado", "Míralo en la pestaña Guiones"); },
    onError: (e) => toast.err("Falló la generación", (e as Error).message),
  });
  const del = useMutation({
    mutationFn: (topicId: string) => api.delete(`/pods/${podId}/topics/${topicId}`),
    onSuccess: () => { invalidate(); toast.ok("Tema borrado"); },
    onError: (e) => toast.err("No se pudo borrar", (e as Error).message),
  });
  return (
    <div className="stack">
      <div className="btn-row">
        <Button variant="primary" loading={gen.isPending} onClick={() => gen.mutate()}><IcSparkles /> Generar temas (IA)</Button>
        <label className="check">
          <input type="checkbox" checked={useTrends} onChange={(e) => setUseTrends(e.target.checked)} />
          <span>Usar tendencias actuales de internet</span>
        </label>
      </div>
      {q.isLoading && <Loading />}
      {!q.isLoading && !q.data?.length && <Empty emoji="💡" title="Sin temas">Genera ideas de episodios con la IA.</Empty>}
      {q.data?.map((t) => (
        <div key={t.id} className="card card-pad between">
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600 }}>{t.title}</div>
            {t.description && <div className="muted" style={{ fontSize: 13, marginTop: 3 }}>{t.description}</div>}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <StateBadge state={t.status} />
            <Button size="sm" loading={makeScript.isPending && makeScript.variables === t.id}
              onClick={() => makeScript.mutate(t.id)}><IcWand /> Guión</Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(t)}><IcEdit /></Button>
            <Button size="sm" variant="ghost" loading={del.isPending && del.variables === t.id}
              onClick={() => confirmThen("¿Borrar este tema?", () => del.mutate(t.id))}><IcTrash /></Button>
          </div>
        </div>
      ))}
      {editing && <EditTopicModal podId={podId} topic={editing} onClose={() => setEditing(null)}
        onSaved={() => { invalidate(); setEditing(null); }} />}
    </div>
  );
}

function EditTopicModal({ podId, topic, onClose, onSaved }: {
  podId: string; topic: Topic; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [title, setTitle] = useState(topic.title);
  const [description, setDescription] = useState(topic.description ?? "");
  const [status, setStatus] = useState(topic.status);
  const save = useMutation({
    mutationFn: () => api.patch<Topic>(`/pods/${podId}/topics/${topic.id}`, {
      title, description: description || null, status,
    }),
    onSuccess: () => { toast.ok("Tema actualizado"); onSaved(); },
    onError: (e) => toast.err("No se pudo guardar", (e as Error).message),
  });
  return (
    <Modal title="Editar tema" onClose={onClose} footer={<>
      <Button variant="ghost" onClick={onClose}>Cancelar</Button>
      <Button variant="primary" loading={save.isPending} disabled={!title.trim()} onClick={() => save.mutate()}>Guardar</Button>
    </>}>
      <Field label="Título"><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
      <Field label="Descripción"><textarea className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      <Field label="Estado">
        <select className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
          {TOPIC_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </Field>
    </Modal>
  );
}

// ---------------------------------------------------------------- Scripts
function ScriptsTab({ podId, q }: { podId: string; q: UseQueryResult<Script[]> }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [viewing, setViewing] = useState<Script | null>(null);
  const makeEp = useMutation({
    mutationFn: (s: Script) => api.post<Episode>(`/pods/${podId}/episodes`, { script_id: s.id, title: s.title }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["episodes", podId] }); toast.ok("Episodio creado", "Disponible en Episodios"); },
    onError: (e) => toast.err("No se pudo crear", (e as Error).message),
  });
  if (q.isLoading) return <Loading />;
  if (!q.data?.length) return <Empty emoji="📝" title="Sin guiones">Genera un guión desde un tema.</Empty>;
  return (
    <div className="stack">
      {q.data.map((s) => (
        <div key={s.id} className="card card-pad between">
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600 }}>{s.title} <span className="dim mono" style={{ fontSize: 11 }}>v{s.version}</span></div>
            <div className="muted" style={{ fontSize: 13 }}>{s.scenes.length} escenas · {s.summary?.slice(0, 80)}</div>
          </div>
          <div className="btn-row">
            <Button size="sm" variant="ghost" onClick={() => setViewing(s)}><IcFile /> Ver guión</Button>
            <Button size="sm" variant="primary" loading={makeEp.isPending && makeEp.variables?.id === s.id}
              onClick={() => makeEp.mutate(s)}><IcPlus /> Crear episodio</Button>
          </div>
        </div>
      ))}
      {viewing && <ScriptViewerModal script={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

function ScriptViewerModal({ script, onClose }: { script: Script; onClose: () => void }) {
  const [raw, setRaw] = useState(false);
  return (
    <Modal title={`Guión · ${script.title}`} onClose={onClose} footer={<Button variant="ghost" onClick={onClose}>Cerrar</Button>}>
      <div className="stack">
        <div className="between">
          <span className="muted" style={{ fontSize: 13 }}>{script.scenes.length} escenas · v{script.version}</span>
          <div className="seg">
            <button className={!raw ? "on" : ""} onClick={() => setRaw(false)}>Escenas</button>
            <button className={raw ? "on" : ""} onClick={() => setRaw(true)}>JSON</button>
          </div>
        </div>
        {script.summary && <p className="muted" style={{ fontSize: 13, margin: 0 }}>{script.summary}</p>}
        {raw ? (
          <pre className="json-view">{JSON.stringify(script, null, 2)}</pre>
        ) : (
          <div className="stack">
            {script.scenes.map((sc) => (
              <div key={sc.id} className="card card-pad stack" style={{ gap: 6 }}>
                <div className="between">
                  <Badge tone="accent">Escena {sc.index}</Badge>
                  <span className="dim mono" style={{ fontSize: 11 }}>
                    {sc.duration_s}s{sc.camera_shot ? ` · ${sc.camera_shot}` : ""}{sc.transition ? ` · ${sc.transition}` : ""}
                  </span>
                </div>
                <div style={{ fontSize: 13 }}><b className="dim">Visual:</b> {sc.visual_prompt}</div>
                {sc.audio_text && <div style={{ fontSize: 13 }}><b className="dim">Audio:</b> {sc.audio_text}</div>}
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- Shorts
const PLATFORMS = ["shorts", "tiktok", "reels"] as const;

function ShortsTab({ podId, q, episodes }: {
  podId: string; q: UseQueryResult<Short[]>; episodes: Episode[];
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);

  const render = useMutation({
    mutationFn: (shortId: string) => api.post<{ job_id: string }>(`/pods/${podId}/shorts/${shortId}/render`),
    onSuccess: (r) => {
      toast.ok("Render de short en curso", `Job ${r.job_id.slice(0, 12)}…`);
      // Live-refresh the list when the render job reaches a terminal state.
      const stop = subscribeToJob(r.job_id, {
        onEvent: (e) => {
          const done = !!e.result || !!e.error
            || ["completed", "succeeded", "failed", "cancelled"].includes(e.event);
          if (!done) return;
          qc.invalidateQueries({ queryKey: ["shorts", podId] });
          if (e.error) toast.err("El render falló", e.error);
          stop();
        },
      });
    },
    onError: (e) => toast.err("No se pudo renderizar", (e as Error).message),
  });

  return (
    <div className="stack">
      <div className="btn-row">
        <Button variant="primary" disabled={episodes.length === 0} onClick={() => setCreating(true)}>
          <IcPlus /> Nuevo short
        </Button>
        {episodes.length === 0 && <span className="dim" style={{ fontSize: 13 }}>Necesitas al menos un episodio como fuente.</span>}
      </div>

      {q.isLoading && <Loading />}
      {!q.isLoading && !q.data?.length && <Empty emoji="📱" title="Sin shorts">Crea verticales 9:16 a partir de un episodio.</Empty>}

      <div className="grid cols">
        {q.data?.map((s) => (
          <div key={s.id} className="card card-pad stack">
            <div className="between">
              <Badge tone="accent">{s.target_platform}</Badge>
              <span className="dim mono" style={{ fontSize: 11 }}>{s.aspect} · {s.duration_s}s</span>
            </div>
            {s.rendered_video_key ? (
              <div className="stage" style={{ aspectRatio: "9/16", maxHeight: 320, margin: "0 auto" }}>
                <video src={mediaUrl(`/storage/${s.rendered_video_key}`)} controls preload="metadata" style={{ height: "100%" }} />
              </div>
            ) : (
              <div className="thumb" style={{ aspectRatio: "9/16", maxHeight: 240, margin: "0 auto", width: "auto" }}>
                <IcRocket />
              </div>
            )}
            {s.hook_text && <p className="muted" style={{ fontSize: 13, margin: 0 }}>“{s.hook_text}”</p>}
            <div className="between">
              <Badge tone={s.rendered_video_key ? "ok" : "default"}>{s.rendered_video_key ? "renderizado" : "pendiente"}</Badge>
              <Button size="sm" loading={render.isPending && render.variables === s.id} onClick={() => render.mutate(s.id)}>
                <IcRocket /> {s.rendered_video_key ? "Re-render" : "Renderizar"}
              </Button>
            </div>
          </div>
        ))}
      </div>

      {creating && (
        <CreateShortModal podId={podId} episodes={episodes} onClose={() => setCreating(false)}
          onCreated={() => { qc.invalidateQueries({ queryKey: ["shorts", podId] }); setCreating(false); }} />
      )}
    </div>
  );
}

function CreateShortModal({ podId, episodes, onClose, onCreated }: {
  podId: string; episodes: Episode[]; onClose: () => void; onCreated: () => void;
}) {
  const toast = useToast();
  const [sourceId, setSourceId] = useState(episodes[0]?.id ?? "");
  const [duration, setDuration] = useState(30);
  const [platform, setPlatform] = useState<(typeof PLATFORMS)[number]>("shorts");
  const [hook, setHook] = useState("");

  const create = useMutation({
    mutationFn: () => api.post<Short>(`/pods/${podId}/shorts`, {
      source_episode_id: sourceId, duration_s: duration, target_platform: platform,
      hook_text: hook || null,
    }),
    onSuccess: () => { toast.ok("Short creado"); onCreated(); },
    onError: (e) => toast.err("No se pudo crear", (e as Error).message),
  });

  return (
    <Modal title="Nuevo short" onClose={onClose} footer={
      <>
        <Button variant="ghost" onClick={onClose}>Cancelar</Button>
        <Button variant="primary" loading={create.isPending} disabled={!sourceId} onClick={() => create.mutate()}>Crear short</Button>
      </>
    }>
      <Field label="Episodio fuente">
        <select className="select" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
          {episodes.map((ep) => <option key={ep.id} value={ep.id}>#{ep.number} · {ep.title}</option>)}
        </select>
      </Field>
      <div className="row">
        <Field label="Duración (s)"><input className="input" type="number" min={5} max={180} value={duration} onChange={(e) => setDuration(Number(e.target.value))} /></Field>
        <Field label="Plataforma">
          <select className="select" value={platform} onChange={(e) => setPlatform(e.target.value as (typeof PLATFORMS)[number])}>
            {PLATFORMS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Hook (texto de gancho)" hint="Opcional — aparece como overlay al inicio">
        <input className="input" value={hook} onChange={(e) => setHook(e.target.value)} placeholder="¡No te vas a creer lo que pasó!" />
      </Field>
    </Modal>
  );
}

// ---------------------------------------------------------------- Characters
function CharactersTab({ podId, q }: { podId: string; q: UseQueryResult<Character[]> }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [assetsFor, setAssetsFor] = useState<Character | null>(null);
  const [editing, setEditing] = useState<Character | null>(null);
  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/pods/${podId}/characters/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["chars", podId] }); toast.ok("Personaje borrado"); },
    onError: (e) => toast.err("No se pudo borrar", (e as Error).message),
  });
  if (q.isLoading) return <Loading />;
  if (!q.data?.length) return <Empty emoji="🧑‍🎤" title="Sin personajes">El asistente de pods puede proponer un reparto.</Empty>;

  // Keep the open modal in sync with refreshed query data.
  const live = assetsFor && q.data.find((c) => c.id === assetsFor.id);

  return (
    <>
      <div className="grid cols">
        {q.data.map((c) => (
          <div key={c.id} className="card card-pad stack">
            <div className="between">
              <h3>{c.name}</h3>
              <Badge tone="accent">{c.role}</Badge>
            </div>
            {c.personality && <p className="muted" style={{ fontSize: 13 }}>{c.personality}</p>}
            {c.look_description && <p className="dim" style={{ fontSize: 12.5 }}>{c.look_description}</p>}

            {c.reference_image_keys.length > 0 && (
              <div className="ref-strip">
                {c.reference_image_keys.slice(0, 4).map((ref) => (
                  <img key={ref} src={mediaUrl(`/storage/${ref}`)} alt="" loading="lazy" />
                ))}
                {c.reference_image_keys.length > 4 && (
                  <span className="ref-more">+{c.reference_image_keys.length - 4}</span>
                )}
              </div>
            )}

            <div className="btn-row" style={{ marginTop: "auto" }}>
              <Button size="sm" variant="ghost" onClick={() => setAssetsFor(c)}>
                <IcImage /> Referencias{c.reference_image_keys.length ? ` (${c.reference_image_keys.length})` : ""}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(c)}><IcEdit /></Button>
              <Button size="sm" variant="ghost" loading={del.isPending && del.variables === c.id}
                onClick={() => confirmThen(`¿Borrar a "${c.name}"?`, () => del.mutate(c.id))}><IcTrash /></Button>
            </div>
          </div>
        ))}
      </div>

      {live && (
        <CharacterAssetsModal podId={podId} character={live} onClose={() => setAssetsFor(null)} />
      )}
      {editing && <EditCharacterModal podId={podId} character={editing} onClose={() => setEditing(null)}
        onSaved={() => { qc.invalidateQueries({ queryKey: ["chars", podId] }); setEditing(null); }} />}
    </>
  );
}

function EditCharacterModal({ podId, character, onClose, onSaved }: {
  podId: string; character: Character; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(character.name);
  const [role, setRole] = useState(character.role);
  const [personality, setPersonality] = useState(character.personality ?? "");
  const [look, setLook] = useState(character.look_description ?? "");
  const [voiceId, setVoiceId] = useState<string>((character.voice as { voice_id?: string } | null)?.voice_id ?? "");
  const [query, setQuery] = useState("");

  const search = useMutation({
    mutationFn: () => api.post<VoiceOption[]>(`/pods/${podId}/characters/${character.id}/voices/search`, { query }),
    onError: (e) => toast.err("No se pudo buscar voces", (e as Error).message),
  });
  const save = useMutation({
    mutationFn: () => api.patch<Character>(`/pods/${podId}/characters/${character.id}`, {
      name, role, personality: personality || null, look_description: look || null,
      voice: voiceId ? { voice_id: voiceId } : undefined,
    }),
    onSuccess: () => { toast.ok("Personaje actualizado"); onSaved(); },
    onError: (e) => toast.err("No se pudo guardar", (e as Error).message),
  });

  return (
    <Modal title={`Editar · ${character.name}`} onClose={onClose} footer={<>
      <Button variant="ghost" onClick={onClose}>Cancelar</Button>
      <Button variant="primary" loading={save.isPending} disabled={!name.trim()} onClick={() => save.mutate()}>Guardar</Button>
    </>}>
      <div className="row">
        <Field label="Nombre"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Rol"><input className="input" value={role} onChange={(e) => setRole(e.target.value)} /></Field>
      </div>
      <Field label="Personalidad"><textarea className="textarea" value={personality} onChange={(e) => setPersonality(e.target.value)} /></Field>
      <Field label="Aspecto (look)"><textarea className="textarea" value={look} onChange={(e) => setLook(e.target.value)} /></Field>

      <div className="divider" />
      <Field label="Voz (ElevenLabs)" hint={voiceId ? `Asignada: ${voiceId}` : "Sin voz asignada"}>
        <div className="btn-row">
          <input className="input" placeholder="describe la voz: niña dulce, narrador épico…"
            value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && query.trim().length > 1) search.mutate(); }} />
          <Button variant="default" loading={search.isPending} disabled={query.trim().length < 2}
            onClick={() => search.mutate()}><IcSparkles /> Buscar</Button>
        </div>
      </Field>
      {search.data && search.data.length === 0 && <p className="dim" style={{ fontSize: 12.5 }}>Sin resultados — prueba otra descripción.</p>}
      <div className="stack" style={{ gap: 8 }}>
        {search.data?.map((v) => (
          <div key={v.voice_id} className={`voice-row ${v.voice_id === voiceId ? "sel" : ""}`}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{v.name}</div>
              <div className="dim" style={{ fontSize: 11.5 }}>
                {[v.gender, v.age, v.accent, v.description].filter(Boolean).join(" · ").slice(0, 70) || "—"}
              </div>
            </div>
            {v.preview_url && <audio src={v.preview_url} controls preload="none" style={{ height: 30 }} />}
            <Button size="sm" variant={v.voice_id === voiceId ? "mint" : "ghost"}
              onClick={() => setVoiceId(v.voice_id)}>{v.voice_id === voiceId ? "✓" : "Asignar"}</Button>
          </div>
        ))}
      </div>
    </Modal>
  );
}

function CharacterAssetsModal({ podId, character, onClose }: {
  podId: string; character: Character; onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [prompt, setPrompt] = useState("");
  const base = `/pods/${podId}/characters/${character.id}/references`;
  const refresh = () => qc.invalidateQueries({ queryKey: ["chars", podId] });

  const uploadM = useMutation({
    mutationFn: (files: File[]) => api.upload<Character>(base, files),
    onSuccess: () => { toast.ok("Imágenes subidas"); refresh(); },
    onError: (e) => toast.err("No se pudo subir", (e as Error).message),
  });
  const genM = useMutation({
    mutationFn: () => api.post<Character>(`${base}/generate`, { prompt }),
    onSuccess: () => { toast.ok("Imagen generada"); setPrompt(""); refresh(); },
    onError: (e) => toast.err("No se pudo generar", (e as Error).message),
  });
  const delM = useMutation({
    mutationFn: (ref: string) => api.delete<Character>(`${base}?ref=${encodeURIComponent(ref)}`),
    onSuccess: () => refresh(),
    onError: (e) => toast.err("No se pudo borrar", (e as Error).message),
  });

  const refs = character.reference_image_keys;
  const lookPrompt = character.look_description
    ? `${character.name}, ${character.look_description}`
    : character.name;

  return (
    <Modal title={`Assets · ${character.name}`} onClose={onClose} footer={
      <Button variant="ghost" onClick={onClose}>Cerrar</Button>
    }>
      <div className="stack">
        <div className="between">
          <span className="eyebrow">Imágenes de referencia</span>
          <Badge>{refs.length}</Badge>
        </div>

        {refs.length === 0 ? (
          <Empty emoji="🖼️" title="Sin referencias">Sube imágenes o genera una con IA para fijar el look del personaje.</Empty>
        ) : (
          <div className="asset-grid">
            {refs.map((ref) => (
              <figure key={ref} className="asset-cell">
                <img src={mediaUrl(`/storage/${ref}`)} alt="" loading="lazy" />
                <button className="asset-del" title="Eliminar"
                  disabled={delM.isPending && delM.variables === ref}
                  onClick={() => delM.mutate(ref)}>
                  <IcTrash />
                </button>
              </figure>
            ))}
          </div>
        )}

        <div className="divider" />

        <input ref={fileInput} type="file" accept="image/*" multiple hidden
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length) uploadM.mutate(files);
            e.target.value = "";
          }} />
        <div className="btn-row">
          <Button variant="default" loading={uploadM.isPending} onClick={() => fileInput.current?.click()}>
            <IcUpload /> Subir imágenes
          </Button>
        </div>

        <div className="divider" />

        <Field label="Generar con IA (Imagen)" hint="Describe el aspecto; se añade como referencia">
          <textarea className="input" rows={2} value={prompt}
            placeholder={lookPrompt}
            onChange={(e) => setPrompt(e.target.value)} />
        </Field>
        <div className="btn-row">
          <Button variant="ghost" onClick={() => setPrompt(lookPrompt)}><IcWand /> Usar descripción</Button>
          <Button variant="primary" loading={genM.isPending}
            disabled={prompt.trim().length < 3}
            onClick={() => genM.mutate()}>
            <IcSparkles /> Generar
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- Files (raw JSON)
function FilesTab({ podId }: { podId: string }) {
  const files = useQuery<{ files: string[] }>({
    queryKey: ["pod-files", podId], queryFn: () => api.get(`/pods/${podId}/files`),
  });
  const [active, setActive] = useState<string | null>(null);
  const list = files.data?.files ?? [];
  const current = active ?? list[0] ?? null;

  if (files.isLoading) return <Loading />;
  if (!list.length) {
    return <Empty emoji="📄" title="Sin archivos editables">Este pod no tiene JSON heredado (config.json, prompts.json…).</Empty>;
  }

  return (
    <div className="stack">
      <p className="muted" style={{ fontSize: 13, margin: 0 }}>
        <IcFile /> JSON heredado del pod — edición en crudo. Se valida antes de guardar.
      </p>
      <div className="file-pills">
        {list.map((f) => (
          <button key={f} className={f === current ? "on" : ""} onClick={() => setActive(f)}>{f}</button>
        ))}
      </div>
      {current && (
        <div className="card card-pad">
          <JsonEditor
            key={current}
            getPath={`/pods/${podId}/files/${current}`}
            putPath={`/pods/${podId}/files/${current}`}
            queryKey={["pod-file", podId, current]}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Settings
const STYLES = ["cinematic_3d", "kids_3d", "anime_2d", "photoreal_doc", "talking_head_avatar", "stock_montage"];

function SettingsTab({ pod }: { pod: Pod }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [cfg, setCfg] = useState(pod.config);
  const providers = useQuery<string[]>({ queryKey: ["providers"], queryFn: () => api.get("/providers") });
  const save = useMutation({
    mutationFn: () => api.put<Pod>(`/pods/${pod.id}/config`, { config: cfg }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pod", pod.id] });
      qc.invalidateQueries({ queryKey: ["pods"] });
      toast.ok("Ajustes guardados");
    },
    onError: (e) => toast.err("No se pudo guardar", (e as Error).message),
  });
  const set = <K extends keyof typeof cfg>(k: K, v: (typeof cfg)[K]) => setCfg({ ...cfg, [k]: v });

  return (
    <div className="card card-pad" style={{ maxWidth: 720 }}>
      <div className="row">
        <Field label="Nombre de la serie"><input className="input" value={cfg.series_name} onChange={(e) => set("series_name", e.target.value)} /></Field>
        <Field label="Idioma"><input className="input" value={cfg.language} onChange={(e) => set("language", e.target.value)} /></Field>
      </div>
      <div className="row">
        <Field label="Audiencia"><input className="input" value={cfg.target_audience} onChange={(e) => set("target_audience", e.target.value)} /></Field>
        <Field label="Duración (s)"><input className="input" type="number" value={cfg.duration_seconds} onChange={(e) => set("duration_seconds", Number(e.target.value))} /></Field>
      </div>
      <div className="row">
        <Field label="Duración máx. por clip (s)" hint="Tope por escena (Veo=8). Otros motores pueden más">
          <input className="input" type="number" value={cfg.max_clip_seconds} onChange={(e) => set("max_clip_seconds", Number(e.target.value))} />
        </Field>
        <Field label="Preguntas al público" hint="0 = ninguna. Para contenido infantil/educativo">
          <input className="input" type="number" min={0} value={cfg.interactive_questions} onChange={(e) => set("interactive_questions", Number(e.target.value))} />
        </Field>
      </div>
      <div className="row">
        <Field label="Estilo visual">
          <select className="select" value={cfg.style_profile} onChange={(e) => set("style_profile", e.target.value)}>
            {STYLES.map((s) => <option key={s} value={s}>{prettyStyle(s)}</option>)}
          </select>
        </Field>
        <Field label="Proveedor de vídeo por defecto" hint="Se puede sobreescribir por episodio">
          <select className="select" value={cfg.provider_preferences?.primary ?? ""}
            onChange={(e) => set("provider_preferences", { ...cfg.provider_preferences, primary: e.target.value })}>
            <option value="">(automático según estilo)</option>
            {(providers.data ?? []).map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Estilo de arte (texto libre)"><input className="input" value={cfg.art_style ?? ""} onChange={(e) => set("art_style", e.target.value || null)} /></Field>
      <Field label="Contexto de la serie"><textarea className="textarea" value={cfg.series_context ?? ""} onChange={(e) => set("series_context", e.target.value || null)} /></Field>
      <div className="btn-row" style={{ justifyContent: "flex-end" }}>
        <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Guardar cambios</Button>
      </div>
    </div>
  );
}

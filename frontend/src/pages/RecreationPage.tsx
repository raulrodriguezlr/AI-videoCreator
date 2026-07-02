import { useState, useEffect, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  planRecreation, sceneTrendMatch, runRecreation, getRecreations, updateRecreation, getRecreation,
  getSdkProviders, ingestAltUpload, ingestAltYoutube, runAlternateEnding, mediaUrl,
  type FairUse, type SceneCandidate, type RecreationBeat,
  type UpdateRecreationRequest, type SdkProvider, type IngestResponse, type AlternateEndingResponse,
} from "../api/client";
import { Badge, Button, Empty, ErrorState, Field, Loading, useToast, Tabs } from "../ui/primitives";
import { IcAlertTriangle, IcRadar, IcSparkles, IcWand, IcEdit, IcUpload } from "../ui/icons";

const RISK_TONE: Record<FairUse["risk"] | string, "ok" | "warn" | "err"> = {
  low: "ok", medium: "warn", high: "err",
};
const RISK_LABEL: Record<FairUse["risk"] | string, string> = {
  low: "Riesgo bajo", medium: "Riesgo medio", high: "Riesgo alto",
};

export function RecreationPage() {
  const [activeTab, setActiveTab] = useState<"new" | "alt" | "history">("new");

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Estudio</div>
          <h1>Recreaciones</h1>
          <p className="sub">
            Detecta escenas icónicas en tendencia y planifica una recreación transformativa con evaluación de uso justo.
          </p>
        </div>
      </div>

      <Tabs
        value={activeTab}
        onChange={setActiveTab}
        tabs={[
          { id: "new", label: "Nueva recreación" },
          { id: "alt", label: "Final alternativo" },
          { id: "history", label: "Borradores e Historial" }
        ]}
      />

      <div style={{ marginTop: 24 }}>
        {activeTab === "new" && <NewRecreationTab onGoToHistory={() => setActiveTab("history")} />}
        {activeTab === "alt" && <AlternateEndingTab />}
        {activeTab === "history" && <HistoryTab />}
      </div>
    </div>
  );
}

function AlternateEndingTab() {
  const toast = useToast();
  const [source, setSource] = useState<IngestResponse | null>(null);
  const [url, setUrl] = useState("");
  const [rightsAck, setRightsAck] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [cutAt, setCutAt] = useState(2);
  const [prompt, setPrompt] = useState("");
  const [tailDur, setTailDur] = useState(5);
  const [result, setResult] = useState<AlternateEndingResponse | null>(null);

  const ingestFile = useMutation({
    mutationFn: (f: File) => ingestAltUpload(f),
    onSuccess: (r) => { setSource(r); setCutAt(Math.min(2, Math.max(0.5, r.duration_s / 2))); toast.ok("Clip cargado", `${r.duration_s.toFixed(1)}s`); },
    onError: (e) => toast.err("No se pudo cargar", (e as Error).message),
  });
  const ingestYt = useMutation({
    mutationFn: () => ingestAltYoutube(url.trim(), rightsAck),
    onSuccess: (r) => { setSource(r); setCutAt(Math.min(2, r.duration_s / 2)); toast.ok("Vídeo descargado", `${r.duration_s.toFixed(1)}s`); },
    onError: (e) => toast.err("No se pudo descargar", (e as Error).message),
  });
  const run = useMutation({
    mutationFn: () => runAlternateEnding(source!.source_id, cutAt, prompt.trim(), tailDur),
    onSuccess: (r) => { setResult(r); toast.ok("Final alternativo listo"); },
    onError: (e) => toast.err("Falló la generación", (e as Error).message),
  });

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault(); setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) ingestFile.mutate(f);
  };

  return (
    <div className="stack" style={{ gap: 16, maxWidth: 720 }}>
      <p className="muted" style={{ fontSize: 13, margin: 0 }}>
        Conserva el principio del clip original y regenera solo el final desde el segundo de corte (image-to-video).
      </p>

      {/* 1) Ingesta */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        style={{
          border: `2px dashed ${dragOver ? "var(--mint)" : "var(--c-border)"}`,
          borderRadius: 12, padding: 24, textAlign: "center",
          background: dragOver ? "rgba(60,200,150,0.06)" : "transparent",
        }}
      >
        <IcUpload />
        <div style={{ marginTop: 8, fontSize: 14 }}>
          Arrastra un mp4 aquí{source ? "" : ", o"}{" "}
          <label style={{ color: "var(--mint)", cursor: "pointer" }}>
            búscalo
            <input
              type="file" accept="video/mp4,video/quicktime,video/webm"
              style={{ display: "none" }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) ingestFile.mutate(f); }}
            />
          </label>
          {ingestFile.isPending && " · subiendo…"}
        </div>
      </div>

      <Field label="…o pega una URL de YouTube" hint="Descargar vídeo de terceros requiere confirmar derechos / uso justo">
        <div style={{ display: "flex", gap: 8 }}>
          <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://youtu.be/…" style={{ flex: 1 }} />
          <Button variant="ghost" loading={ingestYt.isPending} disabled={!url.trim() || !rightsAck} onClick={() => ingestYt.mutate()}>
            Descargar
          </Button>
        </div>
      </Field>
      <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
        <input type="checkbox" checked={rightsAck} onChange={(e) => setRightsAck(e.target.checked)} />
        Confirmo que tengo los derechos o una base de uso justo para este vídeo.
      </label>

      {/* 2) Corte + prompt */}
      {source && (
        <div className="card">
          <div className="card-pad stack" style={{ gap: 12 }}>
            <Badge tone="ok">Clip listo · {source.duration_s.toFixed(1)}s</Badge>
            <Field label={`Cortar en el segundo: ${cutAt.toFixed(1)}s`} hint="Todo lo anterior queda original; a partir de aquí se regenera">
              <input type="range" min={0.5} max={Math.max(1, source.duration_s - 0.5)} step={0.1}
                value={cutAt} onChange={(e) => setCutAt(parseFloat(e.target.value))} style={{ width: "100%" }} />
            </Field>
            <Field label="Nuevo final (prompt)">
              <textarea className="input" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)}
                placeholder="Describe cómo cambia el final…" style={{ resize: "vertical", fontFamily: "inherit" }} />
            </Field>
            <Field label={`Duración del nuevo final: ${tailDur}s`}>
              <input type="range" min={3} max={10} step={1} value={tailDur}
                onChange={(e) => setTailDur(parseInt(e.target.value))} style={{ width: "100%" }} />
            </Field>
            <Button variant="mint" loading={run.isPending} disabled={!prompt.trim()} onClick={() => run.mutate()}>
              <IcWand /> Generar final alternativo
            </Button>
          </div>
        </div>
      )}

      {/* 3) Resultado */}
      {result?.video_url && (
        <div className="card">
          <div className="card-head"><h3>Resultado · {result.duration_s.toFixed(1)}s</h3></div>
          <div className="card-pad">
            <video src={mediaUrl(result.video_url)} controls style={{ width: "100%", borderRadius: 8 }} />
          </div>
        </div>
      )}
    </div>
  );
}

function NewRecreationTab({ onGoToHistory }: { onGoToHistory: () => void }) {
  const toast = useToast();

  const trendMatch = useMutation({
    mutationFn: () => sceneTrendMatch([]),
    onError: (e) => toast.err("No se pudo buscar tendencias", (e as Error).message),
  });

  const [original, setOriginal] = useState("");
  const [niche, setNiche] = useState("general");
  const [twist, setTwist] = useState("");
  const [draftId, setDraftId] = useState<string | null>(null);

  const plan = useMutation({
    mutationFn: () => planRecreation(original.trim(), niche.trim() || "general", twist.trim()),
    onSuccess: (data) => setDraftId(data.id),
    onError: (e) => toast.err("No se pudo planificar la recreación", (e as Error).message),
  });

  const useCandidate = (candidate: SceneCandidate) => {
    setOriginal(candidate.scene);
    requestAnimationFrame(() => {
      document.getElementById("recreation-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  const canPlan = original.trim().length >= 3 && twist.trim().length >= 3 && !plan.isPending;

  if (draftId) {
    return (
      <div className="stack" style={{ gap: 24 }}>
        <div className="between">
          <Button onClick={() => setDraftId(null)}>← Volver a planificar</Button>
          <Button onClick={onGoToHistory} variant="ghost">Ir al Historial →</Button>
        </div>
        <RecreationEditor id={draftId} />
      </div>
    );
  }

  return (
    <div className="stack" style={{ gap: 24 }}>
      {/* ---------------------------------------------------------- Radar */}
      <div className="card card-pad stack">
        <div className="between">
          <div>
            <h2>Radar de escenas</h2>
            <p className="sub" style={{ margin: "4px 0 0" }}>
              Busca términos en tendencia y escenas icónicas asociadas que valga la pena recrear.
            </p>
          </div>
          <Button variant="primary" loading={trendMatch.isPending} onClick={() => trendMatch.mutate()}>
            <IcRadar /> Buscar escenas trending
          </Button>
        </div>

        {trendMatch.isPending && <Loading />}
        {trendMatch.isError && <ErrorState error={trendMatch.error} />}
        {trendMatch.isSuccess && trendMatch.data.trends_source !== "live" && (
          <p className="trend-source-notice">
            <IcAlertTriangle />
            {trendMatch.data.trends_source === "cache"
              ? "Google Trends no accesible — mostrando términos en caché."
              : "Google Trends no accesible — mostrando términos genéricos."}
          </p>
        )}
        {trendMatch.isSuccess && trendMatch.data.candidates.length === 0 && (
          <Empty emoji="📡" title="Sin resultados">
            No se encontraron escenas en tendencia ahora mismo — vuelve a intentarlo más tarde.
          </Empty>
        )}
        {trendMatch.isSuccess && trendMatch.data.candidates.length > 0 && (
          <div className="scene-candidates">
            {trendMatch.data.candidates.map((candidate, i) => (
              <article key={i} className="card card-pad scene-candidate">
                <div>
                  <span className="term mono">{candidate.term}</span>
                  <h3 style={{ marginTop: 6 }}>{candidate.scene}</h3>
                </div>
                <p className="why">{candidate.why_trending}</p>
                <Button size="sm" onClick={() => useCandidate(candidate)} style={{ marginTop: "auto" }}>
                  <IcWand /> Usar
                </Button>
              </article>
            ))}
          </div>
        )}
      </div>

      {/* ---------------------------------------------------------- Form */}
      <div className="card card-pad stack" id="recreation-form">
        <div>
          <h2>Planificar recreación</h2>
          <p className="sub" style={{ margin: "4px 0 0" }}>
            Describe la escena original y el giro transformativo — el director evaluará el riesgo de uso justo y creará un borrador.
          </p>
        </div>

        <Field label="Escena original" hint="Describe la escena icónica que quieres recrear.">
          <textarea
            className="textarea"
            placeholder="p. ej. La escena de bullet-time en la azotea de The Matrix"
            value={original}
            onChange={(e) => setOriginal(e.target.value)}
          />
        </Field>

        <div className="row">
          <Field label="Nicho" hint="Temática o canal donde se publicará.">
            <input
              className="input"
              placeholder="p. ej. finanzas personales"
              value={niche}
              onChange={(e) => setNiche(e.target.value)}
            />
          </Field>
        </div>

        <Field label="Giro transformativo" hint="Qué cambia para que sea una parodia/transformación, no una copia.">
          <textarea
            className="textarea"
            placeholder="p. ej. las balas son facturas sin pagar"
            value={twist}
            onChange={(e) => setTwist(e.target.value)}
          />
        </Field>

        <div className="btn-row">
          <Button variant="primary" loading={plan.isPending} disabled={!canPlan} onClick={() => plan.mutate()}>
            <IcSparkles /> Planificar Borrador
          </Button>
        </div>
        
        {plan.isError && <ErrorState error={plan.error} />}
      </div>
    </div>
  );
}

function HistoryTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["recreations"],
    queryFn: getRecreations,
  });
  
  const [editingId, setEditingId] = useState<string | null>(null);

  if (isLoading) return <Loading />;
  if (error) return <ErrorState error={error} />;
  
  if (!data?.recreations || data.recreations.length === 0) {
    return <Empty emoji="📝" title="Aún no hay recreaciones">Planifica tu primera recreación para verla aquí.</Empty>;
  }

  if (editingId) {
    return (
      <div className="stack" style={{ gap: 24 }}>
        <div className="between">
          <Button onClick={() => setEditingId(null)}>← Volver a la lista</Button>
        </div>
        <RecreationEditor id={editingId} />
      </div>
    );
  }

  return (
    <div className="stack">
      {data.recreations.map((rec) => (
        <div key={rec.id} className="card card-pad between" style={{ alignItems: "center" }}>
          <div>
            <h3>{rec.title}</h3>
            <div className="row muted" style={{ fontSize: 13, marginTop: 4, gap: 16 }}>
              <span>Estado: <Badge>{rec.state}</Badge></span>
              <span>{new Date(rec.updated_at).toLocaleString()}</span>
            </div>
            <p className="sub" style={{ marginTop: 8 }}>{rec.original}</p>
          </div>
          <div>
            <Button variant="ghost" onClick={() => setEditingId(rec.id)}>
              <IcEdit /> Abrir
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}

function RecreationEditor({ id }: { id: string }) {
  const nav = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [riskAccepted, setRiskAccepted] = useState(false);

  const { data: rec, isLoading, error } = useQuery({
    queryKey: ["recreations", id],
    queryFn: () => getRecreation(id),
  });

  const update = useMutation({
    mutationFn: (updates: UpdateRecreationRequest) => updateRecreation(id, updates),
    onSuccess: (newData) => {
      queryClient.setQueryData(["recreations", id], newData);
      toast.ok("Cambios guardados");
    },
    onError: (e) => toast.err("No se pudo guardar", (e as Error).message),
  });

  const run = useMutation({
    mutationFn: () => runRecreation(id),
    onSuccess: (res) => {
      toast.ok("Ejecución iniciada");
      nav(`/runs/${res.run_id}`);
    },
    onError: (e) => toast.err("No se pudo ejecutar", (e as Error).message),
  });

  if (isLoading) return <Loading />;
  if (error || !rec) return <ErrorState error={error} />;

  const fair_use = rec.fair_use as FairUse;
  const ctaDisabled = (fair_use.requires_confirmation && !riskAccepted) || rec.state === "running";

  return (
    <div className="recreation-result stack" style={{ gap: 24 }}>
      {/* Fair-use card */}
      <div className="card card-pad fair-use-card">
        <div className="between">
          <h2>Evaluación de uso justo</h2>
          <Badge tone={RISK_TONE[fair_use.risk]}>{RISK_LABEL[fair_use.risk] ?? fair_use.risk}</Badge>
        </div>

        <div className="fair-use-bars">
          <div>
            <div className="fair-use-bar-label">
              <span>Cercanía con el original</span>
              <strong>{Math.round(fair_use.closeness * 100)}%</strong>
            </div>
            <div className="progress"><i style={{ width: `${Math.round(fair_use.closeness * 100)}%` }} /></div>
          </div>
          <div>
            <div className="fair-use-bar-label">
              <span>Transformación</span>
              <strong>{Math.round(fair_use.transformative * 100)}%</strong>
            </div>
            <div className="progress"><i style={{ width: `${Math.round(fair_use.transformative * 100)}%` }} /></div>
          </div>
        </div>

        <p className="fair-use-guidance">{fair_use.guidance}</p>

        {fair_use.requires_confirmation && (
          <>
            <div className="warn-banner" style={{ marginTop: 16 }}>
              <IcAlertTriangle />
              <div className="body">
                <strong>Esta recreación requiere confirmación.</strong> El nivel de cercanía con la obra original
                es alto — revisa la guía anterior antes de continuar para evitar problemas de derechos de autor.
              </div>
            </div>
            <label className="check" style={{ marginTop: 16 }}>
              <input
                type="checkbox"
                checked={riskAccepted}
                onChange={(e) => setRiskAccepted(e.target.checked)}
              />
              Entiendo el riesgo y quiero continuar
            </label>
          </>
        )}
      </div>

      {/* Output Video (if generated) */}
      {rec.state === "done" && typeof rec.result?.video_url === "string" && (
        <div className="card card-pad stack">
          <div className="between">
            <h2>Video Generado</h2>
            <Badge tone="ok">Completado</Badge>
          </div>
          <video 
            src={rec.result.video_url as string} 
            controls 
            autoPlay 
            loop 
            style={{ width: "100%", borderRadius: 8, background: "#000" }} 
          />
        </div>
      )}

      {/* Editor Plan */}
      <div className="card card-pad stack">
        <div>
          <div className="eyebrow">Detalles del Plan</div>
          <InlineEditableText
            value={rec.title}
            onSave={(v) => update.mutate({ title: v })}
            tag="h2"
          />
        </div>

        <div>
          <h3 style={{ marginBottom: 10 }}>Prompt V2V</h3>
          <InlineEditableTextarea
            value={rec.v2v_prompt}
            onSave={(v) => update.mutate({ v2v_prompt: v })}
          />
        </div>

        <div>
          <h3 style={{ marginBottom: 10 }}>Beats</h3>
          <EditableBeats
            beats={rec.beats}
            onSave={(newBeats) => update.mutate({ beats: newBeats })}
          />
        </div>

        <div className="row" style={{ gap: 24 }}>
          <div className="field" style={{ flex: 1 }}>
            <label>Referencia visual</label>
            <InlineEditableTextarea
              value={rec.reference_description}
              onSave={(v) => update.mutate({ reference_description: v })}
            />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label>Nota de audio</label>
            <InlineEditableTextarea
              value={rec.audio_note}
              onSave={(v) => update.mutate({ audio_note: v })}
            />
          </div>
        </div>
        
        <ProviderModelPicker
          provider={rec.provider || ""}
          model={rec.model || ""}
          onProvider={(v) => update.mutate({ provider: v })}
          onModel={(v) => update.mutate({ video_model: v })}
        />

        <div className="stack" style={{ gap: 8, marginTop: 24 }}>
          <div className="btn-row">
            <Button variant="primary" loading={run.isPending} disabled={ctaDisabled} onClick={() => run.mutate()}>
              <IcSparkles /> Ejecutar Generación
            </Button>
            {rec.run_id && (
              <Button onClick={() => nav(`/runs/${rec.run_id}`)}>
                Ver Run Actual
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

const _VIDEO_CAPS = ["text_to_video", "image_to_video", "video_to_video"];

function ProviderModelPicker({ provider, model, onProvider, onModel }: {
  provider: string; model: string; onProvider: (v: string) => void; onModel: (v: string) => void;
}) {
  const cat = useQuery<SdkProvider[]>({ queryKey: ["sdk-providers"], queryFn: getSdkProviders });
  // Only providers that can generate/transform video are usable for a recreation.
  const providers = (cat.data ?? []).filter((p) => p.capabilities.some((c) => _VIDEO_CAPS.includes(c)));
  const selected = providers.find((p) => p.id === provider);
  const models = (selected?.models ?? []).filter((m) => m.capabilities.some((c) => _VIDEO_CAPS.includes(c)));
  return (
    <div className="row" style={{ gap: 24, alignItems: "flex-start" }}>
      <div className="field" style={{ flex: 1 }}>
        <label>Proveedor de Video</label>
        <select className="select" value={provider}
          onChange={(e) => { onProvider(e.target.value); onModel(""); }}>
          <option value="">— elige proveedor —</option>
          {providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>
      <div className="field" style={{ flex: 1 }}>
        <label>Modelo</label>
        <select className="select mono" value={model} disabled={!selected}
          onChange={(e) => onModel(e.target.value)}>
          <option value="">auto</option>
          {models.map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
        </select>
      </div>
    </div>
  );
}

function InlineEditableText({ value, onSave, tag: Tag = "span" }: { value: string, onSave: (v: string) => void, tag?: any }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(value);

  useEffect(() => { setVal(value); }, [value]);

  if (editing) {
    return (
      <div className="row" style={{ gap: 8, alignItems: "center" }}>
        <input className="input" autoFocus value={val} onChange={e => setVal(e.target.value)} />
        <Button variant="primary" size="sm" onClick={() => { onSave(val); setEditing(false); }}>Guardar</Button>
        <Button variant="ghost" size="sm" onClick={() => { setVal(value); setEditing(false); }}>Cancelar</Button>
      </div>
    );
  }
  return (
    <div className="row" style={{ gap: 8, alignItems: "center" }}>
      <Tag>{value}</Tag>
      <button className="icon-btn" onClick={() => setEditing(true)}><IcEdit /></button>
    </div>
  );
}

function InlineEditableTextarea({ value, onSave }: { value: string, onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(value);

  useEffect(() => { setVal(value); }, [value]);

  if (editing) {
    return (
      <div className="stack" style={{ gap: 8 }}>
        <textarea className="textarea" autoFocus value={val} onChange={e => setVal(e.target.value)} rows={4} />
        <div className="row" style={{ gap: 8 }}>
          <Button variant="primary" size="sm" onClick={() => { onSave(val); setEditing(false); }}>Guardar</Button>
          <Button variant="ghost" size="sm" onClick={() => { setVal(value); setEditing(false); }}>Cancelar</Button>
        </div>
      </div>
    );
  }
  return (
    <div className="copy-block" style={{ position: "relative" }}>
      <pre style={{ whiteSpace: "pre-wrap", margin: 0, paddingRight: 40 }}>{value}</pre>
      <button type="button" className="copy-block-btn" style={{ top: 8 }} onClick={() => setEditing(true)}>
        <IcEdit />
      </button>
    </div>
  );
}

function EditableBeats({ beats, onSave }: { beats: RecreationBeat[], onSave: (b: RecreationBeat[]) => void }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(() => JSON.stringify(beats, null, 2));

  useEffect(() => { setVal(JSON.stringify(beats, null, 2)); }, [beats]);

  if (editing) {
    return (
      <div className="stack" style={{ gap: 8 }}>
        <textarea className="textarea mono" value={val} onChange={e => setVal(e.target.value)} rows={10} style={{ fontSize: 13 }} />
        <div className="row" style={{ gap: 8 }}>
          <Button variant="primary" size="sm" onClick={() => {
            try {
              const parsed = JSON.parse(val);
              onSave(parsed);
              setEditing(false);
            } catch {
              alert("JSON inválido");
            }
          }}>Guardar</Button>
          <Button variant="ghost" size="sm" onClick={() => { setVal(JSON.stringify(beats, null, 2)); setEditing(false); }}>Cancelar</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="stack" style={{ position: "relative" }}>
      <button className="icon-btn" style={{ position: "absolute", top: -8, right: 0 }} onClick={() => setEditing(true)}><IcEdit /></button>
      {beats.map((beat, i) => (
        <div key={i} className="beat-row">
          <span className="beat-pill">{beat.beat}</span>
          <span className="beat-duration">{beat.duration_s}s</span>
          <span className="beat-desc">{beat.description}</span>
        </div>
      ))}
    </div>
  );
}

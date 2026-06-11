import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  planRecreation, sceneTrendMatch, runRecreation, getRecreations, updateRecreation, getRecreation,
  type FairUse, type SceneCandidate, type RecreationBeat,
  type UpdateRecreationRequest
} from "../api/client";
import { Badge, Button, Empty, ErrorState, Field, Loading, useToast, Tabs } from "../ui/primitives";
import { IcAlertTriangle, IcRadar, IcSparkles, IcWand, IcEdit } from "../ui/icons";

const RISK_TONE: Record<FairUse["risk"] | string, "ok" | "warn" | "err"> = {
  low: "ok", medium: "warn", high: "err",
};
const RISK_LABEL: Record<FairUse["risk"] | string, string> = {
  low: "Riesgo bajo", medium: "Riesgo medio", high: "Riesgo alto",
};

export function RecreationPage() {
  const [activeTab, setActiveTab] = useState<"new" | "history">("new");

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
          { id: "history", label: "Borradores e Historial" }
        ]}
      />

      <div style={{ marginTop: 24 }}>
        {activeTab === "new" && <NewRecreationTab onGoToHistory={() => setActiveTab("history")} />}
        {activeTab === "history" && <HistoryTab />}
      </div>
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
        {trendMatch.isSuccess && trendMatch.data.length === 0 && (
          <Empty emoji="📡" title="Sin resultados">
            No se encontraron escenas en tendencia ahora mismo — vuelve a intentarlo más tarde.
          </Empty>
        )}
        {trendMatch.isSuccess && trendMatch.data.length > 0 && (
          <div className="scene-candidates">
            {trendMatch.data.map((candidate, i) => (
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
        
        <div className="row" style={{ gap: 24, alignItems: "center" }}>
          <div className="field" style={{ flex: 1 }}>
            <label>Proveedor de Video</label>
            <InlineEditableText
              value={rec.provider || "veo"}
              onSave={(v) => update.mutate({ provider: v })}
            />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label>Modelo (opcional)</label>
            <InlineEditableText
              value={rec.model || ""}
              onSave={(v) => update.mutate({ video_model: v })}
            />
          </div>
        </div>

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

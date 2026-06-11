import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  planRecreation, sceneTrendMatch,
  type FairUse, type RecreationPlan, type SceneCandidate,
} from "../api/client";
import { Badge, Button, Empty, ErrorState, Field, Loading, useToast } from "../ui/primitives";
import { IcAlertTriangle, IcCopy, IcRadar, IcSparkles, IcWand } from "../ui/icons";

const RISK_TONE: Record<FairUse["risk"], "ok" | "warn" | "err"> = {
  low: "ok", medium: "warn", high: "err",
};
const RISK_LABEL: Record<FairUse["risk"], string> = {
  low: "Riesgo bajo", medium: "Riesgo medio", high: "Riesgo alto",
};

export function RecreationPage() {
  const nav = useNavigate();
  const toast = useToast();

  // -------------------------------------------------------------- Radar
  const trendMatch = useMutation({
    mutationFn: () => sceneTrendMatch([]),
    onError: (e) => toast.err("No se pudo buscar tendencias", (e as Error).message),
  });

  // -------------------------------------------------------------- Form
  const [original, setOriginal] = useState("");
  const [niche, setNiche] = useState("general");
  const [twist, setTwist] = useState("");
  const [riskAccepted, setRiskAccepted] = useState(false);

  const plan = useMutation({
    mutationFn: () => planRecreation(original.trim(), niche.trim() || "general", twist.trim()),
    onSuccess: () => setRiskAccepted(false),
    onError: (e) => toast.err("No se pudo planificar la recreación", (e as Error).message),
  });

  const useCandidate = (candidate: SceneCandidate) => {
    setOriginal(candidate.scene);
    requestAnimationFrame(() => {
      document.getElementById("recreation-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  const canPlan = original.trim().length >= 3 && twist.trim().length >= 3 && !plan.isPending;

  const openInDirector = () => {
    if (!plan.data) return;
    const p = plan.data;
    nav("/director", {
      state: {
        spec: {
          nodes: [
            { id: "plan", capability: "llm_text", params: { task: "recreation_plan" }, depends_on: [], max_retries: 2 },
            { id: "v2v", capability: "video_to_video", params: { prompt: p.v2v_prompt }, depends_on: ["plan"], max_retries: 2 },
            { id: "voice", capability: "tts", params: {}, depends_on: ["plan"], max_retries: 2 },
            { id: "compose", capability: "compose_short", params: {}, depends_on: ["v2v", "voice"], max_retries: 2 },
          ],
        },
        templateName: `Recreación: ${p.title}`,
      },
    });
  };

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

      {/* ---------------------------------------------------------- Radar */}
      <div className="card card-pad stack" style={{ marginBottom: 22 }}>
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
      <div className="card card-pad stack" id="recreation-form" style={{ marginBottom: 22 }}>
        <div>
          <h2>Planificar recreación</h2>
          <p className="sub" style={{ margin: "4px 0 0" }}>
            Describe la escena original y el giro transformativo — el director evaluará el riesgo de uso justo.
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
            <IcSparkles /> Planificar
          </Button>
        </div>
      </div>

      {/* ---------------------------------------------------------- Result */}
      {plan.isPending && <Loading />}
      {plan.isError && <ErrorState error={plan.error} />}
      {plan.data && (
        <RecreationResult
          plan={plan.data}
          riskAccepted={riskAccepted}
          onRiskAcceptedChange={setRiskAccepted}
          onOpenInDirector={openInDirector}
        />
      )}
    </div>
  );
}

function RecreationResult({ plan, riskAccepted, onRiskAcceptedChange, onOpenInDirector }: {
  plan: RecreationPlan;
  riskAccepted: boolean;
  onRiskAcceptedChange: (v: boolean) => void;
  onOpenInDirector: () => void;
}) {
  const { fair_use } = plan;
  const ctaDisabled = fair_use.requires_confirmation && !riskAccepted;

  return (
    <div className="recreation-result">
      {/* Fair-use card — always first */}
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
            <div className="warn-banner">
              <IcAlertTriangle />
              <div className="body">
                <strong>Esta recreación requiere confirmación.</strong> El nivel de cercanía con la obra original
                es alto — revisa la guía anterior antes de continuar para evitar problemas de derechos de autor.
              </div>
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={riskAccepted}
                onChange={(e) => onRiskAcceptedChange(e.target.checked)}
              />
              Entiendo el riesgo y quiero continuar
            </label>
          </>
        )}
      </div>

      {/* Plan */}
      <div className="card card-pad stack">
        <div>
          <div className="eyebrow">Plan</div>
          <h2 style={{ marginTop: 6 }}>{plan.title}</h2>
        </div>

        <div>
          <h3 style={{ marginBottom: 10 }}>Beats</h3>
          <div className="stack">
            {plan.beats.map((beat, i) => (
              <div key={i} className="beat-row">
                <span className="beat-pill">{beat.beat}</span>
                <span className="beat-duration">{beat.duration_s}s</span>
                <span className="beat-desc">{beat.description}</span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h3 style={{ marginBottom: 10 }}>Prompt V2V</h3>
          <CopyBlock text={plan.v2v_prompt} />
        </div>

        <div className="row">
          <div className="field" style={{ flex: 1 }}>
            <label>Referencia visual</label>
            <p className="muted" style={{ margin: 0, fontSize: 13.5 }}>{plan.reference_description}</p>
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label>Nota de audio</label>
            <p className="muted" style={{ margin: 0, fontSize: 13.5 }}>{plan.audio_note}</p>
          </div>
        </div>

        {plan.provider_hint.length > 0 && (
          <div>
            <h3 style={{ marginBottom: 10 }}>Proveedores sugeridos</h3>
            <div className="tag-list">
              {plan.provider_hint.map((p) => <Badge key={p} tone="accent">{p}</Badge>)}
            </div>
          </div>
        )}

        <div className="btn-row">
          <Button variant="primary" disabled={ctaDisabled} onClick={onOpenInDirector}>
            <IcWand /> Abrir en Director
          </Button>
        </div>
      </div>
    </div>
  );
}

function CopyBlock({ text }: { text: string }) {
  const toast = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast.ok("Copiado al portapapeles");
    } catch {
      toast.err("No se pudo copiar");
    }
  };
  return (
    <div style={{ position: "relative" }}>
      <pre className="copy-block">{text}</pre>
      <button type="button" className="copy-block-btn" onClick={copy} aria-label="Copiar">
        <IcCopy />
      </button>
    </div>
  );
}

// Standalone meme generator (§16 follow-up). Memes are one-off content — no
// characters, no series, no topic counts. A minimal form posts a small DAG
// straight to /runs and drops the user on the run timeline.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { startRun, type DagSpecDto } from "../api/client";
import { Button, Field, useToast } from "../ui/primitives";
import { IcLaugh, IcSparkles } from "../ui/icons";

const DURATIONS = [8, 12, 15] as const;

function buildMemeSpec(concept: string, durationS: number): DagSpecDto {
  return {
    nodes: [
      { id: "structure", capability: "native_short", params: { concept, content_type: "meme" }, depends_on: [], max_retries: 2 },
      { id: "clips", capability: "text_to_video", params: { duration_s: durationS }, depends_on: ["structure"], max_retries: 2 },
      { id: "compose", capability: "compose_short", params: {}, depends_on: ["clips"], max_retries: 1 },
    ],
  };
}

export function MemesPage() {
  const nav = useNavigate();
  const toast = useToast();

  const [concept, setConcept] = useState("");
  const [durationS, setDurationS] = useState<typeof DURATIONS[number]>(12);

  const generate = useMutation({
    mutationFn: () => startRun(buildMemeSpec(concept.trim(), durationS)),
    onSuccess: (res) => nav(`/runs/${res.run_id}`),
    onError: (e) => toast.err("No se pudo generar el meme", (e as Error).message),
  });

  const canGenerate = concept.trim().length >= 3 && !generate.isPending;

  return (
    <div className="page page-narrow">
      <div className="page-head">
        <div>
          <div className="eyebrow">Estudio</div>
          <h1>Memes</h1>
          <p className="sub">
            Genera un meme suelto — sin personajes ni temporadas. Describe la idea y el giro, elige duración y dale a generar.
          </p>
        </div>
      </div>

      <div className="card card-pad stack">
        <Field label="Concepto del meme" hint="Setup y giro — cuanto más concreto, mejor sale el chiste.">
          <textarea
            className="textarea"
            rows={5}
            placeholder="Idea del meme — setup y giro"
            value={concept}
            onChange={(e) => setConcept(e.target.value)}
          />
        </Field>

        <Field label="Duración" hint="Duración aproximada del clip final.">
          <select className="select" value={durationS} onChange={(e) => setDurationS(Number(e.target.value) as typeof DURATIONS[number])}>
            {DURATIONS.map((d) => <option key={d} value={d}>{d}s</option>)}
          </select>
        </Field>

        <div className="btn-row">
          <Button variant="primary" loading={generate.isPending} disabled={!canGenerate} onClick={() => generate.mutate()}>
            <IcSparkles /> Generar meme
          </Button>
        </div>
      </div>

      <div className="card card-pad explainer-card">
        <IcLaugh />
        <div>
          <h3>Los memes son contenido suelto</h3>
          <p className="muted" style={{ margin: "4px 0 0" }}>
            Sin personajes fijos ni temporadas — cada meme se genera de una vez. Para series con personajes recurrentes, usa Pods.
          </p>
        </div>
      </div>
    </div>
  );
}

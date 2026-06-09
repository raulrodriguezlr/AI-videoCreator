import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type ContentType, type Pod, type PodBlueprint } from "../api/client";
import { Badge, Button, Field, useToast } from "../ui/primitives";
import { IcSparkles, IcWand } from "../ui/icons";
import { prettyStyle } from "./PodsListPage";

// The big content-type picker (Fase 8). "Otro" + the free-text idea cover any
// concept the presets don't. Each type drives the pod's duration + character
// strategy server-side via content_profile().
const CONTENT_TYPES: { value: ContentType; label: string; hint: string }[] = [
  { value: "story", label: "Historias (largas/cortas)", hint: "Serie narrativa con personajes recurrentes y arco" },
  { value: "meme", label: "Memes / humor viral", hint: "Clips cortos, formato meme; personajes opcionales" },
  { value: "scene_recreation", label: "Recreación de escenas", hint: "Recrea una escena famosa con un giro (vídeo-a-vídeo)" },
  { value: "educational", label: "Educación / divulgación", hint: "El guionista decide la duración según el tema" },
  { value: "other", label: "Otro (descríbelo abajo)", hint: "Concepto personalizado; la IA infiere el formato" },
];

export function CreatePodPage() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

  const [idea, setIdea] = useState("");
  const [language, setLanguage] = useState("es");
  const [contentType, setContentType] = useState<ContentType>("story");
  const [chars, setChars] = useState(3);
  const [topics, setTopics] = useState(5);
  const [blueprint, setBlueprint] = useState<PodBlueprint | null>(null);
  const [name, setName] = useState("");

  const ct = CONTENT_TYPES.find((c) => c.value === contentType)!;
  // Story is the only preset that features named, reference-image characters.
  const showCharacters = contentType === "story" || contentType === "meme";

  const enhance = useMutation({
    mutationFn: () => api.post<{ enhanced: string }>("/wizard/enhance", { idea, language }),
    onSuccess: (r) => { setIdea(r.enhanced); toast.ok("Idea mejorada por la IA"); },
    onError: (e) => toast.err("No se pudo mejorar", (e as Error).message),
  });
  const draft = useMutation({
    mutationFn: () => api.post<PodBlueprint>("/wizard/pods/draft", {
      idea, language, character_count: chars, topic_count: topics,
      content_type: contentType,
    }),
    onSuccess: (bp) => { setBlueprint(bp); setName(bp.series_name); toast.ok("Blueprint generado", "Revísalo y crea el pod"); },
    onError: (e) => toast.err("No se pudo generar", (e as Error).message),
  });
  const create = useMutation({
    mutationFn: () => api.post<Pod>("/wizard/pods", { name, blueprint }),
    onSuccess: (pod) => { qc.invalidateQueries({ queryKey: ["pods"] }); toast.ok("Pod creado"); nav(`/pods/${pod.id}`); },
    onError: (e) => toast.err("No se pudo crear", (e as Error).message),
  });

  return (
    <div className="page page-narrow">
      <div className="page-head">
        <div>
          <div className="eyebrow">Asistente IA</div>
          <h1>Crear un pod</h1>
          <p className="sub">Describe tu idea, deja que la IA la pula y proponga una serie completa con personajes y temas.</p>
        </div>
      </div>

      <div className="card card-pad stack">
        <Field label="Tipo de contenido" hint={ct.hint}>
          <select className="select" value={contentType} onChange={(e) => setContentType(e.target.value as ContentType)}>
            {CONTENT_TYPES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </Field>
        <Field label="Tu idea" hint="Una o dos frases bastan; el botón 'Mejorar' la enriquecerá.">
          <textarea className="textarea" rows={5} value={idea} placeholder="p.ej. Curiosidades del espacio explicadas para niños de 5 a 8 años con una mascota astronauta"
            onChange={(e) => setIdea(e.target.value)} />
        </Field>
        <div className="row">
          <Field label="Idioma"><input className="input" value={language} onChange={(e) => setLanguage(e.target.value)} /></Field>
          {showCharacters && (
            <Field label="Nº personajes"><input className="input" type="number" min={1} max={5} value={chars} onChange={(e) => setChars(Number(e.target.value))} /></Field>
          )}
          <Field label="Nº temas"><input className="input" type="number" min={1} max={20} value={topics} onChange={(e) => setTopics(Number(e.target.value))} /></Field>
        </div>
        <div className="btn-row">
          <Button variant="ghost" loading={enhance.isPending} disabled={idea.trim().length < 3} onClick={() => enhance.mutate()}>
            <IcSparkles /> Mejorar idea
          </Button>
          <Button variant="primary" loading={draft.isPending} disabled={idea.trim().length < 3} onClick={() => draft.mutate()}>
            <IcWand /> Generar blueprint
          </Button>
        </div>
      </div>

      {blueprint && (
        <div className="card card-pad stack" style={{ marginTop: 18 }}>
          <h2>Revisar serie</h2>
          <div className="row">
            <Field label="Nombre del pod"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Nombre de la serie"><input className="input" value={blueprint.series_name}
              onChange={(e) => setBlueprint({ ...blueprint, series_name: e.target.value })} /></Field>
          </div>
          <div className="tag-list">
            <Badge tone="accent">{prettyStyle(blueprint.style_profile)}</Badge>
            <Badge tone="accent">{CONTENT_TYPES.find((c) => c.value === blueprint.content_type)?.label ?? blueprint.content_type}</Badge>
            <Badge>{blueprint.bible.genre}</Badge>
            <Badge>{blueprint.bible.audience}</Badge>
            <Badge>{blueprint.duration_seconds}s/episodio</Badge>
          </div>
          {blueprint.characters.length > 0 && (
            <div>
              <div className="dim" style={{ fontSize: 11.5, marginBottom: 6 }}>PERSONAJES</div>
              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(180px,1fr))" }}>
                {blueprint.characters.map((c, i) => (
                  <div key={i} className="scene"><strong>{c.name}</strong> <span className="dim">· {c.role}</span>
                    {c.personality && <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>{c.personality}</div>}
                  </div>
                ))}
              </div>
            </div>
          )}
          <div>
            <div className="dim" style={{ fontSize: 11.5, marginBottom: 6 }}>TEMAS SEMILLA</div>
            <div className="tag-list">{blueprint.topic_seeds.map((t, i) => <Badge key={i}>{t}</Badge>)}</div>
          </div>
          <div className="btn-row" style={{ justifyContent: "flex-end" }}>
            <Button variant="ghost" onClick={() => setBlueprint(null)}>Descartar</Button>
            <Button variant="primary" loading={create.isPending} disabled={!name.trim()} onClick={() => create.mutate()}>Crear pod</Button>
          </div>
        </div>
      )}
    </div>
  );
}

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api, streamOllamaPull, type LlmConfig, type RecommendedModels,
} from "../api/client";
import {
  Badge, Button, ErrorState, Field, Loading, useToast,
} from "../ui/primitives";
import { IcCloud, IcCpu, IcDownload, IcFile, IcRefresh, IcServer } from "../ui/icons";
import { JsonEditor } from "../components/JsonEditor";

export function SettingsPage() {
  const llm = useQuery<LlmConfig>({ queryKey: ["llm-config"], queryFn: () => api.get("/system/llm") });

  return (
    <div className="page page-narrow">
      <div className="page-head">
        <div>
          <div className="eyebrow">Sistema</div>
          <h1>Ajustes</h1>
          <p className="sub">Elige el motor de texto (nube o local) y gestiona tus claves de proveedor.</p>
        </div>
      </div>
      {llm.isLoading && <Loading />}
      {llm.isError && <ErrorState error={llm.error} />}
      {llm.data && <LlmSection cfg={llm.data} />}
      <div style={{ height: 22 }} />
      <SecretsSection />
      <div style={{ height: 22 }} />
      <RulesSection />
    </div>
  );
}

// ---------------------------------------------------------------- Global rules
function RulesSection() {
  return (
    <div className="card">
      <div className="card-head"><h2>Reglas de vídeo (video_rules.json)</h2></div>
      <div className="card-pad stack">
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>
          <IcFile /> Reglas globales compartidas por todos los pods. Edición JSON en crudo.
        </p>
        <JsonEditor
          getPath="/system/files/video_rules.json"
          putPath="/system/files/video_rules.json"
          queryKey={["system-file", "video_rules.json"]}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- LLM
function LlmSection({ cfg }: { cfg: LlmConfig }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [provider, setProvider] = useState(cfg.provider);
  const [geminiModel, setGeminiModel] = useState(cfg.gemini_model);
  const [ollamaModel, setOllamaModel] = useState(cfg.ollama_model);
  const [pulling, setPulling] = useState<string | null>(null);
  const [pullPct, setPullPct] = useState(0);
  const recs = useQuery<RecommendedModels>({
    queryKey: ["ollama-recommended"], queryFn: () => api.get("/system/llm/ollama/recommended"),
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["llm-config"] });

  const save = useMutation({
    mutationFn: () => api.put<LlmConfig>("/system/llm", {
      provider, gemini_model: geminiModel, ollama_model: ollamaModel,
    }),
    onSuccess: () => { refresh(); toast.ok("Motor actualizado", "Se aplica al instante, sin reiniciar"); },
    onError: (e) => toast.err("No se pudo cambiar", (e as Error).message),
  });

  const serve = useMutation({
    mutationFn: () => api.post<unknown>("/system/llm/ollama/serve"),
    onSuccess: () => { refresh(); toast.ok("Ollama arrancado"); },
    onError: (e) => toast.err("No se pudo arrancar", (e as Error).message),
  });

  const pull = async (model: string) => {
    setPulling(model); setPullPct(0);
    try {
      await streamOllamaPull(model, (obj) => {
        const total = Number(obj.total ?? 0), done = Number(obj.completed ?? 0);
        if (total > 0) setPullPct(Math.round((done / total) * 100));
        if (obj.status === "error") toast.err("Error al descargar", String(obj.error ?? ""));
      });
      toast.ok("Modelo descargado", model);
      refresh();
    } catch (e) {
      toast.err("Descarga interrumpida", (e as Error).message);
    } finally {
      setPulling(null);
    }
  };

  const o = cfg.ollama;

  return (
    <div className="card">
      <div className="card-head between">
        <h2>Motor de texto (LLM)</h2>
        <Button variant="ghost" size="sm" onClick={refresh}><IcRefresh /> Actualizar</Button>
      </div>
      <div className="card-pad stack">
        <div className="seg" role="tablist">
          <button className={provider === "gemini" ? "on" : ""} onClick={() => setProvider("gemini")}>
            <IcCloud width={15} height={15} /> Gemini (nube)
          </button>
          <button className={provider === "ollama" ? "on" : ""} onClick={() => setProvider("ollama")}>
            <IcCpu width={15} height={15} /> Ollama (local)
          </button>
        </div>

        {provider === "gemini" ? (
          <div className="stack">
            <div className="between">
              <span className="muted">Estado de la clave</span>
              <Badge tone={cfg.gemini_key_present ? "ok" : "warn"}>
                {cfg.gemini_key_present ? "GOOGLE_API_KEY presente" : "falta la clave"}
              </Badge>
            </div>
            <Field label="Modelo Gemini">
              <input className="input mono" value={geminiModel} onChange={(e) => setGeminiModel(e.target.value)} />
            </Field>
          </div>
        ) : (
          <div className="stack">
            <div className="statpill">
              <IcServer width={16} height={16} />
              <div style={{ flex: 1 }}>
                <div className="label">Servidor Ollama</div>
                <div className="val mono" style={{ fontSize: 12 }}>{o.base_url}</div>
              </div>
              <Badge tone={o.running ? "ok" : "err"}>{o.running ? "en marcha" : "apagado"}</Badge>
            </div>

            {!o.running && (
              <div className="between" style={{ gap: 12 }}>
                <span className="muted" style={{ fontSize: 13 }}>Ollama no responde. Arráncalo para empezar.</span>
                <Button variant="primary" size="sm" loading={serve.isPending} onClick={() => serve.mutate()}>
                  <IcServer /> Arrancar Ollama
                </Button>
              </div>
            )}

            <Field
              label="Modelo recomendado para tu GPU"
              hint={recs.data?.vram_gb != null
                ? `GPU detectada: ${recs.data.vram_gb} GB VRAM — solo se habilitan los que caben.`
                : "VRAM no detectada — se muestran todos los modelos."}
            >
              <select className="select" value={ollamaModel} onChange={(e) => setOllamaModel(e.target.value)}>
                {!(recs.data?.models ?? []).some((m) => m.name === ollamaModel) && (
                  <option value={ollamaModel}>{ollamaModel} (personalizado)</option>
                )}
                {(recs.data?.models ?? []).map((m) => (
                  <option key={m.name} value={m.name} disabled={!m.fits}>
                    {m.label} · {m.params} · ~{m.min_vram_gb}GB
                    {m.installed ? " · ✓ instalado" : ""}{m.fits ? "" : " · no cabe"}
                  </option>
                ))}
              </select>
            </Field>
            {(() => {
              const sel = recs.data?.models.find((m) => m.name === ollamaModel);
              return sel ? <p className="dim" style={{ fontSize: 12.5, margin: "-4px 0 0" }}>{sel.notes}</p> : null;
            })()}
            <Field label="…o un modelo personalizado">
              <input className="input mono" value={ollamaModel} placeholder="autor/modelo:tag"
                onChange={(e) => setOllamaModel(e.target.value)} />
            </Field>

            <div className="between">
              <div className="tag-list">
                {o.models.length === 0 && <span className="dim" style={{ fontSize: 13 }}>Ningún modelo instalado.</span>}
                {o.models.map((m) => (
                  <button key={m} className={`badge ${m === ollamaModel ? "accent" : ""}`} style={{ cursor: "pointer" }}
                    onClick={() => setOllamaModel(m)}>{m}</button>
                ))}
              </div>
              <Button size="sm" loading={pulling === ollamaModel} disabled={!o.running || !!pulling}
                onClick={() => pull(ollamaModel)}>
                <IcDownload /> Descargar
              </Button>
            </div>

            {pulling && (
              <div>
                <div className="progress"><i style={{ width: `${pullPct}%` }} /></div>
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Descargando <span className="mono">{pulling}</span> · {pullPct}%</div>
              </div>
            )}

            {!o.current_model_installed && o.running && (
              <div className="muted" style={{ fontSize: 12.5 }}>
                ⚠️ El modelo seleccionado no está instalado todavía — descárgalo antes de usarlo.
              </div>
            )}
          </div>
        )}

        <div className="btn-row" style={{ justifyContent: "flex-end" }}>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Aplicar motor</Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Secrets
const KNOWN = ["google", "elevenlabs", "artlist"];

function SecretsSection() {
  const qc = useQueryClient();
  const toast = useToast();
  const keys = useQuery<{ providers: string[] }>({ queryKey: ["secrets"], queryFn: () => api.get("/secrets") });
  const [draft, setDraft] = useState<Record<string, string>>({});

  const setKey = useMutation({
    mutationFn: (p: string) => api.put(`/secrets/${p}`, { value: draft[p] }),
    onSuccess: (_d, p) => { setDraft((x) => ({ ...x, [p]: "" })); qc.invalidateQueries({ queryKey: ["secrets"] }); toast.ok("Clave guardada", p); },
    onError: (e) => toast.err("No se pudo guardar", (e as Error).message),
  });
  const delKey = useMutation({
    mutationFn: (p: string) => api.delete(`/secrets/${p}`),
    onSuccess: (_d, p) => { qc.invalidateQueries({ queryKey: ["secrets"] }); toast.ok("Clave eliminada", p); },
  });

  const stored = new Set(keys.data?.providers ?? []);

  return (
    <div className="card">
      <div className="card-head"><h2>Claves de proveedor (BYO keys)</h2></div>
      <div className="card-pad stack">
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>
          Tus claves se guardan en el servidor y nunca se devuelven por la API. Solo verás si están configuradas.
        </p>
        {KNOWN.map((p) => (
          <div key={p} className="between" style={{ gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 130 }}>
              <span style={{ fontWeight: 600, textTransform: "capitalize" }}>{p}</span>
              {stored.has(p) && <Badge tone="ok">configurada</Badge>}
            </div>
            <input className="input" type="password" placeholder={stored.has(p) ? "•••••••• (reemplazar)" : "pega tu clave"}
              value={draft[p] ?? ""} onChange={(e) => setDraft((x) => ({ ...x, [p]: e.target.value }))} style={{ flex: 1 }} />
            <Button size="sm" disabled={!draft[p]} loading={setKey.isPending && setKey.variables === p} onClick={() => setKey.mutate(p)}>Guardar</Button>
            {stored.has(p) && <Button size="sm" variant="danger" onClick={() => delKey.mutate(p)}>Borrar</Button>}
          </div>
        ))}
      </div>
    </div>
  );
}

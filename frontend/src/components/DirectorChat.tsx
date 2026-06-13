// Conversational recipe editor — left: current recipe (mini DAG + node list),
// right: chat history with the director agent. Each turn proposes a JSON
// Patch against the spec, rendered as a readable diff the user can apply
// or discard.
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  directorChat, getSdkProviders, startRun,
  type DagSpecDto, type DirectorChatResponse, type JsonPatchOp, type SdkProvider,
} from "../api/client";
import { Button, Empty, useToast } from "../ui/primitives";
import { IcCheck, IcSend, IcSparkles, IcX } from "../ui/icons";
import { DagPipeline } from "./DagPipeline";
import { ProviderSelect } from "./ProviderSelect";

const PROVIDER_CAPABILITIES = ["text_to_video", "video_to_video"] as const;

/** Returns a new spec with `params.provider` set/removed on every node whose
 * capability is text_to_video / video_to_video (and tts, when at least one
 * SDK provider declares that capability). */
function applyProviderToSpec(spec: DagSpecDto, provider: string | null, ttsSupported: boolean): DagSpecDto {
  const capabilities: string[] = [...PROVIDER_CAPABILITIES];
  if (ttsSupported) capabilities.push("tts");
  return {
    nodes: spec.nodes.map((node) => {
      if (!capabilities.includes(node.capability)) return node;
      const params = { ...node.params };
      if (provider) params.provider = provider;
      else delete params.provider;
      return { ...node, params };
    }),
  };
}

interface ChatTurn {
  role: "user" | "assistant";
  text: string;
  patch?: JsonPatchOp[];
  nextSpec?: DagSpecDto;
  resolved?: "applied" | "discarded";
}

export function DirectorChat({ initialSpec }: { initialSpec: DagSpecDto }) {
  const nav = useNavigate();
  const toast = useToast();
  const [spec, setSpec] = useState<DagSpecDto>(initialSpec);
  const [history, setHistory] = useState<ChatTurn[]>([]);
  const [message, setMessage] = useState("");
  const [provider, setProvider] = useState<string | null>(null);
  const historyRef = useRef<HTMLDivElement>(null);

  const sdkProviders = useQuery<SdkProvider[]>({
    queryKey: ["sdk-providers"],
    queryFn: getSdkProviders,
    retry: false,
  });
  const ttsSupported = (sdkProviders.data ?? []).some((p) => p.capabilities.includes("tts"));

  const handleProviderChange = (id: string | null) => {
    setProvider(id);
    setSpec((s) => applyProviderToSpec(s, id, ttsSupported));
  };

  const chat = useMutation({
    mutationFn: (msg: string) => directorChat(spec, msg),
    onSuccess: (res: DirectorChatResponse) => {
      setHistory((h) => [...h, {
        role: "assistant",
        text: res.explanation || "Sin cambios sugeridos.",
        patch: res.patch,
        nextSpec: res.spec,
      }]);
      requestAnimationFrame(() => {
        historyRef.current?.scrollTo({ top: historyRef.current.scrollHeight, behavior: "smooth" });
      });
    },
    onError: (e) => toast.err("El director no respondió", (e as Error).message),
  });

  const generate = useMutation({
    mutationFn: () => startRun(spec),
    onSuccess: (res) => nav(`/runs/${res.run_id}`),
    onError: (e) => toast.err("No se pudo iniciar la generación", (e as Error).message),
  });

  const send = () => {
    const text = message.trim();
    if (!text || chat.isPending) return;
    setHistory((h) => [...h, { role: "user", text }]);
    setMessage("");
    chat.mutate(text);
    requestAnimationFrame(() => {
      historyRef.current?.scrollTo({ top: historyRef.current.scrollHeight, behavior: "smooth" });
    });
  };

  const resolveTurn = (index: number, action: "applied" | "discarded") => {
    setHistory((h) => h.map((turn, i) => {
      if (i !== index) return turn;
      if (action === "applied" && turn.nextSpec) {
        setSpec(applyProviderToSpec(turn.nextSpec, provider, ttsSupported));
      }
      return { ...turn, resolved: action };
    }));
    if (action === "applied") toast.ok("Receta actualizada");
  };

  return (
    <div className="director-layout">
      {/* ------------------------------------------------------------ Recipe */}
      <div className="card card-pad stack">
        <div className="between">
          <h2>Receta actual</h2>
          <span className="dim mono" style={{ fontSize: 11 }}>{spec.nodes.length} nodos</span>
        </div>
        <ProviderSelect value={provider} onChange={handleProviderChange} capability="text_to_video" label="Proveedor de video" />
        <Button variant="primary" loading={generate.isPending} disabled={spec.nodes.length === 0}
          onClick={() => generate.mutate()}>
          <IcSparkles /> Generar
        </Button>
        <DagPipeline nodes={spec.nodes} />
        <div className="divider" />
        <div className="recipe-list">
          {spec.nodes.map((node) => (
            <div key={node.id} className="recipe-node">
              <div className="recipe-node-head">
                <span className="recipe-node-id">{node.id}</span>
                <span className="dim" style={{ fontSize: 11.5 }}>{node.capability}</span>
              </div>
              <div className="recipe-node-deps">
                depende de: {node.depends_on.length ? node.depends_on.join(", ") : "—"}
                {" · "}reintentos: {node.max_retries}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ------------------------------------------------------------- Chat */}
      <div className="card chat-panel">
        <div className="card-head">
          <h2>Director</h2>
          <span className="sub">Pídele cambios en lenguaje natural</span>
        </div>
        <div className="chat-history" ref={historyRef}>
          {history.length === 0 && (
            <Empty emoji="🎬" title="¿Cómo funciona el Director?">
              La receta de la izquierda es el pipeline que producirá tu video
              (estructura → clips → voz → montaje). Aquí la editas en lenguaje
              natural: "haz el hook más agresivo", "añade subtítulos",
              "cámbialo a 45 segundos". Cuando te guste, pulsa{" "}
              <strong>Generar</strong> y se ejecuta de verdad: cada nodo corre
              con su proveedor (Veo, LTX, ElevenLabs…) y acabas en la pantalla
              del run con el video final.
            </Empty>
          )}
          {history.map((turn, i) => (
            <div key={i} className={`chat-msg ${turn.role}`}>
              <span className="chat-role">{turn.role === "user" ? "Tú" : "Director"}</span>
              <div className="chat-bubble">{turn.text}</div>
              {turn.patch && turn.patch.length > 0 && (
                <PatchPreview turn={turn} onResolve={(action) => resolveTurn(i, action)} />
              )}
              {turn.patch && turn.patch.length === 0 && turn.role === "assistant" && (
                <span className="dim" style={{ fontSize: 12, marginLeft: 4 }}>Sin cambios propuestos.</span>
              )}
            </div>
          ))}
          {chat.isPending && (
            <div className="chat-msg assistant">
              <span className="chat-role">Director</span>
              <div className="chat-bubble muted">Pensando…</div>
            </div>
          )}
        </div>
        <div className="chat-input-row">
          <textarea
            className="textarea"
            placeholder="Describe el cambio que quieres aplicar a la receta…"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <Button variant="primary" loading={chat.isPending} disabled={!message.trim()} onClick={send}>
            <IcSend /> Enviar
          </Button>
        </div>
      </div>
    </div>
  );
}

function PatchPreview({ turn, onResolve }: { turn: ChatTurn; onResolve: (action: "applied" | "discarded") => void }) {
  return (
    <div style={{ width: "100%" }}>
      <div className="patch-list">
        {turn.patch!.map((op, i) => (
          <div key={i} className="patch-row">
            <span className={`patch-op ${op.op}`}>{op.op}</span>
            <div className="patch-body">
              <span className="patch-path">{op.path}</span>
              {op.value !== undefined && (
                <span className="patch-value">{previewValue(op.value)}</span>
              )}
              {op.from && <span className="patch-value">desde {op.from}</span>}
            </div>
          </div>
        ))}
      </div>
      {turn.resolved ? (
        <span className={`badge ${turn.resolved === "applied" ? "ok" : "default"}`} style={{ marginTop: 4 }}>
          {turn.resolved === "applied" ? <><IcCheck width={12} height={12} /> Aplicado</> : <><IcX width={12} height={12} /> Descartado</>}
        </span>
      ) : (
        <div className="patch-actions">
          <Button size="sm" variant="primary" onClick={() => onResolve("applied")}><IcCheck /> Aplicar</Button>
          <Button size="sm" variant="ghost" onClick={() => onResolve("discarded")}><IcX /> Descartar</Button>
        </div>
      )}
    </div>
  );
}

function previewValue(value: unknown): string {
  try {
    const s = typeof value === "string" ? value : JSON.stringify(value);
    return s.length > 90 ? `${s.slice(0, 90)}…` : s;
  } catch {
    return String(value);
  }
}

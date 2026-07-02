import { useState, type DragEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  ingestAltUpload, ingestAltYoutube,
  type IngestResponse,
} from "../api/client";
import { Badge, Button, Field, useToast } from "../ui/primitives";
import { IcUpload } from "../ui/icons";

/** Drag-and-drop mp4 + YouTube-URL ingest, shared by the Alternate-Ending tab
 * and the Recreation editor's optional "vídeo base (v2v)" section — both need
 * the exact same upload-or-download-with-rights-ack flow, they just do
 * different things with the resulting `source_id` afterwards. */
export function SourceIngest({ source, onIngested, compact = false }: {
  source: IngestResponse | null;
  onIngested: (r: IngestResponse) => void;
  compact?: boolean;
}) {
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [rightsAck, setRightsAck] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const ingestFile = useMutation({
    mutationFn: (f: File) => ingestAltUpload(f),
    onSuccess: (r) => { onIngested(r); toast.ok("Clip cargado", `${r.duration_s.toFixed(1)}s`); },
    onError: (e) => toast.err("No se pudo cargar", (e as Error).message),
  });
  const ingestYt = useMutation({
    mutationFn: () => ingestAltYoutube(url.trim(), rightsAck),
    onSuccess: (r) => { onIngested(r); toast.ok("Vídeo descargado", `${r.duration_s.toFixed(1)}s`); },
    onError: (e) => toast.err("No se pudo descargar", (e as Error).message),
  });

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault(); setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) ingestFile.mutate(f);
  };

  return (
    <div className="stack" style={{ gap: 12 }}>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        style={{
          border: `2px dashed ${dragOver ? "var(--mint)" : "var(--c-border)"}`,
          borderRadius: 12, padding: compact ? 16 : 24, textAlign: "center",
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

      {source && <Badge tone="ok">Clip listo · {source.duration_s.toFixed(1)}s</Badge>}
    </div>
  );
}

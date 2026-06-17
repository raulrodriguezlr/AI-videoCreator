import { useMemo, useState } from "react";
import { mediaUrl, type MediaAsset } from "../api/client";
import { IcFile, IcFilm, IcImage, IcMusic } from "../ui/icons";
import { Empty } from "../ui/primitives";

const KIND_ICON = {
  video: <IcFilm />, image: <IcImage />, audio: <IcMusic />, subtitle: <IcFile />, data: <IcFile />,
};

type Filter = "all" | "video" | "image" | "audio" | "data";

export function MediaViewer({ media, onDelete }: {
  media: MediaAsset[];
  onDelete?: (asset: MediaAsset) => void;
}) {
  const playable = useMemo(() => media.filter((m) => m.kind !== "data" && m.kind !== "subtitle"), [media]);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<MediaAsset | null>(playable[0] ?? media[0] ?? null);

  if (media.length === 0) {
    return <Empty emoji="🎬" title="Sin media todavía">Cuando renderices el episodio, los clips, audios y frames aparecerán aquí.</Empty>;
  }

  const counts: Record<string, number> = {};
  for (const m of media) counts[m.kind] = (counts[m.kind] ?? 0) + 1;
  const filtered = filter === "all" ? media : media.filter((m) => m.kind === filter);
  const cur = selected && filtered.includes(selected) ? selected : filtered[0] ?? null;

  const filters: { id: Filter; label: string }[] = [
    { id: "all", label: `Todo · ${media.length}` },
    ...(["video", "image", "audio", "data"] as const)
      .filter((k) => counts[k])
      .map((k) => ({ id: k as Filter, label: `${labelFor(k)} · ${counts[k]}` })),
  ];

  return (
    <div>
      <div className="media-tabs">
        {filters.map((f) => (
          <button key={f.id} className={`badge ${filter === f.id ? "accent" : ""}`}
            style={{ cursor: "pointer" }} onClick={() => setFilter(f.id)}>
            {f.label}
          </button>
        ))}
      </div>

      {cur && <Stage asset={cur} />}

      {cur && onDelete && (
        <div className="btn-row" style={{ justifyContent: "flex-end", marginTop: 8 }}>
          <button className="btn ghost sm" title="Eliminar este archivo del almacenamiento"
            onClick={() => {
              if (confirm(`¿Eliminar "${cur.name}"? No se puede deshacer.`)) onDelete(cur);
            }}>
            🗑 Eliminar
          </button>
        </div>
      )}

      <div className="media-strip" style={{ marginTop: 14 }}>
        {filtered.map((m) => (
          <button key={m.url} className={`thumb-btn ${cur?.url === m.url ? "sel" : ""}`}
            onClick={() => setSelected(m)} title={m.name}>
            {m.kind === "image" && <img src={mediaUrl(m.url, m.size_bytes)} alt={m.name} loading="lazy" />}
            {m.kind === "video" && <span className="ic"><IcFilm /></span>}
            {m.kind === "audio" && <span className="ic"><IcMusic /></span>}
            {(m.kind === "data" || m.kind === "subtitle") && <span className="ic"><IcFile /></span>}
            <span className="lbl">{shortName(m.name)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function Stage({ asset }: { asset: MediaAsset }) {
  const url = mediaUrl(asset.url, asset.size_bytes);
  return (
    <div className="stage">
      {asset.kind === "video" && <video src={url} controls preload="metadata" key={url} />}
      {asset.kind === "image" && <img src={url} alt={asset.name} key={url} />}
      {asset.kind === "audio" && (
        <div className="audio-wrap">
          <span style={{ color: "var(--text-3)" }}>{KIND_ICON.audio}</span>
          <div className="mono muted" style={{ fontSize: 12 }}>{asset.name}</div>
          <audio src={url} controls key={url} />
        </div>
      )}
      {(asset.kind === "data" || asset.kind === "subtitle") && (
        <div className="audio-wrap">
          <span style={{ color: "var(--text-3)" }}>{KIND_ICON.data}</span>
          <a className="btn sm" href={url} target="_blank" rel="noreferrer">Abrir {asset.name}</a>
        </div>
      )}
    </div>
  );
}

const labelFor = (k: string) => ({ video: "Vídeos", image: "Imágenes", audio: "Audio", data: "Datos" } as Record<string, string>)[k] ?? k;
const shortName = (n: string) => (n.length > 22 ? "…" + n.slice(-21) : n);

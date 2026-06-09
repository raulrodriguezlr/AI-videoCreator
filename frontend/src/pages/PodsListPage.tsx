import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Pod } from "../api/client";
import { Badge, Button, Empty, ErrorState, Loading, useToast } from "../ui/primitives";
import { IcFilm, IcPlus, IcTrash } from "../ui/icons";

function confirmThen(message: string, fn: () => void): void {
  if (window.confirm(message)) fn();
}

export function PodsListPage() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const pods = useQuery<Pod[]>({ queryKey: ["pods"], queryFn: () => api.get("/pods") });
  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/pods/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["pods"] }); toast.ok("Pod borrado"); },
    onError: (e) => toast.err("No se pudo borrar", (e as Error).message),
  });

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Estudio</div>
          <h1>Tus pods</h1>
          <p className="sub">Cada pod es una serie de vídeos con su estilo, personajes, temas y episodios.</p>
        </div>
        <Button variant="primary" onClick={() => nav("/create")}><IcPlus /> Nuevo pod</Button>
      </div>

      {pods.isLoading && <Loading />}
      {pods.isError && <ErrorState error={pods.error} />}
      {pods.data && pods.data.length === 0 && (
        <Empty emoji="🎬" title="Aún no hay pods"
          action={<Button variant="primary" onClick={() => nav("/create")}><IcPlus /> Crear tu primer pod</Button>}>
          Crea una serie desde una idea y deja que la IA proponga personajes y temas.
        </Empty>
      )}

      {pods.data && pods.data.length > 0 && (
        <div className="grid cols">
          {pods.data.map((pod) => (
            <article key={pod.id} className="tile" onClick={() => nav(`/pods/${pod.id}`)}>
              <button className="tile-del" title="Borrar pod"
                disabled={del.isPending && del.variables === pod.id}
                onClick={(e) => { e.stopPropagation(); confirmThen(`¿Borrar el pod "${pod.config.series_name || pod.name}" y todo su contenido?`, () => del.mutate(pod.id)); }}>
                <IcTrash />
              </button>
              <div className="thumb"><IcFilm /></div>
              <div>
                <h3>{pod.config.series_name || pod.name}</h3>
                <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>
                  {pod.config.target_audience} · {pod.config.language}
                </div>
              </div>
              <div className="tag-list">
                <Badge tone={styleTone(pod.config.style_profile)}>{prettyStyle(pod.config.style_profile)}</Badge>
                <Badge>{pod.config.duration_seconds}s</Badge>
                {pod.config.provider_preferences?.primary && (
                  <Badge>{pod.config.provider_preferences.primary}</Badge>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

export const prettyStyle = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

/** Give each visual style its own accent so the grid reads colourfully. */
type Tone = "accent" | "ok" | "warn" | "err" | "pink" | "violet";
const STYLE_TONE: Record<string, Tone> = {
  cinematic_3d: "accent",
  kids_3d: "pink",
  anime_2d: "violet",
  photoreal_doc: "ok",
  talking_head_avatar: "warn",
  motion_graphics: "err",
  stock_montage: "ok",
};
export const styleTone = (s: string): Tone => STYLE_TONE[s] ?? "accent";

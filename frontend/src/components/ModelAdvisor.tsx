// Cost-aware model picker. Given the chosen provider + content style, asks the
// backend (/system/providers/recommend) which model gives the most videos at
// acceptable quality, preselects it, but lets the user override among ALL their
// subscription models. Shows approximate credit/$ cost, a "recomendado" mark,
// and flags experimental (web-backend) and copyright-risky models.
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  recommendModels, CONTENT_TYPES,
  type ModelRecommendation, type RecommendResponse,
} from "../api/client";
import { Field } from "../ui/primitives";

const CONTENT_LABELS: Record<string, string> = {
  animation_2d: "Animación 2D",
  animation_3d: "Animación 3D",
  talking_head: "Personaje hablando",
  realistic: "Realista",
  cinematic: "Cinematográfico",
  quick_draft: "Borrador rápido",
};

function costText(r: ModelRecommendation): string {
  if (r.unlimited) return "ilimitado";
  if (r.est_credits > 0) return `${r.est_credits}cr · ~${r.est_usd.toFixed(2)}$`;
  return `~${r.est_usd.toFixed(2)}$`;
}

function optionLabel(r: ModelRecommendation): string {
  const bits = [r.model_id, costText(r)];
  if (r.recommended) bits.push("✓ recomendado");
  if (r.experimental) bits.push("⚠ experimental");
  if (!r.copyright_safe) bits.push("⛔ copyright");
  return bits.join(" · ");
}

export function ModelAdvisor({
  provider,
  contentType,
  onContentType,
  model,
  onModel,
  durationS = 5,
  copyrightFlagged = false,
  capability = "text_to_video",
}: {
  provider: string | null;
  contentType: string;
  onContentType: (ct: string) => void;
  model: string | null;
  onModel: (id: string | null, providerId?: string | null) => void;
  durationS?: number;
  copyrightFlagged?: boolean;
  capability?: string;
}) {
  const q = useQuery<RecommendResponse>({
    queryKey: ["recommend", contentType, provider, durationS, copyrightFlagged, capability],
    queryFn: () =>
      recommendModels({
        content_type: contentType,
        provider,
        duration_s: durationS,
        copyright_flagged: copyrightFlagged,
        capability,
      }),
    retry: false,
  });

  const recs = q.data?.recommendations ?? [];
  const recommendedId = recs.find((r) => r.recommended)?.model_id ?? null;

  // Suggest the recommended model when the user hasn't picked one yet.
  useEffect(() => {
    if (!model && recommendedId) {
      const rec = recs.find((r) => r.model_id === recommendedId);
      onModel(recommendedId, rec?.provider_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recommendedId]);

  const selected = recs.find((r) => r.model_id === model);
  const pick = (id: string | null) => {
    const rec = recs.find((r) => r.model_id === id);
    onModel(id, rec?.provider_id ?? null);
  };

  let hint: string | undefined;
  if (q.isLoading) hint = "Calculando recomendación…";
  else if (q.isError) hint = "No se pudieron cargar modelos — se usará automático.";
  else if (recs.length === 0) hint = "Sin modelos para esta capacidad — automático.";
  else if (selected) hint = selected.reason;

  return (
    <>
      <Field label="Estilo de contenido">
        <select
          className="select"
          value={contentType}
          onChange={(e) => onContentType(e.target.value)}
        >
          {CONTENT_TYPES.map((ct) => (
            <option key={ct} value={ct}>{CONTENT_LABELS[ct] ?? ct}</option>
          ))}
        </select>
      </Field>
      <Field label="Modelo" hint={hint}>
        <select
          className="select"
          value={model ?? ""}
          onChange={(e) => pick(e.target.value || null)}
          disabled={recs.length === 0}
        >
          <option value="">Automático (recomendado)</option>
          {recs.map((r) => (
            <option key={r.model_id} value={r.model_id}>{optionLabel(r)}</option>
          ))}
        </select>
      </Field>
      {copyrightFlagged && (
        <div className="dim" style={{ fontSize: 11.5, color: "var(--warn, #c70)" }}>
          ⚠ El guion menciona personas reales/personajes con copyright — se han
          ocultado modelos que los rechazarían (Veo, Sora).
        </div>
      )}
    </>
  );
}

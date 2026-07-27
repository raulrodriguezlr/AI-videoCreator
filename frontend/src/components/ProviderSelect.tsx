// Reusable provider picker — lets the user pin a specific SDK provider for a
// generation, or leave it on "Automático" so the backend's fallback chain
// decides. Filters the /system/providers/sdk catalog by capability.
import { useQuery } from "@tanstack/react-query";
import { getSdkProviders, type SdkProvider } from "../api/client";
import { Field } from "../ui/primitives";

function costLabel(p: SdkProvider): string {
  return p.cost_per_second_usd === 0 ? "$0/seg" : `$${p.cost_per_second_usd}/seg`;
}

export function ProviderSelect({
  value, onChange, capability = "text_to_video", label = "Proveedor",
}: {
  value: string | null;
  onChange: (id: string | null) => void;
  capability?: string;
  label?: string;
}) {
  const providers = useQuery<SdkProvider[]>({
    queryKey: ["sdk-providers"],
    queryFn: getSdkProviders,
    retry: false,
  });

  const options = (providers.data ?? []).filter((p) => p.capabilities.includes(capability));

  let hint: string | undefined;
  if (providers.isLoading) hint = "Cargando proveedores…";
  else if (providers.isError) hint = "No se pudo cargar el catálogo — se usará automático.";
  else if (options.length === 0) hint = "Sin proveedores disponibles para esta capacidad — se usará automático.";

  return (
    <Field label={label} hint={hint}>
      <select
        className="select"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">Automático (recomendado)</option>
        {options.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} — {costLabel(p)}
          </option>
        ))}
      </select>
    </Field>
  );
}

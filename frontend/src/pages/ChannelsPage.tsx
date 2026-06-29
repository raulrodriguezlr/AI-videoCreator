import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listChannels, connectChannel, disconnectChannel, listUploads, getAppConfig,
  type Channel, type ChannelPlatform, type PublishJob, type AppConfig,
} from "../api/client";
import {
  Badge, Button, Empty, ErrorState, Field, Loading, Modal, useToast,
} from "../ui/primitives";
import { IcCloud, IcTrash, IcPlus } from "../ui/icons";

const PLATFORMS: { id: ChannelPlatform; label: string }[] = [
  { id: "youtube", label: "YouTube" },
  { id: "tiktok", label: "TikTok" },
  { id: "instagram", label: "Instagram" },
];

const statusTone = (s: Channel["status"]) =>
  s === "connected" ? "ok" : s === "expired" ? "warn" : "err";

export function ChannelsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [connecting, setConnecting] = useState<ChannelPlatform | null>(null);

  const cfg = useQuery<AppConfig>({ queryKey: ["app-config"], queryFn: getAppConfig });
  const enabled = cfg.data?.channels_feature_enabled ?? false;

  const accounts = useQuery<Channel[]>({
    queryKey: ["channels"], queryFn: listChannels, enabled,
  });
  const uploads = useQuery<PublishJob[]>({
    queryKey: ["channel-uploads"], queryFn: listUploads, refetchInterval: 8_000, enabled,
  });

  const disconnect = useMutation({
    mutationFn: (id: string) => disconnectChannel(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channels"] });
      qc.invalidateQueries({ queryKey: ["channel-uploads"] });
      toast.ok("Cuenta desconectada");
    },
    onError: (e) => toast.err("Error", (e as Error).message),
  });

  if (cfg.data && !enabled) {
    return (
      <div className="page">
        <Empty emoji="🔒" title="Centro de canales desactivado">
          Actívalo en <strong>Ajustes → Funciones experimentales</strong>.
        </Empty>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Sistema</div>
          <h1>Canales</h1>
          <p className="sub">Conecta tus cuentas y publica episodios y shorts desde aquí.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {PLATFORMS.map((p) => (
            <Button key={p.id} variant="ghost" onClick={() => setConnecting(p.id)}>
              <IcPlus /> {p.label}
            </Button>
          ))}
        </div>
      </div>

      {accounts.isLoading && <Loading />}
      {accounts.isError && <ErrorState error={accounts.error} />}
      {accounts.data && accounts.data.length === 0 && (
        <Empty emoji="🔌" title="Sin cuentas conectadas">
          Conecta una cuenta arriba para empezar a publicar.
        </Empty>
      )}
      {accounts.data && accounts.data.length > 0 && (
        <div className="grid cols">
          {accounts.data.map((acc) => (
            <div className="card" key={acc.id}>
              <div className="card-pad" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <IcCloud width={20} height={20} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600 }}>{acc.display_name}</div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {acc.platform}{acc.handle ? ` · ${acc.handle}` : ""}
                  </div>
                </div>
                <Badge tone={statusTone(acc.status)}>{acc.status}</Badge>
                <Button
                  variant="danger" size="sm"
                  loading={disconnect.isPending && disconnect.variables === acc.id}
                  onClick={() => disconnect.mutate(acc.id)}
                >
                  <IcTrash />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div style={{ height: 28 }} />
      <h2 style={{ marginBottom: 12 }}>Historial de subidas</h2>
      {uploads.isLoading && <Loading />}
      {uploads.isError && <ErrorState error={uploads.error} />}
      {uploads.data && uploads.data.length === 0 && (
        <Empty emoji="📤" title="Sin subidas todavía">
          Publica un episodio o short desde su página.
        </Empty>
      )}
      {uploads.data && uploads.data.length > 0 && (
        <div className="card" style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Plataforma", "Origen", "Estado", "Programado", "Resultado"].map((h) => (
                  <th key={h} style={{ textAlign: "left", padding: "8px 12px", borderBottom: "1px solid var(--c-border)" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {uploads.data.map((j) => (
                <tr key={j.id}>
                  <td style={{ padding: "8px 12px" }}>{j.platform}</td>
                  <td style={{ padding: "8px 12px" }}>{j.source} · {j.source_id}</td>
                  <td style={{ padding: "8px 12px" }}><Badge tone={uploadTone(j.status)}>{j.status}</Badge></td>
                  <td className="muted" style={{ padding: "8px 12px" }}>{j.scheduled_at ? new Date(j.scheduled_at).toLocaleString() : "—"}</td>
                  <td style={{ padding: "8px 12px" }}>
                    {j.result_url
                      ? <a href={j.result_url} target="_blank" rel="noreferrer">ver</a>
                      : <span className="muted">{j.error ?? "—"}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {connecting && (
        <ConnectModal platform={connecting} onClose={() => setConnecting(null)} />
      )}
    </div>
  );
}

const uploadTone = (s: PublishJob["status"]) =>
  s === "published" ? "ok" : s === "error" ? "err" : s === "uploading" ? "accent" : "default";

function ConnectModal({ platform, onClose }: { platform: ChannelPlatform; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");

  const connect = useMutation({
    mutationFn: () => connectChannel(platform, clientId.trim(), clientSecret.trim()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channels"] });
      toast.ok("Cuenta conectada");
      onClose();
    },
    onError: (e) => toast.err("No se pudo conectar", (e as Error).message),
  });

  const label = PLATFORMS.find((p) => p.id === platform)?.label ?? platform;
  return (
    <Modal
      title={`Conectar ${label}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            loading={connect.isPending}
            disabled={!clientId.trim() || !clientSecret.trim()}
            onClick={() => connect.mutate()}
          >
            Conectar y abrir navegador
          </Button>
        </>
      }
    >
      <div className="stack">
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>
          Introduce las credenciales de tu app de {label}. Al conectar se abrirá una
          pestaña del navegador para iniciar sesión; la sesión queda guardada cifrada
          en local.
        </p>
        <Field label="Client ID">
          <input className="input" value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="client id" />
        </Field>
        <Field label="Client Secret">
          <input
            className="input" type="password" value={clientSecret}
            onChange={(e) => setClientSecret(e.target.value)} placeholder="client secret"
          />
        </Field>
      </div>
    </Modal>
  );
}

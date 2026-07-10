import { Fragment, useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listChannels, connectChannel, disconnectChannel, verifyChannel, listUploads, getAppConfig,
  accountLabel,
  type Channel, type ChannelPlatform, type PublishJob, type AppConfig,
} from "../api/client";
import {
  Badge, Button, Callout, Empty, ErrorState, Field, Loading, Modal, useToast,
} from "../ui/primitives";
import { IcAlertTriangle, IcCloud, IcTrash, IcPlus, IcCheck, IcRefresh } from "../ui/icons";

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

  const verify = useMutation({
    mutationFn: (id: string) => verifyChannel(id),
    onSuccess: (acc) => {
      qc.invalidateQueries({ queryKey: ["channels"] });
      if (acc.status !== "connected") {
        toast.err("Cuenta caducada", `${acc.display_name} necesita reconectarse`);
      }
    },
    // A failed ping is informational, not fatal — the badge already reflects
    // stored status; don't spam a toast for a transient network hiccup.
    onError: () => qc.invalidateQueries({ queryKey: ["channels"] }),
  });

  // Ping every connected account once on mount — a lightweight health check
  // (channels.list / user info / me) that flips a dead token to EXPIRED
  // before the user tries to publish and hits a confusing upload failure.
  const verifyMutate = verify.mutate;
  useEffect(() => {
    if (!accounts.data) return;
    for (const acc of accounts.data) verifyMutate(acc.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accounts.data?.map((a) => a.id).join(",")]);

  const [reconnectPlatform, setReconnectPlatform] = useState<ChannelPlatform | null>(null);

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
        <Empty emoji="🔌" title="Ningún canal enchufado aún">
          Conecta una cuenta arriba y tendrás dónde publicar en un clic.
        </Empty>
      )}
      {accounts.data && accounts.data.length > 0 && (
        <div className="grid cols">
          {accounts.data.map((acc) => (
            <div className="card" key={acc.id}>
              <div className="card-pad" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <IcCloud width={20} height={20} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600 }}>{accountLabel(acc)}</div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {acc.platform}{acc.handle ? ` · ${acc.handle}` : ` · #${acc.id.slice(-4)}`}
                  </div>
                </div>
                <Badge tone={statusTone(acc.status)}>{acc.status}</Badge>
                {acc.status === "expired" && (
                  <Button variant="ghost" size="sm" onClick={() => setReconnectPlatform(acc.platform)}>
                    <IcRefresh /> Reconectar
                  </Button>
                )}
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
        <Empty emoji="📤" title="Nada publicado por aquí todavía">
          Publica un episodio o short desde su página y su rastro aparecerá aquí.
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
        <ConnectWizard platform={connecting} onClose={() => setConnecting(null)} />
      )}
      {reconnectPlatform && (
        <ConnectWizard platform={reconnectPlatform} onClose={() => setReconnectPlatform(null)} />
      )}
    </div>
  );
}

const uploadTone = (s: PublishJob["status"]) =>
  s === "published" ? "ok" : s === "error" ? "err" : s === "uploading" ? "accent" : "default";

// ============================================================================
// Per-platform connect wizard
// ============================================================================
type WizardStep = { title: string; body: ReactNode };

const YT_CLIENT_ID_SUFFIX = ".apps.googleusercontent.com";
const TT_SECRET_MIN_LEN = 8;

function LinkOut({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>
      {children} ↗
    </a>
  );
}

function youtubeSteps(): WizardStep[] {
  return [
    {
      title: "Crea un proyecto en Google Cloud",
      body: (
        <p style={{ margin: 0 }}>
          Abre <LinkOut href="https://console.cloud.google.com/projectcreate">console.cloud.google.com/projectcreate</LinkOut> y
          crea un proyecto nuevo (o reutiliza uno). Es gratis — no hace falta tarjeta.
        </p>
      ),
    },
    {
      title: "Habilita YouTube Data API v3",
      body: (
        <p style={{ margin: 0 }}>
          Con el proyecto seleccionado, entra en{" "}
          <LinkOut href="https://console.cloud.google.com/apis/library/youtube.googleapis.com">
            la librería de YouTube Data API v3
          </LinkOut>{" "}
          y pulsa <b>Habilitar</b>.
        </p>
      ),
    },
    {
      title: "Configura la pantalla de consentimiento OAuth",
      body: (
        <p style={{ margin: 0 }}>
          En <LinkOut href="https://console.cloud.google.com/apis/credentials/consent">
            APIs y servicios → Pantalla de consentimiento
          </LinkOut>, elige tipo <b>Externo</b> y añade tu propio email en{" "}
          <b>Usuarios de prueba</b> — así puedes autorizar la app sin que Google la revise.
        </p>
      ),
    },
    {
      title: "Crea credenciales de tipo Aplicación de escritorio",
      body: (
        <p style={{ margin: 0 }}>
          En <LinkOut href="https://console.cloud.google.com/apis/credentials">
            APIs y servicios → Credenciales
          </LinkOut>, pulsa <b>Crear credenciales → ID de cliente de OAuth</b> y elige{" "}
          <b>Aplicación de escritorio</b>. Google te mostrará un Client ID y un Client Secret.
        </p>
      ),
    },
    {
      title: "Pega tus credenciales",
      body: (
        <p style={{ margin: 0 }}>
          Copia el <b>Client ID</b> y el <b>Client Secret</b> de esa pantalla y pégalos abajo.
        </p>
      ),
    },
  ];
}

function tiktokSteps(): WizardStep[] {
  return [
    {
      title: "Crea una app en TikTok for Developers",
      body: (
        <p style={{ margin: 0 }}>
          Entra en <LinkOut href="https://developers.tiktok.com/apps">developers.tiktok.com/apps</LinkOut> y
          crea una app nueva. Anota el <b>Client Key</b> y <b>Client Secret</b> que te asigna.
        </p>
      ),
    },
    {
      title: "Añade el producto Content Posting API",
      body: (
        <p style={{ margin: 0 }}>
          En la página de tu app, añade el producto <b>Content Posting API</b> y activa los
          scopes <span className="mono">video.publish</span> y <span className="mono">video.upload</span>.
        </p>
      ),
    },
    {
      title: "Solicita la auditoría (audit) de la app",
      body: (
        <>
          <p style={{ margin: "0 0 10px" }}>
            TikTok exige revisar cada app antes de permitirle publicar en cuentas que no sean
            de prueba. Solicita la auditoría desde el mismo panel.
          </p>
          <Callout tone="warn" icon={<IcAlertTriangle width={18} height={18} />}>
            <b>TikTok debe aprobar tu app antes de poder publicar.</b> Puedes conectar la cuenta
            ya mismo — quedará lista y funcionando en cuanto llegue la aprobación, sin que tengas
            que repetir este asistente.
          </Callout>
        </>
      ),
    },
    {
      title: "Pega tus credenciales",
      body: (
        <p style={{ margin: 0 }}>
          Copia el <b>Client Key</b> y el <b>Client Secret</b> de tu app y pégalos abajo.
        </p>
      ),
    },
  ];
}

function instagramSteps(hasPublicUrl: boolean): WizardStep[] {
  return [
    {
      title: "Crea una app de tipo Business en Meta for Developers",
      body: (
        <p style={{ margin: 0 }}>
          Entra en <LinkOut href="https://developers.facebook.com/apps">developers.facebook.com/apps</LinkOut>,
          crea una app y elige el tipo <b>Business</b>.
        </p>
      ),
    },
    {
      title: "Añade el producto Instagram",
      body: (
        <p style={{ margin: 0 }}>
          En el panel de la app, añade el producto <b>Instagram</b> y vincula tu cuenta de
          Instagram profesional (Business o Creator) a través de una Página de Facebook.
        </p>
      ),
    },
    {
      title: "Solicita el permiso instagram_business_content_publish",
      body: (
        <p style={{ margin: 0 }}>
          En <b>Revisión de la app → Permisos y funciones</b>, solicita{" "}
          <span className="mono">instagram_business_content_publish</span> y{" "}
          <span className="mono">instagram_business_basic</span>. Meta revisa esta solicitud
          antes de permitir publicar fuera del modo de desarrollo.
        </p>
      ),
    },
    {
      title: "URL pública de vídeo (requisito de Graph API)",
      body: hasPublicUrl ? (
        <Callout tone="info" icon={<IcCheck width={18} height={18} />}>
          Ya tienes configurada una <b>URL pública de medios</b> en Ajustes — Instagram podrá
          publicar en cuanto conectes la cuenta.
        </Callout>
      ) : (
        <Callout tone="warn" icon={<IcAlertTriangle width={18} height={18} />}>
          Instagram (Graph API) solo acepta un vídeo publicado en una <b>URL pública</b> — nunca
          un archivo subido directamente. Todavía no tienes ninguna URL pública configurada, así
          que la publicación quedará bloqueada hasta que la definas en{" "}
          <a href="#/settings">Ajustes → URL pública de medios (Instagram)</a>.
        </Callout>
      ),
    },
    {
      title: "Pega tus credenciales",
      body: (
        <p style={{ margin: 0 }}>
          Copia el <b>App ID</b> (Client ID) y el <b>App Secret</b> (Client Secret) de tu app y
          pégalos abajo.
        </p>
      ),
    },
  ];
}

function validateClientId(platform: ChannelPlatform, v: string): string | null {
  if (!v.trim()) return null;
  if (platform === "youtube" && !v.trim().endsWith(YT_CLIENT_ID_SUFFIX)) {
    return `Debe terminar en ${YT_CLIENT_ID_SUFFIX}`;
  }
  return null;
}

function validateClientSecret(platform: ChannelPlatform, v: string): string | null {
  if (!v.trim()) return null;
  if (platform === "youtube" && !v.trim().startsWith("GOCSPX-")) {
    return "Debe empezar por GOCSPX-";
  }
  if (platform === "tiktok" && v.trim().length < TT_SECRET_MIN_LEN) {
    return `Demasiado corto (mín. ${TT_SECRET_MIN_LEN} caracteres)`;
  }
  return null;
}

function ConnectWizard({ platform, onClose }: { platform: ChannelPlatform; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [stepIx, setStepIx] = useState(0);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");

  const cfg = useQuery<AppConfig>({ queryKey: ["app-config"], queryFn: getAppConfig });
  const hasPublicUrl = Boolean(cfg.data?.public_media_base_url);

  const steps =
    platform === "youtube" ? youtubeSteps()
    : platform === "tiktok" ? tiktokSteps()
    : instagramSteps(hasPublicUrl);

  const lastIx = steps.length - 1;
  const onCredentialsStep = stepIx === lastIx;

  const idError = validateClientId(platform, clientId);
  const secretError = validateClientSecret(platform, clientSecret);
  const canSubmit = clientId.trim() && clientSecret.trim() && !idError && !secretError;

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
  const idLabel = platform === "instagram" ? "App ID (Client ID)" : platform === "tiktok" ? "Client Key" : "Client ID";
  const secretLabel = platform === "instagram" ? "App Secret (Client Secret)" : "Client Secret";

  return (
    <Modal
      title={`Conectar ${label}`}
      onClose={onClose}
      wide
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancelar</Button>
          {stepIx > 0 && (
            <Button variant="ghost" onClick={() => setStepIx((i) => Math.max(0, i - 1))}>Atrás</Button>
          )}
          {!onCredentialsStep ? (
            <Button variant="primary" onClick={() => setStepIx((i) => Math.min(lastIx, i + 1))}>
              Siguiente
            </Button>
          ) : (
            <Button
              variant="primary"
              loading={connect.isPending}
              disabled={!canSubmit}
              onClick={() => connect.mutate()}
            >
              Conectar y abrir navegador
            </Button>
          )}
        </>
      }
    >
      <div className="stack">
        <div className="wiz-steps" aria-hidden>
          {steps.map((_, i) => (
            <Fragment key={i}>
              <div className={`wiz-step ${i < stepIx ? "done" : i === stepIx ? "active" : ""}`}>
                {i < stepIx ? <IcCheck width={13} height={13} /> : i + 1}
              </div>
              {i < lastIx && <div className={`wiz-step-line ${i < stepIx ? "done" : ""}`} />}
            </Fragment>
          ))}
        </div>

        <div className="wiz-substep">
          <div style={{ fontWeight: 650, marginBottom: 8 }}>
            <span className="num">{stepIx + 1}</span>
            {steps[stepIx].title}
          </div>
          {steps[stepIx].body}
        </div>

        {onCredentialsStep && (
          <>
            <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
              Estas credenciales son tuyas — quedan guardadas cifradas en local, nunca salen de
              esta máquina. Como la app corre sin servidor propio, el flujo de conexión abre una
              pestaña del navegador para que inicies sesión directamente con la plataforma.
            </p>
            <Field label={idLabel} hint={idError ?? undefined}>
              <input
                className="input" value={clientId} onChange={(e) => setClientId(e.target.value)}
                placeholder={platform === "youtube" ? "123-abc.apps.googleusercontent.com" : idLabel}
                style={idError ? { borderColor: "var(--red)" } : undefined}
              />
              {clientId.trim() && !idError && <span className="field-ok" style={{ fontSize: 12 }}>✓ formato correcto</span>}
            </Field>
            <Field label={secretLabel} hint={secretError ?? undefined}>
              <input
                className="input" type="password" value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                placeholder={platform === "youtube" ? "GOCSPX-…" : secretLabel}
                style={secretError ? { borderColor: "var(--red)" } : undefined}
              />
              {clientSecret.trim() && !secretError && <span className="field-ok" style={{ fontSize: 12 }}>✓ formato correcto</span>}
            </Field>
          </>
        )}
      </div>
    </Modal>
  );
}

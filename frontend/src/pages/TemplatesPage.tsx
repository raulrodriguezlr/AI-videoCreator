import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getTemplates, type Template } from "../api/client";
import { Badge, Button, Empty, ErrorState, Loading } from "../ui/primitives";
import { IcLayout, IcWand } from "../ui/icons";
import { DagPipeline } from "../components/DagPipeline";

export function TemplatesPage() {
  const nav = useNavigate();
  const templates = useQuery<Template[]>({ queryKey: ["templates"], queryFn: getTemplates });

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Estudio</div>
          <h1>Plantillas</h1>
          <p className="sub">Recetas listas para producir un short — ábrelas en el director y ajústalas por chat.</p>
        </div>
      </div>

      {templates.isLoading && <Loading />}
      {templates.isError && <ErrorState error={templates.error} />}
      {templates.data && templates.data.length === 0 && (
        <Empty emoji="🧩" title="Las plantillas están al llegar">
          Aún no hay recetas publicadas — pide al Director que diseñe la primera.
        </Empty>
      )}

      {templates.data && templates.data.length > 0 && (
        <div className="grid cols">
          {templates.data.map((tpl) => (
            <article key={tpl.id} className="card card-pad template-card">
              <div>
                <div className="between">
                  <h3>{tpl.name}</h3>
                  <Badge tone="accent"><IcLayout width={13} height={13} /> {tpl.dag.nodes.length} nodos</Badge>
                </div>
                {tpl.description && (
                  <p className="muted" style={{ fontSize: 13, marginTop: 6 }}>{tpl.description}</p>
                )}
              </div>

              {tpl.tags.length > 0 && (
                <div className="tag-list">
                  {tpl.tags.map((tag) => <Badge key={tag}>{tag}</Badge>)}
                </div>
              )}

              <DagPipeline nodes={tpl.dag.nodes} compact />

              <div className="template-card-foot">
                <span className="dim mono" style={{ fontSize: 11 }}>{tpl.id}</span>
                <Button variant="primary" size="sm"
                  onClick={() => nav("/director", { state: { spec: tpl.dag, templateName: tpl.name } })}>
                  <IcWand /> Abrir en Director
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

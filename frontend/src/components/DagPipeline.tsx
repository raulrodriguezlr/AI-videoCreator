// Mini horizontal DAG visualization — pure flex/CSS, no graph library.
// Renders nodes in topological order (by dependency depth), grouped into
// columns so parallel branches stack vertically within the same step.
import type { DagNodeDto } from "../api/client";
import { IcArrowRight } from "../ui/icons";

/** Group nodes into ordered columns based on dependency depth (topological levels). */
function topoColumns(nodes: DagNodeDto[]): DagNodeDto[][] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const depth = new Map<string, number>();

  const resolve = (id: string, trail: Set<string>): number => {
    if (depth.has(id)) return depth.get(id)!;
    const node = byId.get(id);
    if (!node || trail.has(id)) return 0; // missing dep / cycle guard
    trail.add(id);
    const deps = node.depends_on.filter((d) => byId.has(d));
    const d = deps.length === 0 ? 0 : 1 + Math.max(...deps.map((dep) => resolve(dep, trail)));
    depth.set(id, d);
    return d;
  };

  for (const n of nodes) resolve(n.id, new Set());

  const maxDepth = Math.max(0, ...nodes.map((n) => depth.get(n.id) ?? 0));
  const cols: DagNodeDto[][] = Array.from({ length: maxDepth + 1 }, () => []);
  for (const n of nodes) cols[depth.get(n.id) ?? 0].push(n);
  return cols;
}

export function DagPipeline({ nodes, compact }: { nodes: DagNodeDto[]; compact?: boolean }) {
  if (nodes.length === 0) return <span className="dim" style={{ fontSize: 12.5 }}>Sin nodos</span>;
  const cols = topoColumns(nodes);

  return (
    <div className={`dag-pipeline ${compact ? "compact" : ""}`}>
      {cols.map((col, i) => (
        <div className="dag-pipeline-step" key={i}>
          <div className="dag-pipeline-col">
            {col.map((n) => (
              <span key={n.id} className="dag-chip" title={`${n.id} · ${n.capability}`}>
                <span className="dag-chip-cap">{n.capability}</span>
                <span className="dag-chip-id">{n.id}</span>
              </span>
            ))}
          </div>
          {i < cols.length - 1 && <IcArrowRight className="dag-pipeline-arrow" />}
        </div>
      ))}
    </div>
  );
}

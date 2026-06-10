import { useLocation } from "react-router-dom";
import { type DagSpecDto } from "../api/client";
import { DirectorChat } from "../components/DirectorChat";

const DEFAULT_SPEC: DagSpecDto = {
  nodes: [{ id: "structure", capability: "native_short", params: {}, depends_on: [], max_retries: 0 }],
};

interface DirectorLocationState {
  spec?: DagSpecDto;
  templateName?: string;
}

export function DirectorPage() {
  const location = useLocation();
  const state = (location.state ?? null) as DirectorLocationState | null;
  const initialSpec = state?.spec ?? DEFAULT_SPEC;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Estudio</div>
          <h1>Director</h1>
          <p className="sub">
            {state?.templateName
              ? `Editando la receta "${state.templateName}" — pídele cambios al director.`
              : "Diseña la receta de tu short conversando con el director."}
          </p>
        </div>
      </div>
      <DirectorChat key={JSON.stringify(initialSpec)} initialSpec={initialSpec} />
    </div>
  );
}

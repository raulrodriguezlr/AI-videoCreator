import { useLocation } from "react-router-dom";
import { type DagSpecDto } from "../api/client";
import { DirectorChat } from "../components/DirectorChat";

// A runnable starter pipeline (only implemented capabilities), so "Generar"
// produces a real composed short out of the box instead of a dead-end node.
const DEFAULT_SPEC: DagSpecDto = {
  nodes: [
    { id: "structure", capability: "native_short", params: {}, depends_on: [], max_retries: 0 },
    { id: "voice", capability: "tts", params: { language: "es" }, depends_on: ["structure"], max_retries: 1 },
    { id: "clips", capability: "text_to_video", params: { width: 1080, height: 1920 }, depends_on: ["structure"], max_retries: 1 },
    { id: "render", capability: "compose_short", params: {}, depends_on: ["voice", "clips"], max_retries: 0 },
  ],
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

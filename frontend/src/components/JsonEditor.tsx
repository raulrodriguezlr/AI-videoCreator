import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type FileContent } from "../api/client";
import { Button, ErrorState, Loading, useToast } from "../ui/primitives";

/**
 * Raw JSON viewer/editor for a single file. Loads `getPath`, edits in a
 * textarea with client-side JSON validation, and PUTs to `putPath`.
 */
export function JsonEditor({ getPath, putPath, queryKey }: {
  getPath: string; putPath: string; queryKey: unknown[];
}) {
  const toast = useToast();
  const q = useQuery<FileContent>({ queryKey, queryFn: () => api.get(getPath) });
  const [text, setText] = useState<string>("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (q.data && !dirty) setText(q.data.content);
  }, [q.data, dirty]);

  const valid = (() => {
    try { JSON.parse(text); return true; } catch { return false; }
  })();

  const save = useMutation({
    mutationFn: () => api.put<FileContent>(putPath, { content: text }),
    onSuccess: (d) => { setText(d.content); setDirty(false); toast.ok("Guardado", d.name); },
    onError: (e) => toast.err("No se pudo guardar", (e as Error).message),
  });

  const format = () => {
    try { setText(JSON.stringify(JSON.parse(text), null, 2)); setDirty(true); }
    catch { toast.err("JSON inválido", "Corrige los errores antes de formatear"); }
  };

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState error={q.error} />;

  return (
    <div className="stack">
      <textarea
        className="input mono json-editor"
        spellCheck={false}
        value={text}
        onChange={(e) => { setText(e.target.value); setDirty(true); }}
      />
      <div className="between">
        <span className={`json-status ${valid ? "ok" : "bad"}`}>
          {valid ? "JSON válido" : "JSON inválido"}
        </span>
        <div className="btn-row">
          <Button variant="ghost" size="sm" onClick={format} disabled={!valid}>Formatear</Button>
          <Button variant="ghost" size="sm" disabled={!dirty}
            onClick={() => { setText(q.data?.content ?? ""); setDirty(false); }}>Revertir</Button>
          <Button variant="primary" size="sm" loading={save.isPending} disabled={!valid || !dirty}
            onClick={() => save.mutate()}>Guardar</Button>
        </div>
      </div>
    </div>
  );
}

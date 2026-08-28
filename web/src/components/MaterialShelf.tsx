import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AttachResearcherMaterialRequest } from "../api/types";
import { ErrorState } from "./Feedback";
import { Panel } from "./Panel";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function mediaTypeForFile(name: string): string {
  return /\.(md|markdown|tex)$/i.test(name) ? "text/markdown" : "text/plain";
}

/**
 * ADR-019 project shelf: informal researcher material attached once at
 * project level. Copy items are content-addressed into the artifact store;
 * link items keep large material external and seal only the URL.
 */
export function MaterialShelf({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const materialsQuery = useQuery({
    queryKey: ["materials", projectId],
    queryFn: () => api.listMaterials(projectId),
  });
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"copy" | "link">("copy");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [mediaType, setMediaType] = useState("text/markdown");
  const [link, setLink] = useState("");

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["materials", projectId] });

  const attach = useMutation({
    mutationFn: (input: AttachResearcherMaterialRequest) =>
      api.attachMaterial(projectId, input),
    onSuccess: async () => {
      setName("");
      setText("");
      setFileName(null);
      setMediaType("text/markdown");
      setLink("");
      await invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: (materialId: string) => api.deleteMaterial(projectId, materialId),
    onSuccess: invalidate,
  });

  const linkTrimmed = link.trim();
  const linkInvalid =
    kind === "link" && linkTrimmed.length > 0 && !/^https?:\/\/\S+$/.test(linkTrimmed);
  const canAttach =
    name.trim().length > 0 &&
    !attach.isPending &&
    (kind === "copy" ? text.trim().length > 0 : linkTrimmed.length > 0 && !linkInvalid);

  const submit = () => {
    if (!canAttach) return;
    attach.mutate(
      kind === "copy"
        ? { name: name.trim(), kind: "copy", media_type: mediaType, content: text }
        : { name: name.trim(), kind: "link", external_url: linkTrimmed },
    );
  };

  const materials = materialsQuery.data ?? [];

  return (
    <Panel
      eyebrow="Researcher shelf"
      title="Supplementary material"
      description="Material you bring to the project. Copied items are stored in the project artifact store; links keep large material external. Select an item when launching a run to seal it into that run."
    >
      {materialsQuery.error ? (
        <ErrorState error={materialsQuery.error} title="Materials are unavailable" />
      ) : null}
      {materials.length > 0 ? (
        <ul className="material-shelf__list">
          {materials.map((item) => (
            <li key={item.material_id} className="material-shelf__item">
              <span className="material-shelf__name">
                <strong>{item.name}</strong>
                <em className="material-shelf__kind">{item.kind === "copy" ? "copied in" : "external link"}</em>
              </span>
              <span className="material-shelf__meta">
                {item.kind === "copy"
                  ? `${formatSize(item.size_bytes)} · ${item.media_type}`
                  : item.external_url}
                {" · "}{item.created_at.slice(0, 10)}
              </span>
              <button
                type="button"
                className="button button--quiet"
                disabled={remove.isPending}
                onClick={() => remove.mutate(item.material_id)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="field-help">
          Nothing attached yet. Attach your own paper, partial code, notes, or a link
          to large data; runs can then seal this material as researcher-supplied context.
        </p>
      )}

      <div className="material-shelf__attach">
        <div className="choice-cards">
          {([
            { value: "copy", label: "Copy into the project record", description: "Paste text or attach a small file (up to 1 MB)." },
            { value: "link", label: "External link", description: "Reference large data or material by URL." },
          ] as const).map((option) => (
            <label key={option.value} data-selected={kind === option.value || undefined}>
              <input
                type="radio"
                name="material-kind"
                value={option.value}
                checked={kind === option.value}
                onChange={() => setKind(option.value)}
              />
              <span><strong>{option.label}</strong><small>{option.description}</small></span>
            </label>
          ))}
        </div>
        <label className="field">
          <span>Name</span>
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. partial-fit.py, my-2024-paper.pdf notes"
          />
        </label>
        {kind === "copy" ? (
          <label className="field field--prominent">
            <span>Content</span>
            <textarea
              value={text}
              onChange={(event) => {
                setText(event.target.value);
                setFileName(null);
                setMediaType("text/markdown");
              }}
              rows={4}
              placeholder="Paste the material here - partial code, notes, a derivation."
            />
            <input
              type="file"
              accept=".md,.markdown,.txt,.r,.py,.json,.csv,.tex,.ts,.js"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = () => {
                  setText(String(reader.result ?? ""));
                  setFileName(file.name);
                  setMediaType(mediaTypeForFile(file.name));
                  if (!name.trim()) setName(file.name);
                };
                reader.readAsText(file);
              }}
            />
            <small>
              {fileName
                ? `Attached ${fileName} (${formatSize(new Blob([text]).size)}, ${mediaType}).`
                : "Pasted content is stored as text/markdown by default."}
            </small>
          </label>
        ) : (
          <label className="field field--prominent">
            <span>External material URL</span>
            <input
              type="url"
              value={link}
              onChange={(event) => setLink(event.target.value)}
              placeholder="https://..."
            />
            <small>
              {linkInvalid
                ? "This does not look like a valid http(s) URL."
                : "Only the link is kept. Anything the team derives from it is generated inside the project workspace."}
            </small>
          </label>
        )}
        <div className="launch-row">
          <button
            type="button"
            className="button button--primary"
            disabled={!canAttach}
            onClick={submit}
          >
            {attach.isPending ? "Attaching..." : "Attach to the project"}
          </button>
        </div>
        {attach.error ? (
          <ErrorState error={attach.error} title="The material was not attached" />
        ) : null}
      </div>
    </Panel>
  );
}

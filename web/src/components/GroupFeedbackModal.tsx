import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ContextOption } from "../api/types";

interface GroupFeedbackModalProps {
  group: { key: string; options: ContextOption[] };
  label: string;
  projectId: string;
  selectedIds: ReadonlySet<string>;
  onToggle: (optionId: string, checked: boolean) => void;
  onClose: () => void;
}

export function GroupFeedbackModal({
  group,
  label,
  projectId,
  selectedIds,
  onToggle,
  onClose,
}: GroupFeedbackModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content context-feedback-modal"
        ref={dialogRef}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h3>{label}</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="modal-body">
          {group.options.map((option) => (
            <RecordSection
              key={option.option_id}
              option={option}
              projectId={projectId}
              selected={selectedIds.has(option.option_id)}
              onToggle={onToggle}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function RecordSection({
  option,
  projectId,
  selected,
  onToggle,
}: {
  option: ContextOption;
  projectId: string;
  selected: boolean;
  onToggle: (optionId: string, checked: boolean) => void;
}) {
  const [highlight, setHighlight] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const artifactId = option.highlight_artifact_id;

  useEffect(() => {
    if (!artifactId) return;
    setLoading(true);
    api
      .getArtifactContent(projectId, artifactId)
      .then(setHighlight)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [artifactId, projectId]);

  const structuredArtifactId = option.artifact_pointer?.artifact_id;
  const structuredHref = structuredArtifactId
    ? `/api/v1/projects/${projectId}/artifacts/${structuredArtifactId}`
    : null;

  // Only show a sub-header when there are multiple records in the group
  return (
    <section className="context-feedback__section">
      <label className="context-feedback__select">
        <input
          type="checkbox"
          checked={selected}
          disabled={option.required || option.disabled}
          onChange={(e) => onToggle(option.option_id, e.target.checked)}
        />
        <span>
          Include in run context
          {option.required ? " (required)" : ""}
        </span>
      </label>
      {option.feedback ? (
        <>
          <p className="context-feedback__text">{option.feedback}</p>
        </>
      ) : null}
      {highlight != null || loading || error ? (
        <>
          {loading ? (
            <p className="context-feedback__text context-feedback__loading">Loading…</p>
          ) : error ? (
            <p className="context-feedback__text context-feedback__error">
              Could not load: {error}
            </p>
          ) : (
            <pre className="context-feedback__highlight">{highlight}</pre>
          )}
        </>
      ) : null}
      {structuredHref ? (
        <a
          href={structuredHref}
          target="_blank"
          rel="noopener noreferrer"
          className="context-feedback__doc-link"
        >
          Open full record →
        </a>
      ) : null}
    </section>
  );
}

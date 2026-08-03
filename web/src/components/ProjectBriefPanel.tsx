import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type {
  ActionDescriptor,
  ProjectBriefView,
  ProjectOverview,
  UpdateProjectBriefRequest,
} from "../api/types";
import { formatDate } from "../utils/format";
import { ErrorState } from "./Feedback";
import { Panel } from "./Panel";

export interface BriefDraft {
  researchQuestion: string;
  domains: string;
  intendedUse: string;
  scope: string;
  decisionCriteria: string;
  constraints: string;
  reason: string;
}

interface BriefDraftSource {
  generation_id: string;
  artifact_id: string;
}

export interface BriefDraftEnvelope {
  schema_version: 1;
  source: BriefDraftSource;
  saved_at: string;
  draft: BriefDraft;
}

export type BriefScientificChanges = Partial<
  Omit<UpdateProjectBriefRequest, "action_descriptor_id" | "reason">
>;

export type StoredBriefDraftResolution =
  | { kind: "none" }
  | { kind: "invalid" }
  | { kind: "current"; envelope: BriefDraftEnvelope }
  | { kind: "stale"; envelope: BriefDraftEnvelope };

const draftFields: Array<keyof BriefDraft> = [
  "researchQuestion",
  "domains",
  "intendedUse",
  "scope",
  "decisionCriteria",
  "constraints",
  "reason",
];

export function draftFromBrief(brief: ProjectBriefView): BriefDraft {
  return {
    researchQuestion: brief.research_question,
    domains: brief.domains.join(", "),
    intendedUse: brief.intended_use,
    scope: brief.scope ?? "",
    decisionCriteria: brief.decision_criteria.join("\n"),
    constraints: brief.constraints.join("\n"),
    reason: "",
  };
}

function lines(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function domains(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function arraysEqual(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function briefSource(brief: ProjectBriefView): BriefDraftSource {
  return {
    generation_id: brief.generation_id,
    artifact_id: brief.artifact.artifact_id,
  };
}

function sourcesEqual(left: BriefDraftSource, right: BriefDraftSource): boolean {
  return left.generation_id === right.generation_id && left.artifact_id === right.artifact_id;
}

function validEnvelope(value: unknown): value is BriefDraftEnvelope {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<BriefDraftEnvelope>;
  if (candidate.schema_version !== 1 || typeof candidate.saved_at !== "string") return false;
  if (!candidate.source || typeof candidate.source !== "object") return false;
  if (
    typeof candidate.source.generation_id !== "string"
    || typeof candidate.source.artifact_id !== "string"
  ) return false;
  if (!candidate.draft || typeof candidate.draft !== "object") return false;
  return draftFields.every((field) => typeof candidate.draft?.[field] === "string");
}

export function createBriefDraftEnvelope(
  brief: ProjectBriefView,
  draft: BriefDraft,
  savedAt = new Date().toISOString(),
): BriefDraftEnvelope {
  return {
    schema_version: 1,
    source: briefSource(brief),
    saved_at: savedAt,
    draft,
  };
}

export function resolveStoredBriefDraft(
  raw: string | null,
  brief: ProjectBriefView,
): StoredBriefDraftResolution {
  if (!raw) return { kind: "none" };
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!validEnvelope(parsed)) return { kind: "invalid" };
    return sourcesEqual(parsed.source, briefSource(brief))
      ? { kind: "current", envelope: parsed }
      : { kind: "stale", envelope: parsed };
  } catch {
    return { kind: "invalid" };
  }
}

export function preserveBriefDraftOnClose(sourceChanged: boolean): boolean {
  return sourceChanged;
}

export function getBriefScientificChanges(
  brief: ProjectBriefView,
  draft: BriefDraft,
): BriefScientificChanges {
  const changes: BriefScientificChanges = {};
  const researchQuestion = draft.researchQuestion.trim();
  const nextDomains = domains(draft.domains);
  const intendedUse = draft.intendedUse.trim();
  const scope = draft.scope.trim();
  const decisionCriteria = lines(draft.decisionCriteria);
  const constraints = lines(draft.constraints);

  if (researchQuestion !== brief.research_question.trim()) changes.research_question = researchQuestion;
  if (!arraysEqual(nextDomains, brief.domains)) changes.domains = nextDomains;
  if (intendedUse !== brief.intended_use.trim()) changes.intended_use = intendedUse;
  if (scope !== (brief.scope ?? "").trim()) changes.scope = scope;
  if (!arraysEqual(decisionCriteria, brief.decision_criteria)) changes.decision_criteria = decisionCriteria;
  if (!arraysEqual(constraints, brief.constraints)) changes.constraints = constraints;
  return changes;
}

export function briefSaveDisabledReason({
  brief,
  draft,
  action,
  sourceChanged,
  pending,
}: {
  brief: ProjectBriefView;
  draft: BriefDraft;
  action: ActionDescriptor | undefined;
  sourceChanged: boolean;
  pending: boolean;
}): string | undefined {
  if (sourceChanged) return "The formal brief changed while you were editing. Close the editor, then reopen it to choose whether to restore or discard the browser-only draft.";
  if (!action?.enabled) return action?.researcher_message ?? "No project brief update command is available.";
  if (!draft.researchQuestion.trim()) return "A research question is required.";
  if (domains(draft.domains).length === 0) return "At least one research domain is required.";
  if (!draft.intendedUse.trim()) return "The intended scientific use is required.";
  if (Object.keys(getBriefScientificChanges(brief, draft)).length === 0) return "Change at least one scientific field before saving.";
  if (!draft.reason.trim()) return "Explain why the formal brief should change.";
  if (pending) return "The formal brief update is being submitted.";
  return undefined;
}

function draftStorageKey(projectId: string): string {
  return `method-hub-project-brief-draft:${projectId}`;
}

export async function invalidateProjectBriefDependents(
  queryClient: QueryClient,
  projectId: string,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["projects"] }),
    queryClient.invalidateQueries({ queryKey: ["overview", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["phase", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["methods", projectId] }),
  ]);
}

export function ProjectBriefPanel({ projectId, brief }: { projectId: string; brief: ProjectBriefView }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<BriefDraft>(() => draftFromBrief(brief));
  const [draftBasis, setDraftBasis] = useState<BriefDraftSource>(() => briefSource(brief));
  const [recovery, setRecovery] = useState<BriefDraftEnvelope | null>(null);
  const [restored, setRestored] = useState(false);
  const updateAction = brief.actions.find((action) => action.action_type === "update_project_brief");
  const scientificChanges = getBriefScientificChanges(brief, draft);
  const sourceChanged = editing && !sourcesEqual(draftBasis, briefSource(brief));
  const dirty = editing && Object.keys(scientificChanges).length > 0;

  useEffect(() => {
    if (!editing && !recovery) {
      setDraft(draftFromBrief(brief));
      setDraftBasis(briefSource(brief));
    }
  }, [brief, editing, recovery]);

  useEffect(() => {
    if (!editing) return;
    try {
      const envelope: BriefDraftEnvelope = {
        schema_version: 1,
        source: draftBasis,
        saved_at: new Date().toISOString(),
        draft,
      };
      window.localStorage.setItem(draftStorageKey(projectId), JSON.stringify(envelope));
    } catch {
      // Browser storage is optional. The beforeunload guard still protects this session.
    }
  }, [draft, draftBasis, editing, projectId]);

  useEffect(() => {
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [dirty]);

  const startCurrentEdit = () => {
    setDraft(draftFromBrief(brief));
    setDraftBasis(briefSource(brief));
    setRestored(false);
    setRecovery(null);
    setEditing(true);
  };

  const beginEditing = () => {
    let raw: string | null = null;
    try {
      raw = window.localStorage.getItem(draftStorageKey(projectId));
    } catch {
      startCurrentEdit();
      return;
    }
    const resolution = resolveStoredBriefDraft(raw, brief);
    if (resolution.kind === "stale") {
      setRecovery(resolution.envelope);
      return;
    }
    if (resolution.kind === "current") {
      setDraft(resolution.envelope.draft);
      setDraftBasis(briefSource(brief));
      setRestored(true);
      setEditing(true);
      return;
    }
    if (resolution.kind === "invalid") {
      window.localStorage.removeItem(draftStorageKey(projectId));
    }
    startCurrentEdit();
  };

  const restoreStaleDraft = () => {
    if (!recovery) return;
    setDraft(recovery.draft);
    setDraftBasis(briefSource(brief));
    setRestored(true);
    setRecovery(null);
    setEditing(true);
  };

  const discardStaleDraft = () => {
    window.localStorage.removeItem(draftStorageKey(projectId));
    startCurrentEdit();
  };

  const mutation = useMutation({
    mutationFn: () => {
      if (!updateAction) throw new Error("No project brief update command is available.");
      return api.updateProjectBrief(projectId, {
        action_descriptor_id: updateAction.descriptor_id,
        reason: draft.reason.trim(),
        ...scientificChanges,
      });
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData<ProjectOverview>(["overview", projectId], (current) => current ? {
        ...current,
        project: {
          ...current.project,
          research_question: updated.research_question,
          domains: updated.domains,
        },
        project_brief: updated,
      } : current);
      window.localStorage.removeItem(draftStorageKey(projectId));
      await invalidateProjectBriefDependents(queryClient, projectId);
      setEditing(false);
      setRestored(false);
    },
  });

  const update = (field: keyof BriefDraft, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }));
  };

  const cancel = () => {
    if (!preserveBriefDraftOnClose(sourceChanged)) {
      window.localStorage.removeItem(draftStorageKey(projectId));
    }
    setDraft(draftFromBrief(brief));
    setDraftBasis(briefSource(brief));
    setEditing(false);
    setRecovery(null);
    setRestored(false);
    mutation.reset();
  };

  const saveDisabledReason = briefSaveDisabledReason({
    brief,
    draft,
    action: updateAction,
    sourceChanged,
    pending: mutation.isPending,
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saveDisabledReason) return;
    mutation.mutate();
  };

  const editReasonId = "project-brief-edit-disabled-reason";
  const saveReasonId = "project-brief-save-disabled-reason";

  return (
    <Panel
      eyebrow="Shared scientific context"
      title="Project brief"
      description={brief.scope_note}
      actions={editing || recovery ? undefined : (
        <button
          type="button"
          className="button button--quiet button--small"
          disabled={!updateAction?.enabled}
          aria-describedby={!updateAction?.enabled ? editReasonId : undefined}
          onClick={beginEditing}
        >
          Edit brief
        </button>
      )}
    >
      {!editing && !recovery && !updateAction?.enabled ? (
        <p id={editReasonId} className="disabled-reason" role="status">
          {updateAction?.researcher_message ?? "No project brief update command is available."}
        </p>
      ) : null}

      {recovery ? (
        <div className="message message--warning project-brief-recovery" role="status">
          <div>
            <strong>A saved draft was based on an earlier formal brief.</strong>
            <p>
              Saved {formatDate(recovery.saved_at)} from generation <code>{recovery.source.generation_id}</code>.
              The current generation is <code>{brief.generation_id}</code>. Review this choice explicitly before editing.
            </p>
            <div className="form-actions">
              <button type="button" className="button button--quiet" onClick={discardStaleDraft}>Discard draft and use current brief</button>
              <button type="button" className="button button--primary" onClick={restoreStaleDraft}>Restore previous draft intentionally</button>
            </div>
          </div>
        </div>
      ) : editing ? (
        <form className="form-stack" onSubmit={submit}>
          <label className="field">
            <span>Research question</span>
            <textarea value={draft.researchQuestion} onChange={(event) => update("researchQuestion", event.target.value)} rows={5} required />
          </label>
          <label className="field">
            <span>Research domains</span>
            <input value={draft.domains} onChange={(event) => update("domains", event.target.value)} required />
            <small>Separate domains with commas.</small>
          </label>
          <label className="field">
            <span>Intended scientific use</span>
            <textarea value={draft.intendedUse} onChange={(event) => update("intendedUse", event.target.value)} rows={3} required />
          </label>
          <label className="field">
            <span>Scope</span>
            <textarea value={draft.scope} onChange={(event) => update("scope", event.target.value)} rows={3} />
          </label>
          <label className="field">
            <span>Decision criteria</span>
            <textarea value={draft.decisionCriteria} onChange={(event) => update("decisionCriteria", event.target.value)} rows={4} />
            <small>Enter one criterion per line.</small>
          </label>
          <label className="field">
            <span>Scientific constraints</span>
            <textarea value={draft.constraints} onChange={(event) => update("constraints", event.target.value)} rows={4} />
            <small>Enter one constraint per line.</small>
          </label>
          <label className="field field--prominent">
            <span>Reason for changing the formal brief</span>
            <textarea value={draft.reason} onChange={(event) => update("reason", event.target.value)} rows={2} required />
            <small>This reason is retained with the controlled update.</small>
          </label>
          <p className="muted-text" role="status">
            {restored
              ? "A saved draft was restored intentionally. It remains a browser-only draft until you save it as the formal brief."
              : dirty
                ? "This in-progress brief is saved in this browser."
                : "No unsaved scientific change."}
          </p>
          {saveDisabledReason ? <p id={saveReasonId} className="disabled-reason" role="status">{saveDisabledReason}</p> : null}
          <div className="form-actions">
            <button type="button" className="button button--quiet" onClick={cancel} disabled={mutation.isPending}>
              {sourceChanged ? "Close and resolve draft" : "Cancel"}
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={Boolean(saveDisabledReason)}
              aria-describedby={saveDisabledReason ? saveReasonId : undefined}
            >
              {mutation.isPending ? "Saving brief..." : "Save formal brief"}
            </button>
          </div>
          {mutation.error ? <ErrorState error={mutation.error} title="The project brief was not updated" /> : null}
        </form>
      ) : (
        <div className="project-brief-view">
          <div>
            <h3>Research question</h3>
            <p>{brief.research_question}</p>
          </div>
          <div>
            <h3>Intended scientific use</h3>
            <p>{brief.intended_use}</p>
          </div>
          {brief.scope ? <div><h3>Scope</h3><p>{brief.scope}</p></div> : null}
          <div className="project-brief-columns">
            <div>
              <h3>Decision criteria</h3>
              {brief.decision_criteria.length ? (
                <ul>{brief.decision_criteria.map((criterion, index) => <li key={`${criterion}-${index}`}>{criterion}</li>)}</ul>
              ) : <p className="muted-text">No decision criterion is recorded.</p>}
            </div>
            <div>
              <h3>Scientific constraints</h3>
              {brief.constraints.length ? (
                <ul>{brief.constraints.map((constraint, index) => <li key={`${constraint}-${index}`}>{constraint}</li>)}</ul>
              ) : <p className="muted-text">No additional constraint is recorded.</p>}
            </div>
          </div>
          <div className="tag-list" aria-label="Research domains">
            {brief.domains.map((domain, index) => <span key={`${domain}-${index}`}>{domain}</span>)}
          </div>
          <p className="record-note">
            Formal brief published {formatDate(brief.published_at)}. <a href={brief.artifact.href}>Open brief artifact</a>
          </p>
        </div>
      )}
    </Panel>
  );
}

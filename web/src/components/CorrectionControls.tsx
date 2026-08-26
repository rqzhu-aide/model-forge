import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type {
  ActionDescriptor,
  CorrectionPreview,
  CorrectionType,
  RunDetail,
} from "../api/types";
import { ConfirmActionDialog } from "./ConfirmActionDialog";
import { ErrorState, LoadingState } from "./Feedback";
import { Panel } from "./Panel";
import { StatusPill } from "./Status";

// The descriptor action types the backend emits for each correction lane
// (run_views.py emits all four together under the correction surface
// condition; applicability is enforced server-side at command time).
export const CORRECTION_ACTION_TYPES: Record<CorrectionType, ActionDescriptor["action_type"]> = {
  revalidate: "revalidate_run",
  normalize: "normalize_run_outputs",
  packaging: "package_run_outputs",
  scientific: "revise_scientific_content",
};

export const CORRECTION_LABELS: Record<CorrectionType, string> = {
  revalidate: "Re-check sealed outputs",
  normalize: "Apply normalization",
  packaging: "Request packaging correction",
  scientific: "Request scientific revision",
};

const CONFIRM_TITLES: Record<CorrectionType, string> = {
  revalidate: "Re-check the sealed outputs against the current schemas?",
  normalize: "Apply the allowlisted mechanical transformations?",
  packaging: "Re-invoke the role to fix envelope and format issues?",
  scientific: "Re-invoke the role to revise the scientific content?",
};

// Distinct from CORRECTION_LABELS so tests and assistive tech can tell the
// row button apart from the dialog's confirm button.
const CONFIRM_LABELS: Record<CorrectionType, string> = {
  revalidate: "Confirm re-check",
  normalize: "Confirm normalization",
  packaging: "Confirm packaging correction",
  scientific: "Confirm scientific revision",
};

export function correctionActionsOf(run: RunDetail): Partial<Record<CorrectionType, ActionDescriptor>> {
  const found: Partial<Record<CorrectionType, ActionDescriptor>> = {};
  for (const action of run.actions) {
    for (const [type, actionType] of Object.entries(CORRECTION_ACTION_TYPES) as Array<
      [CorrectionType, ActionDescriptor["action_type"]]
    >) {
      if (action.action_type === actionType) found[type] = action;
    }
  }
  return found;
}

// The normalize command rejects empty transformation_codes; the codes that
// actually acted in the dry run are exactly the set to send on apply.
export function normalizeCodesFromPreview(preview: CorrectionPreview): string[] {
  const codes = new Set<string>();
  for (const record of preview.transformations) {
    for (const entry of record.entries) codes.add(entry.code);
  }
  return [...codes].sort();
}

export interface CorrectionStateNotice {
  className: string;
  role: "alert" | "status";
  title: string;
  body: string;
}

export function correctionStateNotice(run: RunDetail): CorrectionStateNotice | undefined {
  if (run.state === "correction_authorized") {
    return {
      className: "message message--neutral",
      role: "status",
      title: "Correction authorized",
      body: "A correction was authorized for this run. The sealed outputs and the frozen basis are unchanged until a correction succeeds. Choose a correction action below.",
    };
  }
  if (run.state === "correcting") {
    return {
      className: "message message--neutral",
      role: "status",
      title: "Correction in progress",
      body: "A correction attempt is being applied, or a bounded attempt did not succeed. The correction controls below remain available; every attempt is recorded.",
    };
  }
  if (run.state === "correction_exhausted") {
    return {
      className: "message message--warning",
      role: "status",
      title: "Correction attempts exhausted",
      body: "The bounded packaging and scientific correction attempts were spent without a passing correction. A full phase rerun is the remaining recovery path.",
    };
  }
  return undefined;
}

export function CorrectionControls({
  projectId,
  run,
  onCorrectionSettled,
}: {
  projectId: string;
  run: RunDetail;
  onCorrectionSettled: (run: RunDetail) => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const actions = correctionActionsOf(run);
  const available = (Object.keys(actions) as CorrectionType[]).filter((type) => actions[type]);
  const [confirm, setConfirm] = useState<CorrectionType | null>(null);
  const [instruction, setInstruction] = useState("");

  // One dry run scopes all four commands (permitted_output_scope requires at
  // least one entry) and drives the normalize apply enablement. retry: false
  // because a preview refusal is deterministic for the current run state.
  const previewQuery = useQuery({
    queryKey: ["correction-preview", projectId, run.run_id],
    queryFn: () => api.previewRunCorrection(projectId, run.run_id),
    enabled: available.length > 0,
    retry: false,
  });

  const preview = previewQuery.data;
  const outputScope = preview?.output_scope ?? [];
  const normalizeCodes = preview ? normalizeCodesFromPreview(preview) : [];

  const mutation = useMutation({
    mutationFn: (type: CorrectionType) => {
      const action = actions[type];
      if (!action) throw new Error("No correction command is available.");
      if (outputScope.length === 0) throw new Error("The correction scope is unavailable.");
      return api.requestRunCorrection(projectId, run.run_id, action, {
        correction_type: type,
        permitted_output_scope: outputScope,
        ...(type === "normalize" ? { transformation_codes: normalizeCodes } : {}),
        ...(type === "scientific" ? { user_instruction: instruction.trim() } : {}),
      });
    },
    onSuccess: async (updated) => {
      setConfirm(null);
      setInstruction("");
      await onCorrectionSettled(updated);
      await queryClient.invalidateQueries({
        queryKey: ["correction-preview", projectId, run.run_id],
      });
    },
  });

  if (available.length === 0) return null;

  const scopeUnavailable = previewQuery.isPending || previewQuery.isError || outputScope.length === 0;
  const confirmAction = confirm ? actions[confirm] : undefined;

  function disabledReason(type: CorrectionType): string | undefined {
    const action = actions[type];
    if (!action) return undefined;
    if (!action.enabled) {
      return action.researcher_message ?? "This correction is not available in the current run state.";
    }
    if (previewQuery.isPending) return "The correction dry run is still in progress.";
    if (previewQuery.isError) return "The correction dry run is unavailable, so the output scope cannot be determined.";
    if (outputScope.length === 0) return "The target work declares no correctable outputs.";
    if (type === "normalize") {
      if (!preview?.passing) {
        return "The dry run does not clear every blocking check; normalization cannot recover this run.";
      }
      if (normalizeCodes.length === 0) {
        return "The dry run made no transformations, so there is nothing to apply.";
      }
    }
    if (type === "scientific" && !instruction.trim()) {
      return "Describe the required revision before requesting it.";
    }
    return undefined;
  }

  return (
    <Panel
      title="Correct outputs"
      eyebrow="In-place recovery"
      id="correction-controls"
      description="Correct the sealed outputs without discarding the completed work. Each action is recorded as a typed command; bounded lanes allow a limited number of attempts."
    >
      {previewQuery.isPending ? <LoadingState label="Running the correction dry run..." /> : null}
      {previewQuery.error ? (
        <ErrorState error={previewQuery.error} title="The correction dry run is unavailable" />
      ) : null}
      {preview ? (
        <div className="result-callout">
          <StatusPill tone={preview.passing ? "positive" : "warning"}>
            {preview.passing ? "Dry run clears all blocking checks" : "Dry run leaves blocking checks"}
          </StatusPill>
          <p>
            Mechanical normalization would fix {preview.fixed_findings.length} of{" "}
            {preview.current_findings.length} recorded checks
            {preview.remaining_findings.length > 0
              ? `; ${preview.remaining_findings.length} would remain`
              : ""}
            .
          </p>
          {preview.transformations.some((record) => record.entries.length > 0) ? (
            <details>
              <summary>Transformation detail</summary>
              <ul className="finding-groups">
                {preview.transformations
                  .filter((record) => record.entries.length > 0)
                  .map((record) => (
                    <li key={record.contract_output_id} className="finding-group">
                      <code>{record.contract_output_id}</code>
                      <span className="finding-group__count">
                        {record.entries
                          .map((entry) => `${entry.code} at ${entry.json_pointer || "/"}`)
                          .join("; ")}
                      </span>
                    </li>
                  ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : null}

      <ul className="finding-groups">
        {available.map((type) => {
          const action = actions[type];
          if (!action) return null;
          const reason = disabledReason(type);
          const reasonId = `correction-disabled-${type}`;
          return (
            <li key={type} className="finding-group">
              <div>
                <strong>{CORRECTION_LABELS[type]}</strong>
                <p className="run-monitor-note">{action.consequence_summary}</p>
                {reason ? (
                  <p id={reasonId} className="disabled-reason" role="status">
                    {reason}
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                className="button button--quiet"
                disabled={Boolean(reason) || mutation.isPending || scopeUnavailable}
                aria-describedby={reason ? reasonId : undefined}
                onClick={() => setConfirm(type)}
              >
                {CORRECTION_LABELS[type]}
              </button>
            </li>
          );
        })}
      </ul>

      {actions.scientific ? (
        <label className="field">
          <span>Revision instruction (scientific corrections only)</span>
          <textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            rows={3}
            maxLength={4000}
            aria-label="Revision instruction"
          />
          <small>Sealed verbatim into the correction command and passed to the role.</small>
        </label>
      ) : null}

      {mutation.error ? <ErrorState error={mutation.error} title="Correction was not requested" /> : null}

      {confirm && confirmAction ? (
        <ConfirmActionDialog
          open
          action={confirmAction}
          title={CONFIRM_TITLES[confirm]}
          confirmLabel={CONFIRM_LABELS[confirm]}
          busy={mutation.isPending}
          busyNote="Recording the command and preparing the correction workspace can take up to a minute - keep this dialog open."
          onCancel={() => setConfirm(null)}
          onConfirm={() => mutation.mutate(confirm)}
        />
      ) : null}
    </Panel>
  );
}

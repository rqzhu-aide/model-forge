import { useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type {
  ActionDescriptor,
  ContextOption,
  MethodIdentity,
  MethodRow,
  PhaseId,
  PhaseView,
  StartRunRequest,
} from "../api/types";
import { shortDigest } from "../utils/format";
import { runInstructionDraftKey, useLocalDraft } from "../hooks/useLocalDraft";
import { ErrorState } from "./Feedback";
import { MethodSelector, SelectedMethodSummary } from "./MethodSelector";

export const PHASE_ONE_SCOPE_OPTIONS = [
  {
    value: "broad_update",
    label: "Broad literature update",
    description: "Survey the relevant literature broadly and update the current evidence base.",
  },
  {
    value: "focused_update",
    label: "Focused literature question",
    description: "Investigate one specific gap, claim, method, or part of the evidence base.",
  },
] as const;

export type PhaseOneScope = (typeof PHASE_ONE_SCOPE_OPTIONS)[number]["value"];

export interface ContextReviewItem {
  optionId: string;
  label: string;
  digest: string;
}

export function selectedContextReviewItems(
  options: ContextOption[],
  selectedIds: ReadonlySet<string>,
): ContextReviewItem[] {
  return options
    .filter((option) => selectedIds.has(option.option_id))
    .map((option) => ({
      optionId: option.option_id,
      label: option.label,
      digest: option.artifact_pointer?.sha256
        ? shortDigest(option.artifact_pointer.sha256)
        : option.option_id,
    }));
}

export function methodIdentitiesMatch(
  expected: MethodIdentity,
  selected: MethodIdentity | undefined,
): boolean {
  return Boolean(
    selected
    && expected.stable_id === selected.stable_id
    && expected.version === selected.version
    && expected.definition_sha256 === selected.definition_sha256
  );
}

export function actionForSelection(
  actions: ActionDescriptor[],
  mode: string,
  method?: MethodRow,
): ActionDescriptor | undefined {
  return actions.find((action) => {
    if (action.action_type !== "start_run") return false;
    if (action.command_contract?.mode !== mode) return false;
    if (method) {
      if (!action.method_identity || !methodIdentitiesMatch(action.method_identity, method.identity)) return false;
    } else if (action.method_identity) {
      return false;
    }
    if (action.method_id && action.method_id !== method?.identity.stable_id) return false;
    return true;
  });
}

function phaseNeedsMethod(phase: PhaseId, mode: string): boolean {
  return phase === "P3" || phase === "P4" || phase === "P5" || mode === "p2.focused_method";
}

export async function invalidateRunStartDependents(
  queryClient: QueryClient,
  projectId: string,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["projects"] }),
    queryClient.invalidateQueries({ queryKey: ["phase", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["runs", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["overview", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["methods", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["profiles"] }),
  ]);
}

export function RunForm({
  projectId,
  phaseView,
  methods,
  selectedMethodId,
  onMethodChange,
  mode,
  onModeChange,
}: {
  projectId: string;
  phaseView: PhaseView;
  methods: MethodRow[];
  selectedMethodId: string;
  onMethodChange: (methodId: string) => void;
  mode: string;
  onModeChange: (mode: string) => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const {
    value: instructions,
    setValue: setInstructions,
    clear: clearInstructionsDraft,
    restored: restoredInstructionDraft,
  } = useLocalDraft(runInstructionDraftKey(projectId, phaseView.phase_id));
  const [phaseOneScope, setPhaseOneScope] = useState<PhaseOneScope>("broad_update");
  const [selectedHistory, setSelectedHistory] = useState<Set<string>>(new Set());
  const [selectedContext, setSelectedContext] = useState<Set<string>>(new Set());
  const [reviewing, setReviewing] = useState(false);

  useEffect(() => {
    setSelectedContext(
      new Set(
        phaseView.run_configuration.current_inputs
          .filter((item) => item.required || item.selected_by_default)
          .map((item) => item.option_id),
      ),
    );
    setReviewing(false);
  }, [phaseView.run_configuration.current_inputs]);

  const selectedMethod = methods.find((method) => method.identity.stable_id === selectedMethodId);
  const action = actionForSelection(phaseView.actions, mode, selectedMethod);
  const requiresMethod = phaseNeedsMethod(phaseView.phase_id, mode);
  const localMissing: string[] = [];
  if (requiresMethod && !selectedMethod) localMissing.push("Select an active method.");
  if (!instructions.trim()) localMissing.push("Provide instructions for this run.");

  const mutation = useMutation({
    mutationFn: (input: StartRunRequest) => api.startRun(projectId, input),
    onSuccess: async (run) => {
      clearInstructionsDraft();
      await invalidateRunStartDependents(queryClient, projectId);
      navigate(`/projects/${projectId}/runs/${run.run_id}`);
    },
  });

  const currentReviewItems = useMemo(
    () => selectedContextReviewItems(phaseView.run_configuration.current_inputs, selectedContext),
    [phaseView.run_configuration.current_inputs, selectedContext],
  );
  const historyReviewItems = useMemo(
    () => selectedContextReviewItems(phaseView.run_configuration.history_options, selectedHistory),
    [phaseView.run_configuration.history_options, selectedHistory],
  );
  const historyPointers = useMemo(
    () => phaseView.run_configuration.history_options
      .filter((item) => selectedHistory.has(item.option_id))
      .flatMap((item) => item.artifact_pointer ? [item.artifact_pointer] : []),
    [phaseView.run_configuration.history_options, selectedHistory],
  );

  const choiceValues = useMemo(() => {
    const prefix = phaseView.phase_id.toLowerCase();
    const values: Record<string, unknown> = {
      [`${prefix}.instructions`]: instructions.trim(),
      [`${prefix}.selected_history`]: historyPointers,
    };
    if (selectedMethod && requiresMethod) values[`${prefix}.selected_method`] = selectedMethod.identity;
    if (phaseView.phase_id === "P1") values["p1.scope"] = phaseOneScope;
    return values;
  }, [historyPointers, instructions, phaseOneScope, phaseView.phase_id, requiresMethod, selectedMethod]);

  const canReview = Boolean(action?.enabled) && localMissing.length === 0 && !mutation.isPending;
  const disabledMessage = localMissing[0] ?? action?.researcher_message ?? "The backend did not provide an eligible start action for this selection.";

  const toggleSetValue = (
    setter: Dispatch<SetStateAction<Set<string>>>,
    value: string,
    checked: boolean,
  ) => setter((current) => {
    const next = new Set(current);
    if (checked) next.add(value);
    else next.delete(value);
    return next;
  });

  const submit = () => {
    if (!action || !canReview) return;
    mutation.mutate({
      action_descriptor_id: action.descriptor_id,
      phase: phaseView.phase_id,
      mode,
      choice_values: choiceValues,
      context_policy: historyPointers.length ? "current_plus_selected_history" : "current_only",
      selected_context_option_ids: [...selectedContext],
    });
  };

  const contextList = (items: ContextReviewItem[], empty: string) => items.length ? (
    <ul className="launch-review__context-list">
      {items.map((item) => (
        <li key={item.optionId}>
          <span>{item.label}</span>
          <code>{item.digest}</code>
        </li>
      ))}
    </ul>
  ) : empty;

  return (
    <div className="run-form">
      <fieldset>
        <legend>Run scope</legend>
        <div className="choice-cards">
          {phaseView.run_configuration.modes.map((option) => (
            <label key={option.mode_id} data-selected={mode === option.mode_id || undefined}>
              <input
                type="radio"
                name="run-mode"
                value={option.mode_id}
                checked={mode === option.mode_id}
                onChange={() => {
                  setReviewing(false);
                  onModeChange(option.mode_id);
                }}
              />
              <span><strong>{option.label}</strong><small>{option.description}</small></span>
            </label>
          ))}
        </div>
      </fieldset>

      {phaseView.phase_id === "P1" ? (
        <fieldset>
          <legend>Literature update type</legend>
          <p className="field-help">Choose how broadly this run should update the literature. State the scientific boundary in the instructions below.</p>
          <div className="choice-cards">
            {PHASE_ONE_SCOPE_OPTIONS.map((option) => (
              <label key={option.value} data-selected={phaseOneScope === option.value || undefined}>
                <input
                  type="radio"
                  name="phase-one-scope"
                  value={option.value}
                  checked={phaseOneScope === option.value}
                  onChange={() => {
                    setReviewing(false);
                    setPhaseOneScope(option.value);
                  }}
                />
                <span><strong>{option.label}</strong><small>{option.description}</small></span>
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}

      {phaseView.phase_id === "P2" && mode === "p2.focused_method" ? (
        <MethodSelector
          methods={methods}
          selectedMethodId={selectedMethodId}
          onChange={(methodId) => {
            setReviewing(false);
            onMethodChange(methodId);
          }}
          legend="Choose the one method this focused update may change"
        />
      ) : null}

      {phaseView.phase_id === "P5" ? (
        <MethodSelector
          methods={methods}
          selectedMethodId={selectedMethodId}
          onChange={(methodId) => {
            setReviewing(false);
            onMethodChange(methodId);
          }}
          legend="Choose the manuscript method"
        />
      ) : null}

      <label className="field field--prominent">
        <span>{phaseView.run_configuration.instruction_label}</span>
        <textarea
          value={instructions}
          onChange={(event) => {
            setReviewing(false);
            setInstructions(event.target.value);
          }}
          rows={5}
          required
          placeholder={phaseView.run_configuration.instruction_placeholder}
        />
        <small>{phaseView.run_configuration.instruction_help}</small>
        <small className="draft-note" role="status">
          {restoredInstructionDraft
            ? "A locally stored draft was restored. It is cleared after the run starts."
            : "This browser saves an instruction draft locally when storage is available."}
        </small>
      </label>

      <fieldset>
        <legend>Current context for this run</legend>
        <p className="field-help">The backend resolved these typed inputs. Required inputs cannot be removed here.</p>
        <div className="context-list">
          {phaseView.run_configuration.current_inputs.map((option) => (
            <label key={option.option_id}>
              <input
                type="checkbox"
                checked={selectedContext.has(option.option_id)}
                disabled={option.required || option.disabled}
                onChange={(event) => {
                  setReviewing(false);
                  toggleSetValue(setSelectedContext, option.option_id, event.target.checked);
                }}
              />
              <span>
                <strong>{option.label}{option.required ? " (required)" : ""}</strong>
                <small>{option.disabled_reason ?? option.description}</small>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend>Optional historical context</legend>
        {phaseView.run_configuration.history_options.length === 0 ? (
          <p className="field-help">No selectable history is available. The run will use current formal records only.</p>
        ) : (
          <div className="context-list">
            {phaseView.run_configuration.history_options.map((option) => (
              <label key={option.option_id}>
                <input
                  type="checkbox"
                  checked={selectedHistory.has(option.option_id)}
                  disabled={option.disabled}
                  onChange={(event) => {
                    setReviewing(false);
                    toggleSetValue(setSelectedHistory, option.option_id, event.target.checked);
                  }}
                />
                <span><strong>{option.label}</strong><small>{option.disabled_reason ?? option.description}</small></span>
              </label>
            ))}
          </div>
        )}
      </fieldset>

      <div className="run-plan-digest" aria-label="Resolved run sequence">
        <div><p className="eyebrow">Resolved role plan</p><strong>No stage starts until you launch.</strong></div>
        <ol>
          {phaseView.run_configuration.stage_plan.map((stage) => (
            <li key={stage.stage_id}>
              <span>{stage.roles.join(" + ")}</span>
              <small>{stage.execution}, {stage.label}</small>
            </li>
          ))}
        </ol>
      </div>

      {selectedMethod && requiresMethod ? <SelectedMethodSummary method={selectedMethod} /> : null}

      <div className="launch-row">
        <button
          type="button"
          className="button button--primary"
          disabled={!canReview}
          onClick={() => setReviewing(true)}
        >
          Review this run
        </button>
        <p>{canReview ? action?.consequence_summary : disabledMessage}</p>
      </div>

      {reviewing && action ? (
        <section className="launch-review" aria-labelledby="launch-review-title">
          <p className="eyebrow">Final command review</p>
          <h3 id="launch-review-title">Start this exact run?</h3>
          <dl>
            <div><dt>Phase and mode</dt><dd>{phaseView.phase_id}, {mode}</dd></div>
            {phaseView.phase_id === "P1" ? (
              <div><dt>Literature update</dt><dd>{PHASE_ONE_SCOPE_OPTIONS.find((option) => option.value === phaseOneScope)?.label}</dd></div>
            ) : null}
            <div><dt>Method</dt><dd>{selectedMethod ? `${selectedMethod.display_name}, v${selectedMethod.identity.version}` : "Not method-bound"}</dd></div>
            <div><dt>Selected current inputs</dt><dd>{contextList(currentReviewItems, "None")}</dd></div>
            <div><dt>Selected historical inputs</dt><dd>{contextList(historyReviewItems, "None")}</dd></div>
            <div>
              <dt>Contract</dt>
              <dd>{action.command_contract?.phase_contract_version ?? "Not recorded"}, <code>{shortDigest(action.command_contract?.phase_contract_sha256)}</code></dd>
            </div>
          </dl>
          <p>{action.consequence_summary}</p>
          <p className="launch-review__note">
            Starting creates a run-local attempt only. Formal records change only after validation and publication.
          </p>
          <div className="launch-review__actions">
            <button type="button" className="button button--quiet" onClick={() => setReviewing(false)} disabled={mutation.isPending}>Back</button>
            <button type="button" className="button button--primary" onClick={submit} disabled={!canReview}>
              {mutation.isPending ? "Starting run..." : "Start this run"}
            </button>
          </div>
        </section>
      ) : null}

      {mutation.error ? <ErrorState error={mutation.error} title="The run was not started" /> : null}
    </div>
  );
}

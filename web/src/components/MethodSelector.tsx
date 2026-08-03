import type { MethodRow } from "../api/types";
import { CompactPhaseStatus, StatusPill } from "./Status";
import { shortDigest } from "../utils/format";
import { MethodDetailsDisclosure } from "./MethodDetails";

export function MethodSelector({
  methods,
  selectedMethodId,
  onChange,
  legend = "Choose a current method for this run",
}: {
  methods: MethodRow[];
  selectedMethodId: string;
  onChange: (methodId: string) => void;
  legend?: string;
}) {
  const activeMethods = methods.filter((method) => method.lifecycle_state === "active");
  return (
    <fieldset className="method-selector">
      <legend>{legend}</legend>
      {activeMethods.length === 0 ? (
        <p className="field-help">No active method is available from the current Phase 2 catalog.</p>
      ) : (
        <div className="method-selector__list">
          {activeMethods.map((method) => {
            const selected = method.identity.stable_id === selectedMethodId;
            return (
              <label
                className="method-option"
                data-selected={selected || undefined}
                key={`${method.identity.stable_id}-${method.identity.version}`}
              >
                <input
                  type="radio"
                  name="selected-method"
                  value={method.identity.stable_id}
                  checked={selected}
                  onChange={() => onChange(method.identity.stable_id)}
                />
                <span className="method-option__body">
                  <span className="method-option__heading">
                    <strong>{method.display_name}</strong>
                    <StatusPill>{`v${method.identity.version}`}</StatusPill>
                  </span>
                  <span className="method-option__summary">{method.summary}</span>
                  <span className="method-option__identity">
                    <code>{method.identity.stable_id}</code>
                    <span>definition {shortDigest(method.identity.definition_sha256)}</span>
                  </span>
                  <span className="method-option__phase-status" aria-label="Current phase alignment">
                    {(["P3", "P4", "P5"] as const).map((phase) => (
                      <span key={phase}>
                        <b>{phase}</b>
                        <CompactPhaseStatus status={method.phase_statuses[phase]} />
                      </span>
                    ))}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      )}
    </fieldset>
  );
}

export function SelectedMethodSummary({ method }: { method?: MethodRow }) {
  if (!method) return null;
  return (
    <div className="selected-method-summary">
      <div>
        <p className="eyebrow">Selected exact method</p>
        <h3>{method.display_name}</h3>
        <p>{method.summary}</p>
      </div>
      <dl>
        <div><dt>Stable ID</dt><dd><code>{method.identity.stable_id}</code></dd></div>
        <div><dt>Version</dt><dd>{method.identity.version}</dd></div>
        <div>
          <dt>Definition digest</dt>
          <dd><code title={method.identity.definition_sha256}>{shortDigest(method.identity.definition_sha256)}</code></dd>
        </div>
        <div><dt>Lifecycle</dt><dd><StatusPill>{method.lifecycle_state}</StatusPill></dd></div>
      </dl>
      <MethodDetailsDisclosure method={method} />
    </div>
  );
}

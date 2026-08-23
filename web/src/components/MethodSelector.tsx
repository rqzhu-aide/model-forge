import type { MethodRow } from "../api/types";
import { StatusPill } from "./Status";
import { shortDigest } from "../utils/format";
import { MathText } from "./MathText";
import { MethodDetailsDisclosure } from "./MethodDetails";
import { MethodScores } from "./MethodScores";
import { shortMethodName } from "./MethodTable";

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
        <select
          className="method-selector__dropdown"
          name="selected-method"
          value={selectedMethodId}
          onChange={(event) => onChange(event.target.value)}
          aria-label={legend}
        >
          <option value="">Select a method…</option>
          {activeMethods.map((method) => (
            <option
              key={`${method.identity.stable_id}-${method.identity.version}`}
              value={method.identity.stable_id}
            >
              {shortMethodName(method.display_name)}
            </option>
          ))}
        </select>
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
        <h3><MathText text={method.display_name} /></h3>
        <p><MathText text={method.summary} /></p>
        <MethodScores evaluation={method.evaluation} />
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

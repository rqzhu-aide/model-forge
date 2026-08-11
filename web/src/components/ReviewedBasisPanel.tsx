import type { ReviewedBasis, ReviewedRoleResource } from "../api/types";
import { shortDigest } from "../utils/format";
import { Panel } from "./Panel";

export function memoryPolicyLabel(policy: string): string {
  switch (policy) {
    case "persistent":
      return "keeps project memory between runs";
    case "ephemeral":
    case "fresh":
      return "fresh every run";
    case "read_only":
      return "reads memory, never writes";
    default:
      return policy;
  }
}

function RoleResources({ roleId, resource }: { roleId: string; resource: ReviewedRoleResource }) {
  return (
    <div className="reviewed-role">
      <h4><code>{roleId}</code></h4>
      <dl className="record-metadata">
        <div><dt>Profile</dt><dd>{resource.profile}, v{resource.profile_version}</dd></div>
        <div>
          <dt>Soul digest</dt>
          <dd><code title={resource.soul_sha256}>{shortDigest(resource.soul_sha256)}</code></dd>
        </div>
        <div><dt>Model</dt><dd>{resource.model ?? "Not configured"}</dd></div>
        <div><dt>Provider</dt><dd>{resource.provider ?? "Not configured"}</dd></div>
        <div>
          <dt>Memory policy</dt>
          <dd>{resource.memory_policy} — {memoryPolicyLabel(resource.memory_policy)}</dd>
        </div>
        <div><dt>Phase instruction</dt><dd>{resource.phase_instruction ?? "None in contract"}</dd></div>
        <div><dt>Tools</dt><dd>{resource.tools ?? "Not configured"}</dd></div>
      </dl>
      <ul className="reviewed-skills">
        {resource.skills.map((skill) => (
          <li key={skill.skill_id}>
            <code>{skill.skill_id}</code>
            <small>{skill.source}@{skill.source_revision}</small>
            <code className="reviewed-skills__digest" title={skill.bundle_sha256}>{shortDigest(skill.bundle_sha256)}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ReviewedBasisPanel({ basis }: { basis: ReviewedBasis | null | undefined }) {
  if (!basis) {
    return (
      <Panel
        eyebrow="Reviewed basis"
        title="Sealed basis for this view"
        description="Every start-run action seals the reviewed basis at review time so the run cannot proceed on state that drifted afterwards."
      >
        <p className="muted-note">No sealed basis for this view.</p>
      </Panel>
    );
  }

  const roleEntries = Object.entries(basis.role_resources);

  return (
    <Panel
      eyebrow="Reviewed basis"
      title="What a run command seals"
      description="The start-run action seals this basis at review time: the authority head, the exact current inputs, the method binding, and the role resources. If any part drifts before launch, the run is rejected as stale instead of proceeding on outdated state."
    >
      <details className="reviewed-basis">
        <summary>
          Review the sealed basis · {basis.reviewed_current_inputs.length} current input
          {basis.reviewed_current_inputs.length === 1 ? "" : "s"} · {roleEntries.length} role
          {roleEntries.length === 1 ? "" : "s"}
        </summary>

        <h3 className="panel-subheading">Authority head</h3>
        <dl className="record-metadata">
          <div><dt>Authority sequence</dt><dd>{basis.authority_head.authority_sequence}</dd></div>
          <div>
            <dt>Authority root</dt>
            <dd><code title={basis.authority_head.authority_root_sha256}>{shortDigest(basis.authority_head.authority_root_sha256)}</code></dd>
          </div>
          <div><dt>Current revision</dt><dd>{basis.authority_head.current_revision}</dd></div>
        </dl>

        <h3 className="panel-subheading">Reviewed current inputs</h3>
        {basis.reviewed_current_inputs.length === 0 ? (
          <p className="muted-note">No current inputs were reviewed for this command.</p>
        ) : (
          <ul className="reviewed-inputs-list">
            {basis.reviewed_current_inputs.map((input) => (
              <li key={input.option_id}>
                <code>{input.option_id}</code>
                <span>{input.generation_id}</span>
                <code className="reviewed-inputs-list__digest" title={input.sha256}>{shortDigest(input.sha256)}</code>
              </li>
            ))}
          </ul>
        )}

        <h3 className="panel-subheading">Method binding</h3>
        {basis.method_identity ? (
          <p className="reviewed-method">
            <code>{basis.method_identity.stable_id}</code>, v{basis.method_identity.version} · definition{" "}
            <code title={basis.method_identity.definition_sha256}>{shortDigest(basis.method_identity.definition_sha256)}</code>
          </p>
        ) : (
          <p className="muted-note">Not method-bound.</p>
        )}

        <h3 className="panel-subheading">Role resources</h3>
        {roleEntries.length === 0 ? (
          <p className="muted-note">No role resources were sealed for this command.</p>
        ) : (
          roleEntries.map(([roleId, resource]) => (
            <RoleResources key={roleId} roleId={roleId} resource={resource} />
          ))
        )}
      </details>
    </Panel>
  );
}

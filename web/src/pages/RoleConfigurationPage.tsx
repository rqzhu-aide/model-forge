import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type {
  AssetStatusView,
  ConfigurationAssetType,
  ProvisionRoleRequest,
  ProvisionResultView,
  RoleDefinitionView,
  RoleHealthReportView,
  SkillRecommendationView,
} from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/Feedback";
import { Panel } from "../components/Panel";
import { StatusPill, configurationAssetTone, configurationOverallTone } from "../components/Status";
import { NotFoundPage } from "./NotFoundPage";

export const CONFIGURATION_ASSET_TYPES: readonly ConfigurationAssetType[] = [
  "soul",
  "base_configuration",
  "library_guidance",
  "skill",
];

const ASSET_TYPE_LABELS: Record<ConfigurationAssetType, string> = {
  soul: "SOUL",
  base_configuration: "Base configuration",
  library_guidance: "Library guidance",
  skill: "Skill",
};

const INITIAL_PROVISION_REQUEST: ProvisionRoleRequest = {
  install_skills: true,
  force_overwrite_assets: false,
  force_overwrite_skills: false,
};

export function assetTypeLabel(assetType: ConfigurationAssetType): string {
  return ASSET_TYPE_LABELS[assetType];
}

export function healthAssets(health: RoleHealthReportView): AssetStatusView[] {
  return [
    health.soul_status,
    health.configuration_status,
    health.guidance_status,
    ...health.skill_statuses,
  ];
}

export function healthSkillAsset(
  health: RoleHealthReportView,
  skillId: string,
): AssetStatusView | undefined {
  // Skill asset file names are the skill ids themselves.
  return health.skill_statuses.find((asset) => asset.file_name === skillId);
}

export function extractProvisionConflict(error: unknown): ApiError | undefined {
  if (!(error instanceof ApiError)) return undefined;
  if (error.status !== 409 || error.code !== "CUSTOMIZATION_CONFLICT") return undefined;
  return error;
}

/**
 * Match the 409 CUSTOMIZATION_CONFLICT against the customized assets reported
 * by the role health report. Asset conflicts carry
 * object_refs = [role_id, asset_type, file_name]; skill-directory conflicts
 * carry object_refs = [role_id, profile_name] and fall back to the customized
 * skill entry. The 409 body itself carries no digests — expected vs actual
 * digests come from the matching AssetStatusView entry.
 */
export function conflictingAsset(
  health: RoleHealthReportView,
  error: ApiError,
): AssetStatusView | undefined {
  const refs = error.objectRefs ?? [];
  const customized = healthAssets(health).filter((asset) => asset.status === "customized");
  if (customized.length === 0) return undefined;

  const typeRef = refs[1];
  if (typeRef !== undefined && (CONFIGURATION_ASSET_TYPES as readonly string[]).includes(typeRef)) {
    const fileName = refs[2];
    return customized.find(
      (asset) => asset.asset_type === typeRef
        && (fileName === undefined || asset.file_name === fileName),
    );
  }
  return customized.find((asset) => asset.asset_type === "skill") ?? customized[0];
}

export function overwriteProvisionRequest(
  asset: AssetStatusView | undefined,
  error: ApiError,
): ProvisionRoleRequest {
  const refs = error.objectRefs ?? [];
  const typeRef = refs[1];
  const isSkillConflict = asset?.asset_type === "skill"
    || typeRef === "skill"
    || (typeRef !== undefined
      && !(CONFIGURATION_ASSET_TYPES as readonly string[]).includes(typeRef));
  return {
    install_skills: true,
    force_overwrite_assets: true,
    force_overwrite_skills: isSkillConflict,
  };
}

function ProvisionOutcome({ result }: { result: ProvisionResultView }) {
  return (
    <div className="message message--neutral provision-outcome-message" role="status">
      <div>
        <strong>Role definition provisioned</strong>
        <p>Profile {result.profile_name} was updated for role {result.role_id}.</p>
        <dl className="record-metadata">
          <div>
            <dt>Assets written</dt>
            <dd>
              {result.assets_written.length > 0
                ? result.assets_written.join(", ")
                : "None (all assets already matched)"}
            </dd>
          </div>
          <div>
            <dt>Skills installed</dt>
            <dd>
              {result.skills_installed.length > 0
                ? result.skills_installed.join(", ")
                : "None"}
            </dd>
          </div>
        </dl>
        {result.rolled_back ? (
          <p className="muted-text">
            The write was rolled back after a partial failure; the profile is unchanged.
          </p>
        ) : null}
      </div>
    </div>
  );
}

function ProvisionConflict({
  error,
  asset,
  busy,
  onConfirm,
}: {
  error: ApiError;
  asset: AssetStatusView | undefined;
  busy: boolean;
  onConfirm: () => void;
}) {
  return (
    <div className="message message--warning provision-conflict" role="alert">
      <div>
        <strong>Customization conflict</strong>
        <p>{error.message}</p>
        {error.smallestCorrection ? (
          <p><span className="message__label">Next step:</span> {error.smallestCorrection}</p>
        ) : null}
        {error.objectRefs && error.objectRefs.length > 0 ? (
          <p className="provision-conflict__refs">
            <span className="message__label">Conflicting reference:</span>{" "}
            <code>{error.objectRefs.join(" / ")}</code>
          </p>
        ) : null}
        {asset ? (
          <dl className="digest-pair">
            <div>
              <dt>Asset</dt>
              <dd>{assetTypeLabel(asset.asset_type)} <code>{asset.file_name}</code></dd>
            </div>
            <div>
              <dt>Expected digest (reference)</dt>
              <dd><code>{asset.expected_sha256}</code></dd>
            </div>
            <div>
              <dt>Actual digest (customized)</dt>
              <dd><code>{asset.actual_sha256 ?? "Not readable"}</code></dd>
            </div>
          </dl>
        ) : (
          <p className="muted-text">
            The role health report does not list a matching customized asset; the conflict
            references the profile directory directly.
          </p>
        )}
        <div className="action-with-reason">
          <button
            type="button"
            className="button button--danger"
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? "Overwriting..." : "Overwrite customization"}
          </button>
          <p className="muted-text">
            Overwriting replaces the customized file with the configuration-managed reference
            and provisions again. This explicit action cannot be undone.
          </p>
        </div>
      </div>
    </div>
  );
}

function RecommendedSkillRow({
  skill,
  health,
}: {
  skill: SkillRecommendationView;
  health: RoleHealthReportView;
}) {
  const asset = healthSkillAsset(health, skill.skill_id);
  return (
    <li>
      <div className="skill-list__heading">
        <div>
          <strong>{skill.name}</strong>
          <code>{skill.skill_id}</code>
        </div>
        {asset ? (
          <StatusPill tone={configurationAssetTone(asset.status)}>{asset.status}</StatusPill>
        ) : null}
      </div>
      <p>{skill.description}</p>
      <dl>
        <div><dt>Source</dt><dd><code>{skill.source}</code></dd></div>
        <div><dt>Recommended version</dt><dd>{skill.recommended_version}</dd></div>
        {asset ? <div><dt>Installation</dt><dd>{asset.detail}</dd></div> : null}
      </dl>
    </li>
  );
}

export function SkillAssignmentsPanel({ roleId }: { roleId: string }) {
  const queryClient = useQueryClient();
  const assignmentsQuery = useQuery({
    queryKey: ["role-skill-assignments", roleId],
    queryFn: () => api.getRoleSkillAssignments(roleId),
  });
  const mutation = useMutation({
    mutationFn: (input: { phase: string; skills: string[] | null }) =>
      api.updateRoleSkillAssignments(roleId, input.phase, { skills: input.skills }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["role-skill-assignments", roleId] });
    },
  });

  const busy = mutation.isPending;

  const toggle = (phase: string, skillId: string, currentlyEffective: string[]) => {
    const next = currentlyEffective.includes(skillId)
      ? currentlyEffective.filter((id) => id !== skillId)
      : [...currentlyEffective, skillId];
    mutation.mutate({ phase, skills: next });
  };

  return (
    <Panel
      eyebrow="Skill assignments"
      title="Skills per phase"
      description="Which skills this member carries into each phase. Edits take effect at the next run seal; in-flight runs are untouched."
    >
      {assignmentsQuery.isLoading ? <p className="muted-text">Loading skill assignments...</p> : null}
      {assignmentsQuery.error ? (
        <p className="muted-text" role="alert">
          Skill assignments are unavailable: {String(assignmentsQuery.error)}
        </p>
      ) : null}
      {assignmentsQuery.data ? (
        <>
          <table className="skill-matrix">
            <thead>
              <tr>
                <th scope="col">Skill</th>
                {assignmentsQuery.data.phases.map((entry) => (
                  <th scope="col" key={entry.phase}>
                    <div className="skill-matrix__phase">
                      <span>{entry.phase}</span>
                      <StatusPill tone={entry.source === "assigned" ? "information" : "neutral"}>
                        {entry.source}
                      </StatusPill>
                      {entry.source === "assigned" ? (
                        <button
                          type="button"
                          className="button button--quiet button--small"
                          disabled={busy}
                          onClick={() => mutation.mutate({ phase: entry.phase, skills: null })}
                        >
                          Reset
                        </button>
                      ) : null}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {assignmentsQuery.data.available_skills.map((skill) => (
                <tr key={skill.skill_id}>
                  <th scope="row">
                    <code>{skill.skill_id}</code>
                    <span className="skill-matrix__digest">{skill.content_sha256.slice(0, 12)}</span>
                  </th>
                  {assignmentsQuery.data.phases.map((entry) => {
                    const checked = entry.skills.includes(skill.skill_id);
                    return (
                      <td key={entry.phase}>
                        <input
                          type="checkbox"
                          aria-label={`${skill.skill_id} in ${entry.phase}`}
                          checked={checked}
                          disabled={busy}
                          onChange={() => toggle(entry.phase, skill.skill_id, entry.skills)}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {mutation.error ? (
            <p className="muted-text" role="alert">
              The assignment was not saved: {String(mutation.error)}
            </p>
          ) : null}
          <dl className="record-metadata">
            {assignmentsQuery.data.matrix_sha256 ? (
              <div>
                <dt>Assignment matrix digest</dt>
                <dd><code>{assignmentsQuery.data.matrix_sha256}</code></dd>
              </div>
            ) : null}
          </dl>
        </>
      ) : null}
    </Panel>
  );
}

export function RoleConfigurationPage() {
  const { roleId } = useParams();
  const queryClient = useQueryClient();

  const definitionQuery = useQuery({
    queryKey: ["role-definition", roleId],
    queryFn: () => api.getRoleDefinition(roleId as string),
    enabled: Boolean(roleId),
  });
  const healthQuery = useQuery({
    queryKey: ["role-health", roleId],
    queryFn: () => api.getRoleHealth(roleId as string),
    enabled: Boolean(roleId),
  });

  const provisionMutation = useMutation({
    mutationFn: (input: ProvisionRoleRequest) => api.provisionRole(roleId as string, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["role-health", roleId] });
      void queryClient.invalidateQueries({ queryKey: ["role-definition", roleId] });
      void queryClient.invalidateQueries({ queryKey: ["configuration-health"] });
    },
  });

  if (!roleId) return <NotFoundPage />;
  if (definitionQuery.isLoading || healthQuery.isLoading) {
    return <LoadingState label="Loading role definition..." />;
  }
  if (definitionQuery.error) {
    if (definitionQuery.error instanceof ApiError && definitionQuery.error.status === 404) {
      return <NotFoundPage />;
    }
    return <ErrorState error={definitionQuery.error} title="Role definition is unavailable" />;
  }
  if (healthQuery.error) {
    return <ErrorState error={healthQuery.error} title="Role health report is unavailable" />;
  }
  if (!definitionQuery.data || !healthQuery.data) return <NotFoundPage />;

  const definition: RoleDefinitionView = definitionQuery.data;
  const health: RoleHealthReportView = healthQuery.data;
  const conflict = extractProvisionConflict(provisionMutation.error);
  const conflictAsset = conflict ? conflictingAsset(health, conflict) : undefined;

  return (
    <div className="page-stack">
      <header className="page-header page-header--with-action">
        <div>
          <p className="eyebrow">Role configuration</p>
          <h1>{definition.display_name}</h1>
          <p>
            <code>{definition.role_id}</code> · profile version {definition.profile_version} ·
            default profile {definition.default_profile}
          </p>
        </div>
        <Link to="/configuration" className="button button--quiet">All role configuration</Link>
      </header>

      <Panel
        eyebrow="Role definition"
        title="Overview"
        description="The role definition is the configuration-managed reference for this role."
      >
        <dl className="record-metadata">
          <div><dt>Role id</dt><dd><code>{definition.role_id}</code></dd></div>
          <div><dt>Profile version</dt><dd>{definition.profile_version}</dd></div>
          <div><dt>Default profile</dt><dd>{definition.default_profile}</dd></div>
          <div><dt>Applicable phases</dt><dd>{definition.applicable_phases.join(", ")}</dd></div>
          <div>
            <dt>Overall health</dt>
            <dd>
              <StatusPill tone={configurationOverallTone(health.overall_status)}>
                {health.overall_status}
              </StatusPill>
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel
        eyebrow="System prompt"
        title="SOUL definition"
        description="Read-only reference text. It is written into the profile only by provisioning."
      >
        <pre className="soul-text">{definition.soul_text}</pre>
        <dl className="record-metadata">
          <div><dt>SOUL digest</dt><dd><code>{definition.soul_sha256}</code></dd></div>
          <div>
            <dt>Status</dt>
            <dd>
              <StatusPill tone={configurationAssetTone(health.soul_status.status)}>
                {health.soul_status.status}
              </StatusPill>
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel
        eyebrow="Base configuration"
        title="Configuration file"
        description="The YAML or JSON configuration written into the role's profile."
      >
        <dl className="record-metadata">
          <div><dt>File name</dt><dd><code>{definition.base_configuration.file_name}</code></dd></div>
          <div><dt>Format</dt><dd>{definition.base_configuration.format}</dd></div>
          <div>
            <dt>Content digest</dt>
            <dd><code>{definition.base_configuration.content_sha256}</code></dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>
              <StatusPill tone={configurationAssetTone(health.configuration_status.status)}>
                {health.configuration_status.status}
              </StatusPill>
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel
        eyebrow="Skills"
        title="Recommended and custom skills"
        description="Recommended skills come from the role bundle; the status pill is observed in the target Hermes profile."
      >
        {definition.recommended_skills.length === 0 && definition.custom_skills.length === 0 ? (
          <EmptyState title="No skills are defined for this role">
            <p>This role definition does not declare recommended or custom skills.</p>
          </EmptyState>
        ) : null}
        {definition.recommended_skills.length > 0 ? (
          <>
            <h3>Recommended skills</h3>
            <ul className="skill-list">
              {definition.recommended_skills.map((skill) => (
                <RecommendedSkillRow skill={skill} health={health} key={skill.skill_id} />
              ))}
            </ul>
          </>
        ) : null}
        {definition.custom_skills.length > 0 ? (
          <>
            <h3>Custom skills</h3>
            <ul className="skill-list">
              {definition.custom_skills.map((skill) => (
                <li key={skill.skill_id}>
                  <div className="skill-list__heading">
                    <div>
                      <strong>{skill.name}</strong>
                      <code>{skill.skill_id}</code>
                    </div>
                  </div>
                  <p>{skill.description}</p>
                  <dl>
                    <div><dt>Source</dt><dd><code>{skill.source}</code></dd></div>
                  </dl>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </Panel>

      <SkillAssignmentsPanel roleId={roleId} />

      <Panel
        eyebrow="Library guidance"
        title="Guidance file"
        description="The reference guidance document written into the profile."
      >
        <dl className="record-metadata">
          <div><dt>File name</dt><dd><code>{definition.library_guidance.file_name}</code></dd></div>
          <div>
            <dt>Content digest</dt>
            <dd><code>{definition.library_guidance.content_sha256}</code></dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>
              <StatusPill tone={configurationAssetTone(health.guidance_status.status)}>
                {health.guidance_status.status}
              </StatusPill>
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel
        eyebrow="Installation health"
        title="Role health report"
        description={health.detail}
      >
        <dl className="status-grid">
          <div>
            <dt>Overall status</dt>
            <dd>
              <StatusPill tone={configurationOverallTone(health.overall_status)}>
                {health.overall_status}
              </StatusPill>
            </dd>
          </div>
          <div>
            <dt>Profile available</dt>
            <dd>{health.profile_available ? health.profile_name ?? "Yes" : "No"}</dd>
          </div>
          <div>
            <dt>Conditions</dt>
            <dd>{health.conditions.length > 0 ? health.conditions.join(", ") : "None"}</dd>
          </div>
        </dl>
        <ul className="config-list">
          {healthAssets(health).map((asset) => (
            <li key={`${asset.asset_type}-${asset.file_name}`}>
              <div className="skill-list__heading">
                <div>
                  <strong>{assetTypeLabel(asset.asset_type)}</strong>
                  <code>{asset.file_name}</code>
                </div>
                <StatusPill tone={configurationAssetTone(asset.status)}>{asset.status}</StatusPill>
              </div>
              {asset.status === "customized" ? (
                <dl className="digest-pair">
                  <div>
                    <dt>Expected digest</dt>
                    <dd><code>{asset.expected_sha256}</code></dd>
                  </div>
                  <div>
                    <dt>Actual digest</dt>
                    <dd><code>{asset.actual_sha256 ?? "Not readable"}</code></dd>
                  </div>
                </dl>
              ) : null}
              <p className="skill-list__detail">{asset.detail}</p>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel
        eyebrow="Explicit user action"
        title="Provision role definition"
        description="Writes the SOUL, base configuration, and library guidance into the role's Hermes profile and installs the recommended skills. A customized file blocks provisioning until you explicitly choose to overwrite it."
      >
        <div className="action-with-reason">
          <button
            type="button"
            className="button button--primary"
            disabled={provisionMutation.isPending}
            onClick={() => provisionMutation.mutate(INITIAL_PROVISION_REQUEST)}
          >
            {provisionMutation.isPending ? "Provisioning..." : "Provision role definition"}
          </button>
          <p className="muted-text">
            Provisioning is an explicit command; nothing is written without this action.
          </p>
        </div>

        {provisionMutation.data ? <ProvisionOutcome result={provisionMutation.data} /> : null}
        {conflict ? (
          <ProvisionConflict
            error={conflict}
            asset={conflictAsset}
            busy={provisionMutation.isPending}
            onConfirm={() => provisionMutation.mutate(overwriteProvisionRequest(conflictAsset, conflict))}
          />
        ) : null}
        {provisionMutation.error && !conflict ? (
          <ErrorState error={provisionMutation.error} title="Provisioning failed" />
        ) : null}
      </Panel>
    </div>
  );
}

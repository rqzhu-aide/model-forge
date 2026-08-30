import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ProfileOption, RoleProfileView, SkillStatus } from "../api/types";
import { ErrorState, LoadingState } from "../components/Feedback";
import { Panel } from "../components/Panel";
import { ProjectionNote } from "../components/ProjectionNote";
import { StatusPill } from "../components/Status";
import { NotFoundPage } from "./NotFoundPage";

function skillTone(status: SkillStatus["status"]): "positive" | "warning" | "danger" | "neutral" {
  if (status === "installed") return "positive";
  if (status === "missing" || status === "update_available") return "warning";
  if (status === "unavailable") return "danger";
  return "neutral";
}

export function profileSaveExplanation(
  role: RoleProfileView,
  selected: ProfileOption | undefined,
  pending: boolean,
): string {
  if (!selected) return "Select an available Hermes profile.";
  if (selected.profile_id === role.profile_id) {
    return selected.researcher_message ?? "This profile is already assigned.";
  }
  if (!selected.enabled) return selected.researcher_message ?? "This Hermes profile is unavailable for this role.";
  if (pending) return "The profile assignment is being saved.";
  return "Saving changes only future runs. Active and completed runs retain their frozen profile assignment.";
}

export function RoleProfileCard({ projectId, role }: { projectId: string; role: RoleProfileView }) {
  const queryClient = useQueryClient();
  const [selectedProfileId, setSelectedProfileId] = useState(role.profile_id);
  const selectedOption = role.profile_options.find((option) => option.profile_id === selectedProfileId);
  const currentOption = role.profile_options.find((option) => option.profile_id === role.profile_id);
  const unavailableOptions = role.profile_options.filter(
    (option) => !option.enabled && option.profile_id !== role.profile_id,
  );

  useEffect(() => setSelectedProfileId(role.profile_id), [role.profile_id]);

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!selectedOption?.enabled) throw new Error("Select an available profile assignment.");
      return api.saveProfile(
        projectId,
        role.role_id,
        selectedOption.profile_id,
        selectedOption.action_descriptor_id,
      );
    },
    onSuccess: (configuration) => queryClient.setQueryData(["profiles", projectId], configuration),
  });

  const installMutation = useMutation({
    mutationFn: ({ skill, actionId }: { skill: SkillStatus; actionId: string }) =>
      api.installSkill(projectId, role.role_id, skill.skill_id, actionId),
    onSuccess: (configuration) => queryClient.setQueryData(["profiles", projectId], configuration),
  });

  const optionReasonsId = `${role.role_id}-profile-option-reasons`;
  const currentOptionReasonId = `${role.role_id}-current-profile-reason`;
  const saveReasonId = `${role.role_id}-profile-save-reason`;
  const saveExplanation = profileSaveExplanation(role, selectedOption, saveMutation.isPending);
  const saveDisabled = !selectedOption
    || !selectedOption.enabled
    || selectedOption.profile_id === role.profile_id
    || saveMutation.isPending;
  const describedBy = [
    currentOption?.researcher_message ? currentOptionReasonId : undefined,
    unavailableOptions.length ? optionReasonsId : undefined,
  ].filter(Boolean).join(" ") || undefined;

  return (
    <article className="profile-card">
      <header>
        <div>
          <p className="eyebrow">Research team member</p>
          <h2>{role.display_name}</h2>
          <p>{role.role_summary}</p>
        </div>
        <div className="phase-tags" aria-label="Applicable phases">
          {role.applicable_phases.map((phase) => <span key={phase}>{phase}</span>)}
        </div>
      </header>

      <section className="profile-card__section" aria-labelledby={`${role.role_id}-observed`}>
        <div className="profile-card__section-heading">
          <h3 id={`${role.role_id}-observed`}>Observed project configuration</h3>
          <p>These values are reported by the current project projection.</p>
        </div>
        <dl className="profile-science-grid">
          <div><dt>Assigned Hermes profile</dt><dd><code>{role.profile_id}</code></dd></div>
          <div><dt>Role resource version</dt><dd>{role.profile_version}</dd></div>
          <div><dt>Available local profiles</dt><dd>{role.profile_options.length}</dd></div>
        </dl>
      </section>

      <section className="profile-card__section" aria-labelledby={`${role.role_id}-change-profile`}>
        <div className="profile-card__section-heading">
          <h3 id={`${role.role_id}-change-profile`}>Profile used by future runs</h3>
          <p>Changing this assignment does not alter active or completed runs.</p>
        </div>
        <div className="profile-card__configuration">
          <label className="field">
            <span>Hermes profile</span>
            <select
              value={selectedProfileId}
              aria-describedby={describedBy}
              onChange={(event) => setSelectedProfileId(event.target.value)}
            >
              {role.profile_options.map((option) => (
                <option
                  value={option.profile_id}
                  key={`${option.profile_id}-${option.version}`}
                  disabled={!option.enabled && option.profile_id !== role.profile_id}
                >
                  {option.label} ({option.version})
                  {option.profile_id === role.profile_id ? " (current)" : option.enabled ? "" : " (unavailable)"}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="button button--primary"
            disabled={saveDisabled}
            aria-describedby={saveReasonId}
            onClick={() => saveMutation.mutate()}
          >
            {saveMutation.isPending ? "Saving..." : "Save profile"}
          </button>
        </div>
        <p id={saveReasonId} className={saveDisabled ? "disabled-reason" : "muted-text"} role="status">
          {saveExplanation}
        </p>
        {currentOption?.researcher_message ? (
          <p id={currentOptionReasonId} className="profile-current-reason">
            <strong>Current assignment:</strong> {currentOption.researcher_message}
          </p>
        ) : null}
        {unavailableOptions.length ? (
          <div id={optionReasonsId} className="profile-option-reasons">
            <strong>Unavailable assignments</strong>
            <ul>
              {unavailableOptions.map((option) => (
                <li key={option.profile_id}>
                  <span>{option.label}:</span> {option.researcher_message ?? "Unavailable for this role."}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      <section className="profile-card__section" aria-labelledby={`${role.role_id}-policy`}>
        <div className="profile-card__section-heading">
          <h3 id={`${role.role_id}-policy`}>Run-preparation policy</h3>
          <p>These summaries describe how the system prepares this role. They are not a live view of profile memory or provider settings.</p>
        </div>
        <dl className="profile-science-grid">
          <div><dt>Scientific stance</dt><dd>{role.scientific_stance_summary}</dd></div>
          <div><dt>Model resolution</dt><dd>{role.model_summary}</dd></div>
          <div><dt>Memory policy</dt><dd>{role.memory_policy_summary}</dd></div>
          <div><dt>Phase participation</dt><dd>{role.applicable_phases.join(", ")}</dd></div>
        </dl>
      </section>

      <section className="skill-section profile-card__section" aria-labelledby={`${role.role_id}-skills`}>
        <div className="profile-card__section-heading">
          <h3 id={`${role.role_id}-skills`}>Recommended skills</h3>
          <p>Installation status is observed in the assigned local Hermes profile. Installation remains an explicit action.</p>
        </div>
        <ul className="skill-list">
          {role.skills.map((skill) => {
            const installAction = skill.actions.find((action) => action.action_type === "install_skill");
            const installReasonId = `${role.role_id}-${skill.skill_id}-install-reason`;
            return (
              <li key={skill.skill_id}>
                <div className="skill-list__heading">
                  <div><strong>{skill.name}</strong>{skill.required ? <span className="required-label">Required</span> : null}</div>
                  <StatusPill tone={skillTone(skill.status)}>{skill.status.replaceAll("_", " ")}</StatusPill>
                </div>
                <p>{skill.description}</p>
                <p className="skill-list__detail">{skill.status_detail}</p>
                <dl>
                  <div><dt>Installed</dt><dd>{skill.installed_version ?? "Not installed"}</dd></div>
                  <div><dt>Recommended</dt><dd>{skill.recommended_version ?? "Not specified"}</dd></div>
                  {skill.source_revision ? <div><dt>Pinned source</dt><dd><code>{skill.source_revision}</code></dd></div> : null}
                </dl>
                {installAction ? (
                  <div className="action-with-reason">
                    <button
                      type="button"
                      className="button button--small button--quiet"
                      disabled={!installAction.enabled || installMutation.isPending}
                      aria-describedby={!installAction.enabled ? installReasonId : undefined}
                      onClick={() => installMutation.mutate({ skill, actionId: installAction.descriptor_id })}
                    >
                      {installMutation.isPending ? "Installing..." : skill.status === "update_available" ? "Update skill" : "Install skill"}
                    </button>
                    {!installAction.enabled ? (
                      <p id={installReasonId} className="disabled-reason" role="status">
                        {installAction.researcher_message ?? "Skill installation is unavailable for the assigned profile."}
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </section>

      {saveMutation.error ? <ErrorState error={saveMutation.error} title={`${role.display_name} profile was not saved`} /> : null}
      {installMutation.error ? <ErrorState error={installMutation.error} title={`${role.display_name} skill was not installed`} /> : null}
    </article>
  );
}

export function ProfilesPage() {
  const { projectId } = useParams();
  const profilesQuery = useQuery({
    queryKey: ["profiles", projectId],
    queryFn: () => api.getProfiles(projectId as string),
    enabled: Boolean(projectId),
  });

  if (!projectId) return <NotFoundPage />;
  if (profilesQuery.isLoading) return <LoadingState label="Loading profiles and skills..." />;
  if (profilesQuery.error) return <ErrorState error={profilesQuery.error} title="Profiles and skills are unavailable" />;
  if (!profilesQuery.data) return <NotFoundPage />;

  return (
    <div className="page-stack">
      <header className="page-header page-header--with-action">
        <div>
          <p className="eyebrow">Project configuration</p>
          <h1>Research profiles and skills</h1>
          <p>Inspect each role's assigned profile, scientific policy, and recommended skill status before making a change.</p>
        </div>
        <Link to={`/projects/${encodeURIComponent(projectId)}`} className="button button--quiet">Project overview</Link>
      </header>

      <Panel title="How this configuration is used" eyebrow="Phase-specific team context">
        <p>
          The backend resolves the profile, soul, memory policy, and installed skills for each role when a run is prepared.
          Saving a profile or installing a skill does not start a research phase.
        </p>
        <p className="reviewer-isolation-note">
          <strong>Outside-review independence:</strong> Sharing an author Hermes profile with the outside reviewer would directly mix persistent
          author-role memory into the review process. The current Hermes integration cannot attest that reviewer memory is empty, so the reviewer
          must use a profile that is not assigned to the research lead, theorist, or data analyst.
        </p>
      </Panel>

      <div className="profile-list">
        {profilesQuery.data.profiles.map((role) => {
          const attention = role.skills.filter(
            (skill) => skill.status === "missing" || skill.status === "update_available",
          ).length;
          return (
            <details className="profile-collapsible" key={role.role_id}>
              <summary>
                <span className="profile-collapsible__name">{role.display_name}</span>
                <span className="profile-collapsible__meta">
                  Profile: <code>{role.profile_id}</code>
                  {" · "}
                  {role.skills.length} recommended skill{role.skills.length === 1 ? "" : "s"}
                  {attention ? (
                    <span className="profile-collapsible__attention">
                      {" · "}{attention} need{attention === 1 ? "s" : ""} attention
                    </span>
                  ) : null}
                </span>
              </summary>
              <RoleProfileCard projectId={projectId} role={role} />
            </details>
          );
        })}
      </div>
      <ProjectionNote projection={profilesQuery.data.projection} />
    </div>
  );
}

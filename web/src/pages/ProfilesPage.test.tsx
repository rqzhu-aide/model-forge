import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ActionDescriptor, RoleProfileView } from "../api/types";
import { profileSaveExplanation, RoleProfileCard } from "./ProfilesPage";

const disabledInstall: ActionDescriptor = {
  descriptor_id: "install-disabled",
  action_type: "install_skill",
  enabled: false,
  researcher_message: "Select an available Hermes profile before installing this skill.",
  consequence_summary: "Install the recommended skill.",
};

const role: RoleProfileView = {
  role_id: "outside_reviewer",
  display_name: "Outside reviewer",
  role_summary: "Reviews the closed manuscript packet independently.",
  profile_id: "independent-reviewer",
  profile_version: "2.0",
  profile_options: [
    {
      profile_id: "independent-reviewer",
      label: "Independent reviewer",
      version: "local",
      enabled: false,
      researcher_message: "This profile is already assigned.",
      action_descriptor_id: "save-independent-reviewer",
    },
    {
      profile_id: "author-profile",
      label: "Research lead profile",
      version: "local",
      enabled: false,
      researcher_message: "Already assigned to an authoring role; reviewer memory must remain independent.",
      action_descriptor_id: "save-author-profile",
    },
  ],
  scientific_stance_summary: "Evaluate the closed packet without author-team memory.",
  model_summary: "Model and provider settings are read from the selected Hermes profile.",
  memory_policy_summary: "Only the closed review packet is used.",
  applicable_phases: ["P5"],
  skills: [
    {
      skill_id: "stat-paper-reviewer",
      name: "Statistical paper reviewer",
      description: "Independent statistical review guidance.",
      required: true,
      status: "missing",
      recommended_version: "pinned",
      source_revision: "bundle-42",
      status_detail: "The recommended reviewer skill is not installed.",
      actions: [disabledInstall],
    },
  ],
  actions: [],
};

describe("RoleProfileCard", () => {
  it("shows observed configuration and run-preparation policy", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const markup = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <RoleProfileCard projectId="project-1" role={role} />
      </QueryClientProvider>,
    );

    expect(markup).toContain("Observed project configuration");
    expect(markup).toContain("Assigned Hermes profile");
    expect(markup).toContain("Run-preparation policy");
    expect(markup).toContain("not a live view of profile memory or provider settings");
    expect(markup).toContain("Pinned source");
  });

  it("disables conflicting profiles and exposes every disabled reason accessibly", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const markup = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <RoleProfileCard projectId="project-1" role={role} />
      </QueryClientProvider>,
    );

    expect(markup).toMatch(/<option[^>]*disabled=""[^>]*>Research lead profile \(local\) \(unavailable\)<\/option>/);
    expect(markup).toMatch(/<option[^>]*>Independent reviewer \(local\) \(current\)<\/option>/);
    expect(markup).not.toMatch(/<option[^>]*disabled=""[^>]*>Independent reviewer/);
    expect(markup).toMatch(/<button[^>]*disabled=""[^>]*aria-describedby="outside_reviewer-profile-save-reason"/);
    expect(markup).toContain("This profile is already assigned.");
    expect(markup).toContain("Already assigned to an authoring role; reviewer memory must remain independent.");
    expect(markup).toContain(
      "aria-describedby=\"outside_reviewer-current-profile-reason outside_reviewer-profile-option-reasons\"",
    );
    expect(markup).toContain("Select an available Hermes profile before installing this skill.");
    expect(markup).toContain("aria-describedby=\"outside_reviewer-stat-paper-reviewer-install-reason\"");
  });

  it("uses the selected option's binding state to explain save eligibility", () => {
    expect(profileSaveExplanation(role, role.profile_options[0], false)).toBe(
      "This profile is already assigned.",
    );
    expect(profileSaveExplanation(role, role.profile_options[1], false)).toContain("reviewer memory must remain independent");
  });
});

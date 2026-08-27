// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type {
  AssetStatusView,
  RoleDefinitionView,
  RoleHealthReportView,
  RoleSkillAssignmentsView,
} from "../api/types";
import {
  conflictingAsset,
  extractProvisionConflict,
  overwriteProvisionRequest,
  RoleConfigurationPage,
} from "./RoleConfigurationPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getRoleDefinition: vi.fn(),
      getRoleHealth: vi.fn(),
      getRoleSkillAssignments: vi.fn(),
      updateRoleSkillAssignments: vi.fn(),
      provisionRole: vi.fn(),
    },
  };
});

function asset(overrides: Partial<AssetStatusView>): AssetStatusView {
  return {
    asset_type: "soul",
    file_name: "SOUL.md",
    status: "present",
    expected_sha256: "e".repeat(64),
    detail: "Matches the reference.",
    ...overrides,
  };
}

function definition(overrides: Partial<RoleDefinitionView> = {}): RoleDefinitionView {
  return {
    role_id: "research_lead",
    display_name: "Research lead",
    profile_version: "3.1",
    default_profile: "research-lead",
    applicable_phases: ["P1", "P2", "P3", "P4"],
    soul_text: "You are the research lead.\nSecond line of the SOUL.",
    soul_sha256: "a".repeat(64),
    base_configuration: {
      file_name: "research_lead.yaml",
      format: "yaml",
      content_sha256: "b".repeat(64),
    },
    recommended_skills: [
      {
        skill_id: "lit-review-orchestrator",
        name: "Literature review orchestrator",
        description: "Plans and tracks literature review work.",
        source: "model-forge-bundle",
        recommended_version: "pinned",
      },
    ],
    custom_skills: [
      {
        skill_id: "lab-notes",
        name: "Lab notes helper",
        description: "Formats team lab notes.",
        source: "team-vault",
      },
    ],
    library_guidance: {
      file_name: "library_guidance.md",
      content_sha256: "c".repeat(64),
    },
    ...overrides,
  };
}

function healthReport(overrides: Partial<RoleHealthReportView> = {}): RoleHealthReportView {
  return {
    role_id: "research_lead",
    display_name: "Research lead",
    profile_available: true,
    profile_name: "research-lead",
    overall_status: "customized",
    soul_status: asset({
      status: "customized",
      expected_sha256: "e".repeat(64),
      actual_sha256: "f".repeat(64),
      detail: "SOUL.md has been customized locally.",
    }),
    configuration_status: asset({
      asset_type: "base_configuration",
      file_name: "research_lead.yaml",
    }),
    guidance_status: asset({ asset_type: "library_guidance", file_name: "library_guidance.md" }),
    skill_statuses: [
      asset({
        asset_type: "skill",
        file_name: "lit-review-orchestrator",
        detail: "Installed at the recommended version.",
      }),
    ],
    conditions: ["soul_customized"],
    detail: "SOUL.md differs from the configuration-managed reference.",
    ...overrides,
  };
}

function assignmentsView(
  overrides: Partial<RoleSkillAssignmentsView> = {},
): RoleSkillAssignmentsView {
  return {
    role_id: "research_lead",
    phases: ["P1", "P2", "P3", "P4", "P5"].map((phase) => ({
      phase,
      source: phase === "P5" ? ("assigned" as const) : ("default" as const),
      skills: ["stat-paper-writing", "mf-contribution-boundary"],
    })),
    available_skills: [
      {
        skill_id: "stat-paper-writing",
        content_sha256: "1".repeat(64),
        roles: ["research_lead"],
        bundled: true,
      },
      {
        skill_id: "mf-contribution-boundary",
        content_sha256: "2".repeat(64),
        roles: ["research_lead"],
        bundled: true,
      },
      {
        skill_id: "stat-paper-reviewer",
        content_sha256: "3".repeat(64),
        roles: ["outside_reviewer"],
        bundled: true,
      },
    ],
    matrix_sha256: "4".repeat(64),
    ...overrides,
  };
}

function renderPage(queryClient: QueryClient, roleId = "research_lead") {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/configuration/roles/${roleId}`]}>
        <Routes>
          <Route path="/configuration/roles/:roleId" element={<RoleConfigurationPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RoleConfigurationPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(api.getRoleSkillAssignments).mockResolvedValue(assignmentsView());
    vi.mocked(api.updateRoleSkillAssignments).mockResolvedValue(assignmentsView());
  });

  afterEach(() => {
    cleanup();
  });

  it("renders SOUL, base configuration, skills, library guidance, and the health report", async () => {
    vi.mocked(api.getRoleDefinition).mockResolvedValue(definition());
    vi.mocked(api.getRoleHealth).mockResolvedValue(healthReport());
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage(queryClient);

    // SOUL read-only panel
    expect(await screen.findByText("SOUL definition")).toBeInTheDocument();
    expect(screen.getByText(/You are the research lead\./)).toBeInTheDocument();
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
    // Base configuration
    expect(screen.getAllByText("research_lead.yaml").length).toBeGreaterThan(0);
    expect(screen.getByText("b".repeat(64))).toBeInTheDocument();
    // Recommended + custom skills
    expect(screen.getByText("Literature review orchestrator")).toBeInTheDocument();
    expect(screen.getByText("model-forge-bundle")).toBeInTheDocument();
    expect(screen.getByText("pinned")).toBeInTheDocument();
    expect(screen.getByText("Lab notes helper")).toBeInTheDocument();
    expect(screen.getByText("team-vault")).toBeInTheDocument();
    expect(screen.getAllByText("present").length).toBeGreaterThan(0);
    // Library guidance
    expect(screen.getAllByText("library_guidance.md").length).toBeGreaterThan(0);
    expect(screen.getByText("c".repeat(64))).toBeInTheDocument();
    // Health report with expected vs actual digests for the customized asset
    expect(screen.getByText("Role health report")).toBeInTheDocument();
    expect(screen.getByText("Expected digest")).toBeInTheDocument();
    expect(screen.getByText("Actual digest")).toBeInTheDocument();
    expect(screen.getByText("e".repeat(64))).toBeInTheDocument();
    expect(screen.getByText("f".repeat(64))).toBeInTheDocument();
    // Provision action
    expect(screen.getByRole("button", { name: "Provision role definition" })).toBeInTheDocument();
  });

  it("renders the loading state while queries are pending", () => {
    vi.mocked(api.getRoleDefinition).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.getRoleHealth).mockReturnValue(new Promise(() => {}));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage(queryClient);

    expect(screen.getByText("Loading role definition...")).toBeInTheDocument();
  });

  it("renders NotFoundPage for an unknown role", async () => {
    vi.mocked(api.getRoleDefinition).mockRejectedValueOnce(
      new ApiError("Role 'unknown' does not exist.", 404, "TARGET_NOT_FOUND"),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage(queryClient, "unknown");

    expect(await screen.findByText("This research view does not exist")).toBeInTheDocument();
  });

  it("renders the error state when the health query fails", async () => {
    vi.mocked(api.getRoleDefinition).mockResolvedValue(definition());
    vi.mocked(api.getRoleHealth).mockRejectedValueOnce(new Error("health backend down"));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage(queryClient);

    expect(await screen.findByText("Role health report is unavailable")).toBeInTheDocument();
    expect(screen.getByText("health backend down")).toBeInTheDocument();
  });
});

describe("provision conflict helpers", () => {
  it("recognizes only 409 CUSTOMIZATION_CONFLICT errors", () => {
    expect(extractProvisionConflict(new Error("plain failure"))).toBeUndefined();
    expect(extractProvisionConflict(new ApiError("x", 500, "CUSTOMIZATION_CONFLICT"))).toBeUndefined();
    expect(extractProvisionConflict(new ApiError("x", 409, "ROLE_PROVISIONING_FAILED"))).toBeUndefined();
    const conflict = new ApiError(
      "customized",
      409,
      "CUSTOMIZATION_CONFLICT",
      undefined,
      ["research_lead", "soul", "SOUL.md"],
    );
    expect(extractProvisionConflict(conflict)).toBe(conflict);
  });

  it("matches the conflict to the customized asset with both digests", () => {
    const health = healthReport();
    const conflict = new ApiError(
      "message",
      409,
      "CUSTOMIZATION_CONFLICT",
      undefined,
      ["research_lead", "soul", "SOUL.md"],
    );

    const matched = conflictingAsset(health, conflict);
    expect(matched?.asset_type).toBe("soul");
    expect(matched?.file_name).toBe("SOUL.md");
    expect(matched?.expected_sha256).toBe("e".repeat(64));
    expect(matched?.actual_sha256).toBe("f".repeat(64));

    // Skill-directory conflicts carry [role_id, profile_name] and fall back
    // to the customized skill entry.
    const skillHealth = healthReport({
      skill_statuses: [
        asset({
          asset_type: "skill",
          file_name: "stat-paper-reviewer",
          status: "customized",
          actual_sha256: "9".repeat(64),
        }),
      ],
    });
    const skillConflict = new ApiError(
      "message",
      409,
      "CUSTOMIZATION_CONFLICT",
      undefined,
      ["research_lead", "research-lead"],
    );
    expect(conflictingAsset(skillHealth, skillConflict)?.file_name).toBe("stat-paper-reviewer");
  });

  it("builds the overwrite request with force flags scoped to the conflict type", () => {
    const soulConflict = new ApiError(
      "message",
      409,
      "CUSTOMIZATION_CONFLICT",
      undefined,
      ["research_lead", "soul", "SOUL.md"],
    );
    expect(overwriteProvisionRequest(conflictingAsset(healthReport(), soulConflict), soulConflict))
      .toEqual({ install_skills: true, force_overwrite_assets: true, force_overwrite_skills: false });

    const skillDirConflict = new ApiError(
      "message",
      409,
      "CUSTOMIZATION_CONFLICT",
      undefined,
      ["research_lead", "research-lead"],
    );
    expect(overwriteProvisionRequest(undefined, skillDirConflict))
      .toEqual({ install_skills: true, force_overwrite_assets: true, force_overwrite_skills: true });

    const skillAssetConflict = new ApiError(
      "message",
      409,
      "CUSTOMIZATION_CONFLICT",
      undefined,
      ["research_lead", "skill", "stat-paper-reviewer"],
    );
    expect(overwriteProvisionRequest(undefined, skillAssetConflict))
      .toEqual({ install_skills: true, force_overwrite_assets: true, force_overwrite_skills: true });
  });
});

describe("SkillAssignmentsPanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(api.getRoleDefinition).mockResolvedValue(definition());
    vi.mocked(api.getRoleHealth).mockResolvedValue(healthReport());
    vi.mocked(api.getRoleSkillAssignments).mockResolvedValue(assignmentsView());
    vi.mocked(api.updateRoleSkillAssignments).mockResolvedValue(assignmentsView());
  });

  afterEach(() => {
    cleanup();
  });

  it("renders the skill-by-phase matrix with sources and the matrix digest", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage(queryClient);

    expect(await screen.findByText("Skills per phase")).toBeInTheDocument();
    // Phase columns with source pills (first phase awaited so the query has resolved)
    expect(await screen.findByText("P1")).toBeInTheDocument();
    for (const phase of ["P2", "P3", "P4", "P5"]) {
      expect(screen.getByText(phase)).toBeInTheDocument();
    }
    expect(screen.getAllByText("default")).toHaveLength(4);
    expect(screen.getByText("assigned")).toBeInTheDocument();
    // Skill rows with digest previews
    expect(screen.getByText("stat-paper-writing")).toBeInTheDocument();
    expect(screen.getByText("mf-contribution-boundary")).toBeInTheDocument();
    expect(screen.getByText("stat-paper-reviewer")).toBeInTheDocument();
    expect(screen.getByText("1".repeat(12))).toBeInTheDocument();
    // Matrix digest + seal note
    expect(screen.getByText("Assignment matrix digest")).toBeInTheDocument();
    expect(screen.getByText("4".repeat(64))).toBeInTheDocument();
    expect(screen.getByText(/next run seal/)).toBeInTheDocument();
    // Checked state follows the effective lists
    const reviewerInP1 = screen.getByRole("checkbox", { name: "stat-paper-reviewer in P1" });
    expect(reviewerInP1).not.toBeChecked();
    const writingInP3 = screen.getByRole("checkbox", { name: "stat-paper-writing in P3" });
    expect(writingInP3).toBeChecked();
  });

  it("toggling a cell saves the recomputed phase skill list", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage(queryClient);

    const cell = await screen.findByRole("checkbox", { name: "stat-paper-reviewer in P1" });
    await user.click(cell);

    expect(api.updateRoleSkillAssignments).toHaveBeenCalledWith("research_lead", "P1", {
      skills: ["stat-paper-writing", "mf-contribution-boundary", "stat-paper-reviewer"],
    });
  });

  it("unchecking a cell removes only that skill", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage(queryClient);

    const cell = await screen.findByRole("checkbox", { name: "mf-contribution-boundary in P2" });
    await user.click(cell);

    expect(api.updateRoleSkillAssignments).toHaveBeenCalledWith("research_lead", "P2", {
      skills: ["stat-paper-writing"],
    });
  });

  it("reset restores the catalog default for an assigned phase", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage(queryClient);

    // Only the assigned column (P5) shows a Reset button
    const reset = await screen.findByRole("button", { name: "Reset" });
    await user.click(reset);

    expect(api.updateRoleSkillAssignments).toHaveBeenCalledWith("research_lead", "P5", {
      skills: null,
    });
  });

  it("surfaces a save failure without crashing the page", async () => {
    const user = userEvent.setup();
    vi.mocked(api.updateRoleSkillAssignments).mockRejectedValue(new Error("network down"));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage(queryClient);

    const cell = await screen.findByRole("checkbox", { name: "stat-paper-reviewer in P1" });
    await user.click(cell);

    expect(await screen.findByText(/The assignment was not saved/)).toBeInTheDocument();
  });

  it("shows an inline error when the assignments query fails", async () => {
    vi.mocked(api.getRoleSkillAssignments).mockRejectedValue(new Error("offline"));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage(queryClient);

    expect(await screen.findByText(/Skill assignments are unavailable/)).toBeInTheDocument();
  });
});

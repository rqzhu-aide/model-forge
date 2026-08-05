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
} from "../api/types";
import { RoleConfigurationPage } from "./RoleConfigurationPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getRoleDefinition: vi.fn(),
      getRoleHealth: vi.fn(),
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
    soul_text: "You are the research lead.",
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
        source: "method-hub-bundle",
        recommended_version: "pinned",
      },
    ],
    custom_skills: [],
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

let queryClient: QueryClient;

function mockQueries(healthOverrides: Partial<RoleHealthReportView> = {}): void {
  vi.mocked(api.getRoleDefinition).mockResolvedValue(definition());
  vi.mocked(api.getRoleHealth).mockResolvedValue(healthReport(healthOverrides));
}

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/configuration/roles/research_lead"]}>
        <Routes>
          <Route path="/configuration/roles/:roleId" element={<RoleConfigurationPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

afterEach(() => {
  cleanup();
});

describe("RoleConfigurationPage provision flow", () => {
  it("provisions on demand and shows assets written and skills installed", async () => {
    mockQueries();
    const provision = vi.mocked(api.provisionRole).mockResolvedValue({
      role_id: "research_lead",
      profile_name: "research-lead",
      assets_written: ["SOUL.md", "research_lead.yaml", "library_guidance.md"],
      skills_installed: ["lit-review-orchestrator"],
      rolled_back: false,
    });
    const user = userEvent.setup();

    renderPage();
    await user.click(await screen.findByRole("button", { name: "Provision role definition" }));

    expect(provision).toHaveBeenCalledTimes(1);
    expect(provision).toHaveBeenCalledWith("research_lead", {
      install_skills: true,
      force_overwrite_assets: false,
      force_overwrite_skills: false,
    });
    expect(await screen.findByText("Role definition provisioned")).toBeInTheDocument();
    const outcome = document.querySelector(".provision-outcome-message");
    expect(outcome).not.toBeNull();
    expect(outcome?.textContent).toContain("SOUL.md, research_lead.yaml, library_guidance.md");
    expect(outcome?.textContent).toContain("lit-review-orchestrator");
  });

  it("surfaces a 409 customization conflict without re-issuing before confirmation", async () => {
    mockQueries();
    const provision = vi.mocked(api.provisionRole).mockRejectedValueOnce(
      new ApiError(
        "The SOUL.md file 'SOUL.md' in profile 'research-lead' has been customized and differs from the configuration-managed reference.",
        409,
        "CUSTOMIZATION_CONFLICT",
        "Resolve the conflict explicitly: keep the customized file or force-overwrite it with the reference.",
        ["research_lead", "soul", "SOUL.md"],
      ),
    );
    const user = userEvent.setup();

    renderPage();
    await user.click(await screen.findByRole("button", { name: "Provision role definition" }));

    // The initial attempt ran exactly once and the conflict is visible.
    expect(await screen.findByText("Customization conflict")).toBeInTheDocument();
    expect(provision).toHaveBeenCalledTimes(1);
    const conflict = document.querySelector(".provision-conflict");
    expect(conflict).not.toBeNull();
    expect(conflict?.textContent).toContain("has been customized and differs");
    expect(conflict?.textContent).toContain("research_lead / soul / SOUL.md");
    // Expected vs actual digests come from the health report's customized entry.
    expect(conflict?.textContent).toContain("e".repeat(64));
    expect(conflict?.textContent).toContain("f".repeat(64));
    expect(screen.getByRole("button", { name: "Overwrite customization" })).toBeInTheDocument();
    // Rendering the conflict must not re-issue the provision command.
    expect(provision).toHaveBeenCalledTimes(1);
  });

  it("re-issues with force flags only after the explicit overwrite confirmation", async () => {
    mockQueries();
    const provision = vi.mocked(api.provisionRole)
      .mockRejectedValueOnce(
        new ApiError(
          "The SOUL.md file 'SOUL.md' in profile 'research-lead' has been customized and differs from the configuration-managed reference.",
          409,
          "CUSTOMIZATION_CONFLICT",
          "Resolve the conflict explicitly.",
          ["research_lead", "soul", "SOUL.md"],
        ),
      )
      .mockResolvedValueOnce({
        role_id: "research_lead",
        profile_name: "research-lead",
        assets_written: ["SOUL.md"],
        skills_installed: [],
        rolled_back: false,
      });
    const user = userEvent.setup();

    renderPage();
    await user.click(await screen.findByRole("button", { name: "Provision role definition" }));
    expect(await screen.findByText("Customization conflict")).toBeInTheDocument();
    expect(provision).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Overwrite customization" }));

    expect(await screen.findByText("Role definition provisioned")).toBeInTheDocument();
    expect(provision).toHaveBeenCalledTimes(2);
    expect(provision).toHaveBeenNthCalledWith(2, "research_lead", {
      install_skills: true,
      force_overwrite_assets: true,
      force_overwrite_skills: false,
    });
    const outcome = document.querySelector(".provision-outcome-message");
    expect(outcome).not.toBeNull();
    expect(outcome?.textContent).toContain("SOUL.md");
  });

  it("forces skill overwrite when the conflict is a customized skill", async () => {
    mockQueries({
      skill_statuses: [
        asset({
          asset_type: "skill",
          file_name: "lit-review-orchestrator",
          status: "customized",
          expected_sha256: "e".repeat(64),
          actual_sha256: "f".repeat(64),
          detail: "Customized skill directory.",
        }),
      ],
    });
    const provision = vi.mocked(api.provisionRole)
      .mockRejectedValueOnce(
        new ApiError(
          "A recommended skill for role 'research_lead' conflicts with a customized local skill directory.",
          409,
          "CUSTOMIZATION_CONFLICT",
          "Resolve the local skill directory, refresh, and provision again, or force-overwrite the skill.",
          ["research_lead", "research-lead"],
        ),
      )
      .mockResolvedValueOnce({
        role_id: "research_lead",
        profile_name: "research-lead",
        assets_written: [],
        skills_installed: ["lit-review-orchestrator"],
        rolled_back: false,
      });
    const user = userEvent.setup();

    renderPage();
    await user.click(await screen.findByRole("button", { name: "Provision role definition" }));

    const conflict = await screen.findByText("Customization conflict");
    expect(conflict).toBeInTheDocument();
    const conflictBox = document.querySelector(".provision-conflict");
    expect(conflictBox?.textContent).toContain("lit-review-orchestrator");
    expect(conflictBox?.textContent).toContain("f".repeat(64));

    await user.click(screen.getByRole("button", { name: "Overwrite customization" }));

    expect(provision).toHaveBeenCalledTimes(2);
    expect(provision).toHaveBeenNthCalledWith(2, "research_lead", {
      install_skills: true,
      force_overwrite_assets: true,
      force_overwrite_skills: true,
    });
  });

  it("renders ErrorState when provisioning fails for another reason", async () => {
    mockQueries();
    vi.mocked(api.provisionRole).mockRejectedValue(new Error("hermes root missing"));
    const user = userEvent.setup();

    renderPage();
    await user.click(await screen.findByRole("button", { name: "Provision role definition" }));

    expect(await screen.findByText("Provisioning failed")).toBeInTheDocument();
    expect(screen.getByText("hermes root missing")).toBeInTheDocument();
  });

  it("renders ErrorState when the health query fails", async () => {
    vi.mocked(api.getRoleDefinition).mockResolvedValue(definition());
    vi.mocked(api.getRoleHealth).mockRejectedValue(new Error("health backend down"));

    renderPage();

    expect(await screen.findByText("Role health report is unavailable")).toBeInTheDocument();
    expect(screen.getByText("health backend down")).toBeInTheDocument();
  });
});

// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type {
  AssetStatusView,
  ConfigurationHealthView,
  RoleHealthReportView,
} from "../api/types";
import { ConfigurationPage, RoleConfigurationCard } from "./ConfigurationPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getConfigurationHealth: vi.fn(),
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

function roleReport(overrides: Partial<RoleHealthReportView> = {}): RoleHealthReportView {
  return {
    role_id: "research_lead",
    display_name: "Research lead",
    profile_available: true,
    profile_name: "research-lead",
    overall_status: "healthy",
    soul_status: asset({ asset_type: "soul", file_name: "SOUL.md" }),
    configuration_status: asset({
      asset_type: "base_configuration",
      file_name: "research_lead.yaml",
    }),
    guidance_status: asset({ asset_type: "library_guidance", file_name: "library_guidance.md" }),
    skill_statuses: [],
    conditions: [],
    detail: "All assets match the reference.",
    ...overrides,
  };
}

function healthView(roles: RoleHealthReportView[]): ConfigurationHealthView {
  return {
    hermes_root: "/tmp/hermes",
    hermes_available: true,
    roles,
    overall_status: "healthy",
    conditions: [],
  };
}

function renderList(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ConfigurationPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ConfigurationPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders all four roles with health badges and detail links", async () => {
    vi.mocked(api.getConfigurationHealth).mockResolvedValue(healthView([
      roleReport({ role_id: "research_lead", display_name: "Research lead", overall_status: "healthy" }),
      roleReport({ role_id: "theorist", display_name: "Theorist", overall_status: "customized" }),
      roleReport({ role_id: "data_analyst", display_name: "Data analyst", overall_status: "incomplete" }),
      roleReport({ role_id: "outside_reviewer", display_name: "Outside reviewer", overall_status: "unavailable" }),
    ]));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = renderList(queryClient);

    expect(await screen.findByText("Research lead")).toBeInTheDocument();
    expect(screen.getByText("Theorist")).toBeInTheDocument();
    expect(screen.getByText("Data analyst")).toBeInTheDocument();
    expect(screen.getByText("Outside reviewer")).toBeInTheDocument();
    expect(screen.getAllByText("healthy").length).toBeGreaterThan(0);
    expect(screen.getAllByText("customized").length).toBeGreaterThan(0);
    expect(screen.getAllByText("incomplete").length).toBeGreaterThan(0);
    expect(screen.getAllByText("unavailable").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Research lead" })).toHaveAttribute(
      "href",
      "/configuration/roles/research_lead",
    );
    expect(screen.getByRole("link", { name: "Theorist" })).toHaveAttribute(
      "href",
      "/configuration/roles/theorist",
    );
    expect(screen.getByRole("link", { name: "Data analyst" })).toHaveAttribute(
      "href",
      "/configuration/roles/data_analyst",
    );
    expect(screen.getByRole("link", { name: "Outside reviewer" })).toHaveAttribute(
      "href",
      "/configuration/roles/outside_reviewer",
    );
    expect(container.querySelector('[data-tone="positive"]')).not.toBeNull();
    expect(container.querySelector('[data-tone="warning"]')).not.toBeNull();
    expect(container.querySelector('[data-tone="danger"]')).not.toBeNull();
  });

  it("renders the empty state when no roles are reported", async () => {
    vi.mocked(api.getConfigurationHealth).mockResolvedValue(healthView([]));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderList(queryClient);

    expect(await screen.findByText("No role definitions are installed")).toBeInTheDocument();
  });

  it("renders the loading state while the health query is pending", () => {
    vi.mocked(api.getConfigurationHealth).mockReturnValue(new Promise(() => {}));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderList(queryClient);

    expect(screen.getByText("Loading role configuration...")).toBeInTheDocument();
  });

  it("renders the error state when the health query fails", async () => {
    vi.mocked(api.getConfigurationHealth).mockRejectedValueOnce(new Error("backend unavailable"));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderList(queryClient);

    expect(await screen.findByText("Role configuration is unavailable")).toBeInTheDocument();
    expect(screen.getByText("backend unavailable")).toBeInTheDocument();
  });
});

describe("RoleConfigurationCard", () => {
  it("links the card to the role detail page", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <RoleConfigurationCard role={roleReport()} />
      </MemoryRouter>,
    );
    expect(markup).toContain('href="/configuration/roles/research_lead"');
    expect(markup).toContain("Inspect role definition");
    expect(markup).toContain("All assets match the reference.");
  });
});

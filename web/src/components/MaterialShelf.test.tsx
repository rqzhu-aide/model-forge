// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AttachResearcherMaterialRequest } from "../api/types";
import { MaterialShelf } from "./MaterialShelf";

const listMock = vi.fn<(projectId: string) => Promise<unknown>>();
const attachMock =
  vi.fn<(projectId: string, input: AttachResearcherMaterialRequest) => Promise<unknown>>();
const deleteMock = vi.fn<(projectId: string, materialId: string) => Promise<unknown>>();

vi.mock("../api/client", () => ({
  api: {
    listMaterials: (projectId: string) => listMock(projectId),
    attachMaterial: (projectId: string, input: AttachResearcherMaterialRequest) =>
      attachMock(projectId, input),
    deleteMaterial: (projectId: string, materialId: string) =>
      deleteMock(projectId, materialId),
  },
}));

function renderShelf() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MaterialShelf projectId="project-1" />
    </QueryClientProvider>,
  );
}

describe("MaterialShelf (ADR-019 project shelf)", () => {
  beforeEach(() => {
    listMock.mockReset();
    listMock.mockResolvedValue([]);
    attachMock.mockReset();
    attachMock.mockResolvedValue({});
    deleteMock.mockReset();
    deleteMock.mockResolvedValue(undefined);
  });
  afterEach(cleanup);

  it("attaches copied text with a name", async () => {
    const user = userEvent.setup();
    renderShelf();
    await user.type(screen.getByPlaceholderText(/partial-fit\.py/), "my notes");
    await user.type(
      screen.getByPlaceholderText(/Paste the material here/),
      "def partial_fit(x): return x",
    );
    await user.click(screen.getByRole("button", { name: "Attach to the project" }));
    await waitFor(() => expect(attachMock).toHaveBeenCalledTimes(1));
    expect(attachMock.mock.calls[0]?.[1]).toEqual({
      name: "my notes",
      kind: "copy",
      media_type: "text/markdown",
      content: "def partial_fit(x): return x",
    });
  });

  it("attaches an external link and rejects malformed URLs", async () => {
    const user = userEvent.setup();
    renderShelf();
    await user.click(screen.getByRole("radio", { name: /External link/ }));
    await user.type(screen.getByPlaceholderText(/partial-fit\.py/), "big data");
    await user.type(screen.getByPlaceholderText("https://..."), "not-a-url");
    expect(screen.getByRole("button", { name: "Attach to the project" })).toBeDisabled();
    await user.clear(screen.getByPlaceholderText("https://..."));
    await user.type(
      screen.getByPlaceholderText("https://..."),
      "https://data.example.org/archive.tar",
    );
    await user.click(screen.getByRole("button", { name: "Attach to the project" }));
    await waitFor(() => expect(attachMock).toHaveBeenCalledTimes(1));
    expect(attachMock.mock.calls[0]?.[1]).toEqual({
      name: "big data",
      kind: "link",
      external_url: "https://data.example.org/archive.tar",
    });
  });

  it("lists shelf items with kind badges and removes them", async () => {
    listMock.mockResolvedValue([
      {
        material_id: "material.abc",
        name: "partial_fit.py",
        kind: "copy",
        media_type: "text/plain",
        size_bytes: 30,
        created_at: "2026-08-28T10:00:00Z",
      },
      {
        material_id: "material.def",
        name: "archive",
        kind: "link",
        media_type: "text/markdown",
        size_bytes: 40,
        external_url: "https://data.example.org/archive.tar",
        created_at: "2026-08-28T11:00:00Z",
      },
    ]);
    const user = userEvent.setup();
    renderShelf();
    expect(await screen.findByText("partial_fit.py")).toBeInTheDocument();
    expect(screen.getByText("copied in")).toBeInTheDocument();
    expect(screen.getByText("external link")).toBeInTheDocument();
    expect(screen.getByText(/data\.example\.org\/archive\.tar/)).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Remove" })[0]!);
    await waitFor(() =>
      expect(deleteMock).toHaveBeenCalledWith("project-1", "material.abc"),
    );
  });
});

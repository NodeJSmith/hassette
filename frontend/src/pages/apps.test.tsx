import { describe, expect, it, vi, beforeEach } from "vitest";
import { signal } from "@preact/signals";
import { AppsPage } from "./apps";
import { renderWithAppState } from "../test/render-helpers";
import { createManifestList, createManifest } from "../test/factories";

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

// Stub heavy child components that have their own tests
vi.mock("../components/apps/manifest-list", () => ({
  ManifestList: ({ manifests }: { manifests: unknown; filter: unknown }) =>
    <div data-testid="manifest-list" data-count={Array.isArray(manifests) ? (manifests as unknown[]).length : 0} />,
  EXPANDED_KEY: "expanded",
}));

vi.mock("../components/apps/status-filter", () => ({
  StatusFilter: () =>
    <div data-testid="status-filter" />,
}));

vi.mock("../hooks/use-api", () => ({
  useApi: vi.fn(),
}));

const useApiMod = await import("../hooks/use-api");
const useApi = useApiMod.useApi as unknown as ReturnType<typeof vi.fn>;

function fakeApiResult<T>(data: T | null, loading = false, error: string | null = null) {
  return {
    data: signal(data),
    loading: signal(loading),
    error: signal(error),
    refetch: vi.fn(),
  };
}

describe("AppsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows spinner while loading", () => {
    useApi.mockReturnValue(fakeApiResult(null, true));
    const { getByTestId } = renderWithAppState(<AppsPage />);
    expect(getByTestId("spinner")).toBeDefined();
  });

  it("renders 'App Management' heading when data loads", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList()));
    const { getByRole } = renderWithAppState(<AppsPage />);
    expect(getByRole("heading", { name: /app management/i })).toBeDefined();
  });

  it("renders ManifestList component", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList()));
    const { getByTestId } = renderWithAppState(<AppsPage />);
    expect(getByTestId("manifest-list")).toBeDefined();
  });

  it("renders StatusFilter component", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList()));
    const { getByTestId } = renderWithAppState(<AppsPage />);
    expect(getByTestId("status-filter")).toBeDefined();
  });

  it("renders error message when fetch fails", () => {
    useApi.mockReturnValue(fakeApiResult(null, false, "Connection refused"));
    const { getByText } = renderWithAppState(<AppsPage />);
    expect(getByText("Connection refused")).toBeDefined();
  });

  it("passes manifests data to ManifestList", () => {
    const manifests = createManifestList({
      manifests: [
        createManifest({ app_key: "app_a", status: "running" }),
        createManifest({ app_key: "app_b", status: "failed" }),
      ],
      total: 2,
    });
    useApi.mockReturnValue(fakeApiResult(manifests));
    const { getByTestId } = renderWithAppState(<AppsPage />);
    // manifest-list stub exposes count via data-count attribute
    expect(getByTestId("manifest-list").getAttribute("data-count")).toBe("2");
  });

  it("renders empty ManifestList when data is null (not loading)", () => {
    useApi.mockReturnValue(fakeApiResult(null, false));
    const { getByTestId } = renderWithAppState(<AppsPage />);
    // ManifestList receives null manifests — renders stub with count 0
    expect(getByTestId("manifest-list")).toBeDefined();
  });
});

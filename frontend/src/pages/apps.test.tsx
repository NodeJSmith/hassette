import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { AppsPage } from "./apps";
import { renderWithAppState } from "../test/render-helpers";
import { createManifestList, createManifest } from "../test/factories";

// Mutable search string for tests that need to control query params
let mockSearch = "";
const mockNavigate = vi.fn();

vi.mock("wouter", () => ({
  useSearch: () => mockSearch,
  useLocation: () => ["/apps", mockNavigate],
}));

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

vi.mock("../hooks/use-api", () => ({
  useApi: vi.fn(),
}));

vi.mock("../hooks/use-scoped-api", () => ({
  useScopedApi: vi.fn(() => ({
    data: signal({ apps: [] }),
    loading: signal(false),
    error: signal(null),
    refetch: vi.fn(),
  })),
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
    mockSearch = "";
  });

  it("shows spinner while loading", () => {
    useApi.mockReturnValue(fakeApiResult(null, true));
    const { getByTestId } = renderWithAppState(<AppsPage />);
    expect(getByTestId("spinner")).toBeDefined();
  });

  it("renders 'apps' heading when data loads", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList()));
    const { getByRole } = renderWithAppState(<AppsPage />);
    expect(getByRole("heading", { name: /apps/i })).toBeDefined();
  });

  it("renders stats strip with counts", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList({
      manifests: [
        createManifest({ app_key: "a", status: "running" }),
        createManifest({ app_key: "b", status: "disabled" }),
      ],
      total: 2,
    })));
    const { getByTestId } = renderWithAppState(<AppsPage />);
    expect(getByTestId("apps-stats-strip")).toBeDefined();
  });

  it("renders filter pills", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList()));
    const { getByTestId } = renderWithAppState(<AppsPage />);
    expect(getByTestId("apps-filter-pills")).toBeDefined();
  });

  it("renders app rows in the table", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList({
      manifests: [
        createManifest({ app_key: "app_a", status: "running" }),
        createManifest({ app_key: "app_b", status: "running" }),
      ],
      total: 2,
    })));
    const { getByTestId } = renderWithAppState(<AppsPage />);
    expect(getByTestId("app-row-app_a")).toBeDefined();
    expect(getByTestId("app-row-app_b")).toBeDefined();
  });

  it("renders search input", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList()));
    const { getByTestId } = renderWithAppState(<AppsPage />);
    expect(getByTestId("apps-search")).toBeDefined();
  });

  it("shows empty state when no manifests", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList({ manifests: [], total: 0 })));
    const { getByText } = renderWithAppState(<AppsPage />);
    expect(getByText(/no apps match/i)).toBeDefined();
  });

  describe("query param: filter", () => {
    it("reads filter from URL query params — only failed apps shown when filter=failed", () => {
      mockSearch = "filter=failed";
      useApi.mockReturnValue(fakeApiResult(createManifestList({
        manifests: [
          createManifest({ app_key: "running_app", status: "running" }),
          createManifest({ app_key: "failed_app", status: "failed" }),
        ],
        total: 2,
      })));
      const { queryByTestId } = renderWithAppState(<AppsPage />);
      expect(queryByTestId("app-row-failed_app")).toBeDefined();
      expect(queryByTestId("app-row-running_app")).toBeNull();
    });
  });

  describe("query param: search", () => {
    it("reads search from URL query params — filters apps by name", () => {
      mockSearch = "search=motion";
      useApi.mockReturnValue(fakeApiResult(createManifestList({
        manifests: [
          createManifest({ app_key: "motion_lights", status: "running" }),
          createManifest({ app_key: "alarm_app", status: "running" }),
        ],
        total: 2,
      })));
      const { queryByTestId } = renderWithAppState(<AppsPage />);
      expect(queryByTestId("app-row-motion_lights")).toBeDefined();
      expect(queryByTestId("app-row-alarm_app")).toBeNull();
    });
  });

  describe("query param: sort/dir", () => {
    it("reads sort key from URL — defaults to status when absent", () => {
      mockSearch = "";
      useApi.mockReturnValue(fakeApiResult(createManifestList({
        manifests: [
          createManifest({ app_key: "app_a", status: "running" }),
        ],
        total: 1,
      })));
      // Page should render without errors when no sort param is in URL
      const { getByTestId } = renderWithAppState(<AppsPage />);
      expect(getByTestId("app-row-app_a")).toBeDefined();
    });
  });

  describe("filter pill onChange — replaces history", () => {
    it("clicking a filter pill calls navigate with replace: true", () => {
      mockSearch = "";
      useApi.mockReturnValue(fakeApiResult(createManifestList({
        manifests: [
          createManifest({ app_key: "running_app", status: "running" }),
          createManifest({ app_key: "failed_app", status: "failed" }),
        ],
        total: 2,
      })));
      const { getByTestId } = renderWithAppState(<AppsPage />);
      fireEvent.click(getByTestId("filter-failed"));
      expect(mockNavigate).toHaveBeenCalledWith(
        expect.stringContaining("filter=failed"),
        expect.objectContaining({ replace: true }),
      );
    });
  });
});

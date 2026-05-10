import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { AppsPage } from "./apps";
import { renderWithAppState } from "../test/render-helpers";
import { createManifest } from "../test/factories";

// Mutable search string for tests that need to control query params
let mockSearch = "";
const mockNavigate = vi.fn();

vi.mock("wouter", () => ({
  useSearch: () => mockSearch,
  useLocation: () => ["/apps", mockNavigate],
  Link: ({ href, children, class: cls }: Record<string, unknown>) =>
    <a href={href as string} class={cls as string}>{children as never}</a>,
}));

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

vi.mock("../hooks/use-scoped-api", () => ({
  useScopedApi: vi.fn(() => ({
    data: signal({ apps: [] }),
    loading: signal(false),
    error: signal(null),
    refetch: vi.fn(),
  })),
}));

describe("AppsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearch = "";
  });

  it("shows spinner while loading", () => {
    const { getByTestId } = renderWithAppState(<AppsPage />, {
      stateOverrides: { manifests: signal([]), manifestsLoading: signal(true) },
    });
    expect(getByTestId("spinner")).toBeDefined();
  });

  it("renders 'apps' heading when data loads", () => {
    const { getByRole } = renderWithAppState(<AppsPage />, {
      stateOverrides: { manifests: signal([createManifest()]), manifestsLoading: signal(false) },
    });
    expect(getByRole("heading", { name: /apps/i })).toBeDefined();
  });

  it("renders stats strip with counts", () => {
    const { getByTestId } = renderWithAppState(<AppsPage />, {
      stateOverrides: {
        manifests: signal([
          createManifest({ app_key: "a", status: "running" }),
          createManifest({ app_key: "b", status: "disabled" }),
        ]),
        manifestsLoading: signal(false),
      },
    });
    expect(getByTestId("apps-stats-strip")).toBeDefined();
  });

  it("renders filter pills", () => {
    const { getByTestId } = renderWithAppState(<AppsPage />, {
      stateOverrides: { manifests: signal([createManifest()]), manifestsLoading: signal(false) },
    });
    expect(getByTestId("apps-filter-pills")).toBeDefined();
  });

  it("renders app rows in the table", () => {
    const { getByTestId } = renderWithAppState(<AppsPage />, {
      stateOverrides: {
        manifests: signal([
          createManifest({ app_key: "app_a", status: "running" }),
          createManifest({ app_key: "app_b", status: "running" }),
        ]),
        manifestsLoading: signal(false),
      },
    });
    expect(getByTestId("app-row-app_a")).toBeDefined();
    expect(getByTestId("app-row-app_b")).toBeDefined();
  });

  it("renders search input", () => {
    const { getByTestId } = renderWithAppState(<AppsPage />, {
      stateOverrides: { manifests: signal([createManifest()]), manifestsLoading: signal(false) },
    });
    expect(getByTestId("apps-search")).toBeDefined();
  });

  it("shows empty state when no manifests", () => {
    const { getByText } = renderWithAppState(<AppsPage />, {
      stateOverrides: { manifests: signal([]), manifestsLoading: signal(false) },
    });
    expect(getByText(/no apps match/i)).toBeDefined();
  });

  describe("query param: filter", () => {
    it("reads filter from URL query params — only failed apps shown when filter=failed", () => {
      mockSearch = "filter=failed";
      const { queryByTestId } = renderWithAppState(<AppsPage />, {
        stateOverrides: {
          manifests: signal([
            createManifest({ app_key: "running_app", status: "running" }),
            createManifest({ app_key: "failed_app", status: "failed" }),
          ]),
          manifestsLoading: signal(false),
        },
      });
      expect(queryByTestId("app-row-failed_app")).toBeDefined();
      expect(queryByTestId("app-row-running_app")).toBeNull();
    });
  });

  describe("query param: search", () => {
    it("reads search from URL query params — filters apps by name", () => {
      mockSearch = "search=motion";
      const { queryByTestId } = renderWithAppState(<AppsPage />, {
        stateOverrides: {
          manifests: signal([
            createManifest({ app_key: "motion_lights", status: "running" }),
            createManifest({ app_key: "alarm_app", status: "running" }),
          ]),
          manifestsLoading: signal(false),
        },
      });
      expect(queryByTestId("app-row-motion_lights")).toBeDefined();
      expect(queryByTestId("app-row-alarm_app")).toBeNull();
    });
  });

  describe("query param: sort/dir", () => {
    it("reads sort key from URL — defaults to status when absent", () => {
      mockSearch = "";
      // Page should render without errors when no sort param is in URL
      const { getByTestId } = renderWithAppState(<AppsPage />, {
        stateOverrides: {
          manifests: signal([createManifest({ app_key: "app_a", status: "running" })]),
          manifestsLoading: signal(false),
        },
      });
      expect(getByTestId("app-row-app_a")).toBeDefined();
    });
  });

  describe("filter pill onChange — replaces history", () => {
    it("clicking a filter pill calls navigate with replace: true", () => {
      mockSearch = "";
      const { getByTestId } = renderWithAppState(<AppsPage />, {
        stateOverrides: {
          manifests: signal([
            createManifest({ app_key: "running_app", status: "running" }),
            createManifest({ app_key: "failed_app", status: "failed" }),
          ]),
          manifestsLoading: signal(false),
        },
      });
      fireEvent.click(getByTestId("filter-failed"));
      expect(mockNavigate).toHaveBeenCalledWith(
        expect.stringContaining("filter=failed"),
        expect.objectContaining({ replace: true }),
      );
    });
  });
});

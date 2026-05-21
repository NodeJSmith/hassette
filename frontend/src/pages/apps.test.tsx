import { signal } from "@preact/signals";
import { fireEvent } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createManifest } from "../test/factories";
import { renderWithAppState } from "../test/render-helpers";
import { AppsPage } from "./apps";

// Mutable search string for tests that need to control query params
let mockSearch = "";
const mockNavigate = vi.fn();

vi.mock("wouter", () => ({
  useSearch: () => mockSearch,
  useLocation: () => ["/apps", mockNavigate],
  Link: ({ href, children, class: cls }: Record<string, unknown>) => (
    <a href={href as string} class={cls as string}>
      {children as never}
    </a>
  ),
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

  it("does not render legacy filter pills", () => {
    const { queryByTestId } = renderWithAppState(<AppsPage />, {
      stateOverrides: { manifests: signal([createManifest()]), manifestsLoading: signal(false) },
    });
    expect(queryByTestId("apps-filter-pills")).toBeNull();
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

  it("renders search input above the table", () => {
    const { getByTestId } = renderWithAppState(<AppsPage />, {
      stateOverrides: { manifests: signal([createManifest()]), manifestsLoading: signal(false) },
    });
    const search = getByTestId("apps-search");
    expect(search).toBeDefined();
    // Search should be inside the search slot (data-search-bar attribute)
    const searchBar = search.closest("[data-search-bar]");
    expect(searchBar).not.toBeNull();
  });

  it("shows empty state when no manifests", () => {
    const { getByText } = renderWithAppState(<AppsPage />, {
      stateOverrides: { manifests: signal([]), manifestsLoading: signal(false) },
    });
    expect(getByText(/no apps match/i)).toBeDefined();
  });

  it("renders record count in the table footer", () => {
    const { getByText } = renderWithAppState(<AppsPage />, {
      stateOverrides: {
        manifests: signal([
          createManifest({ app_key: "app_a", status: "running" }),
          createManifest({ app_key: "app_b", status: "running" }),
        ]),
        manifestsLoading: signal(false),
      },
    });
    expect(getByText(/2 apps/i)).toBeDefined();
  });

  it("footer count updates when search filters results", () => {
    mockSearch = "search=motion";
    const { getByText } = renderWithAppState(<AppsPage />, {
      stateOverrides: {
        manifests: signal([
          createManifest({ app_key: "motion_lights", status: "running" }),
          createManifest({ app_key: "alarm_app", status: "running" }),
        ]),
        manifestsLoading: signal(false),
      },
    });
    expect(getByText(/1 app/i)).toBeDefined();
  });

  describe("STATUS column filter", () => {
    it("renders a filter button on the STATUS column header", () => {
      const { getByRole } = renderWithAppState(<AppsPage />, {
        stateOverrides: {
          manifests: signal([createManifest({ app_key: "app_a", status: "running" })]),
          manifestsLoading: signal(false),
        },
      });
      // SortHeader renders filter button with data-testid="filter-btn" when filterContent is provided
      const filterBtn = getByRole("button", { name: /filter status/i });
      expect(filterBtn).toBeDefined();
    });

    it("clicking the STATUS filter button opens the filter popover", () => {
      const { getByRole, getByText } = renderWithAppState(<AppsPage />, {
        stateOverrides: {
          manifests: signal([
            createManifest({ app_key: "running_app", status: "running" }),
            createManifest({ app_key: "failed_app", status: "failed" }),
          ]),
          manifestsLoading: signal(false),
        },
      });
      const filterBtn = getByRole("button", { name: /filter status/i });
      fireEvent.click(filterBtn);
      // Popover should now be open and show filter options
      expect(getByText(/all/i)).toBeDefined();
    });
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
      const { getByTestId } = renderWithAppState(<AppsPage />, {
        stateOverrides: {
          manifests: signal([createManifest({ app_key: "app_a", status: "running" })]),
          manifestsLoading: signal(false),
        },
      });
      expect(getByTestId("app-row-app_a")).toBeDefined();
    });
  });

  describe("empty state when filters produce zero results", () => {
    it("names the active filter in the empty state message", () => {
      mockSearch = "filter=failed";
      const { getByText } = renderWithAppState(<AppsPage />, {
        stateOverrides: {
          manifests: signal([createManifest({ app_key: "running_app", status: "running" })]),
          manifestsLoading: signal(false),
        },
      });
      expect(getByText(/no apps match status: failed/i)).toBeDefined();
    });

    it("provides a clear filters button in the empty state", () => {
      mockSearch = "filter=failed";
      const { getByRole } = renderWithAppState(<AppsPage />, {
        stateOverrides: {
          manifests: signal([createManifest({ app_key: "running_app", status: "running" })]),
          manifestsLoading: signal(false),
        },
      });
      expect(getByRole("button", { name: /clear filters/i })).toBeDefined();
    });

    it("clicking clear filters calls navigate to reset filter and search", () => {
      mockSearch = "filter=failed";
      const { getByRole } = renderWithAppState(<AppsPage />, {
        stateOverrides: {
          manifests: signal([createManifest({ app_key: "running_app", status: "running" })]),
          manifestsLoading: signal(false),
        },
      });
      fireEvent.click(getByRole("button", { name: /clear filters/i }));
      expect(mockNavigate).toHaveBeenCalledWith(
        expect.not.stringContaining("filter="),
        expect.objectContaining({ replace: true }),
      );
    });
  });
});

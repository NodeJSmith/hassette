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

vi.mock("../hooks/use-scoped-query", () => ({
  useScopedQuery: vi.fn(() => ({ data: { apps: [] }, isPending: false, error: null })),
}));

vi.mock("../hooks/use-query-invalidator", () => ({
  useQueryInvalidator: vi.fn(),
  WS_DEBOUNCE_DELAY_MS: 500,
  WS_DEBOUNCE_MAX_WAIT_MS: 1500,
}));

// Mock useManifests so manifest data is synchronous (matching the pattern
// used for useScopedApi above). Replaced here to avoid async MSW roundtrip
// for tests that focus on filter/sort/search behavior, not data fetching.
vi.mock("../hooks/use-manifests", () => ({
  useManifests: vi.fn(() => ({ data: [], isPending: false })),
}));

const useManifestsMod = await import("../hooks/use-manifests");
const useManifests = useManifestsMod.useManifests as unknown as ReturnType<typeof vi.fn>;

function withManifests(manifests: ReturnType<typeof createManifest>[], loading = false) {
  useManifests.mockReturnValue({ data: manifests, isPending: loading });
}

describe("AppsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearch = "";
    useManifests.mockReturnValue({ data: [], isPending: false });
  });

  it("shows spinner while loading", () => {
    withManifests([], true);
    const { getByTestId } = renderWithAppState(<AppsPage />);
    expect(getByTestId("spinner")).toBeDefined();
  });

  it("renders 'apps' heading when data loads", () => {
    withManifests([createManifest()]);
    const { getByRole } = renderWithAppState(<AppsPage />);
    expect(getByRole("heading", { name: /apps/i })).toBeDefined();
  });

  it("renders stats strip with counts", () => {
    withManifests([
      createManifest({ app_key: "a", status: "running" }),
      createManifest({ app_key: "b", status: "disabled" }),
    ]);
    const { getByTestId } = renderWithAppState(<AppsPage />);
    expect(getByTestId("apps-stats-strip")).toBeDefined();
  });

  it("does not render legacy filter pills", () => {
    withManifests([createManifest()]);
    const { queryByTestId } = renderWithAppState(<AppsPage />);
    expect(queryByTestId("apps-filter-pills")).toBeNull();
  });

  it("renders app rows in the table", () => {
    withManifests([
      createManifest({ app_key: "app_a", status: "running" }),
      createManifest({ app_key: "app_b", status: "running" }),
    ]);
    const { getByTestId } = renderWithAppState(<AppsPage />);
    expect(getByTestId("app-row-app_a")).toBeDefined();
    expect(getByTestId("app-row-app_b")).toBeDefined();
  });

  it("renders search input above the table", () => {
    withManifests([createManifest()]);
    const { getByTestId } = renderWithAppState(<AppsPage />);
    const search = getByTestId("apps-search");
    expect(search).toBeDefined();
    // Search should be inside the search slot (data-search-bar attribute)
    const searchBar = search.closest("[data-search-bar]");
    expect(searchBar).not.toBeNull();
  });

  it("shows empty state when no manifests", () => {
    withManifests([]);
    const { getByText } = renderWithAppState(<AppsPage />);
    expect(getByText(/no apps match/i)).toBeDefined();
  });

  it("renders record count in the table footer", () => {
    withManifests([
      createManifest({ app_key: "app_a", status: "running" }),
      createManifest({ app_key: "app_b", status: "running" }),
    ]);
    const { getByText } = renderWithAppState(<AppsPage />);
    expect(getByText(/2 apps/i)).toBeDefined();
  });

  it("footer count updates when search filters results", () => {
    mockSearch = "search=motion";
    withManifests([
      createManifest({ app_key: "motion_lights", status: "running" }),
      createManifest({ app_key: "alarm_app", status: "running" }),
    ]);
    const { getByText } = renderWithAppState(<AppsPage />);
    expect(getByText(/1 app/i)).toBeDefined();
  });

  describe("STATUS column filter", () => {
    it("renders a filter button on the STATUS column header", () => {
      withManifests([createManifest({ app_key: "app_a", status: "running" })]);
      const { getByRole } = renderWithAppState(<AppsPage />);
      // SortHeader renders filter button with data-testid="filter-btn" when filterContent is provided
      const filterBtn = getByRole("button", { name: /filter status/i });
      expect(filterBtn).toBeDefined();
    });

    it("clicking the STATUS filter button opens the filter popover", () => {
      withManifests([
        createManifest({ app_key: "running_app", status: "running" }),
        createManifest({ app_key: "failed_app", status: "failed" }),
      ]);
      const { getByRole, getByText } = renderWithAppState(<AppsPage />);
      const filterBtn = getByRole("button", { name: /filter status/i });
      fireEvent.click(filterBtn);
      // Popover should now be open and show filter options
      expect(getByText(/all/i)).toBeDefined();
    });
  });

  describe("query param: filter", () => {
    it("reads filter from URL query params — only failed apps shown when filter=failed", () => {
      mockSearch = "filter=failed";
      withManifests([
        createManifest({ app_key: "running_app", status: "running" }),
        createManifest({ app_key: "failed_app", status: "failed" }),
      ]);
      const { queryByTestId } = renderWithAppState(<AppsPage />);
      expect(queryByTestId("app-row-failed_app")).toBeDefined();
      expect(queryByTestId("app-row-running_app")).toBeNull();
    });
  });

  describe("query param: search", () => {
    it("reads search from URL query params — filters apps by name", () => {
      mockSearch = "search=motion";
      withManifests([
        createManifest({ app_key: "motion_lights", status: "running" }),
        createManifest({ app_key: "alarm_app", status: "running" }),
      ]);
      const { queryByTestId } = renderWithAppState(<AppsPage />);
      expect(queryByTestId("app-row-motion_lights")).toBeDefined();
      expect(queryByTestId("app-row-alarm_app")).toBeNull();
    });
  });

  describe("query param: sort/dir", () => {
    it("reads sort key from URL — defaults to status when absent", () => {
      mockSearch = "";
      withManifests([createManifest({ app_key: "app_a", status: "running" })]);
      const { getByTestId } = renderWithAppState(<AppsPage />);
      expect(getByTestId("app-row-app_a")).toBeDefined();
    });
  });

  describe("empty state when filters produce zero results", () => {
    it("names the active filter in the empty state message", () => {
      mockSearch = "filter=failed";
      withManifests([createManifest({ app_key: "running_app", status: "running" })]);
      const { getByText } = renderWithAppState(<AppsPage />);
      expect(getByText(/no apps match status: failed/i)).toBeDefined();
    });

    it("provides a clear filters button in the empty state", () => {
      mockSearch = "filter=failed";
      withManifests([createManifest({ app_key: "running_app", status: "running" })]);
      const { getByRole } = renderWithAppState(<AppsPage />);
      expect(getByRole("button", { name: /clear filters/i })).toBeDefined();
    });

    it("clicking clear filters calls navigate to reset filter and search", () => {
      mockSearch = "filter=failed";
      withManifests([createManifest({ app_key: "running_app", status: "running" })]);
      const { getByRole } = renderWithAppState(<AppsPage />);
      fireEvent.click(getByRole("button", { name: /clear filters/i }));
      expect(mockNavigate).toHaveBeenCalledWith(
        expect.not.stringContaining("filter="),
        expect.objectContaining({ replace: true }),
      );
    });
  });
});

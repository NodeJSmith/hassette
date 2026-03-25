import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { h } from "preact";
import { signal } from "@preact/signals";
import type { ComponentChildren } from "preact";
import { ManifestList, EXPANDED_KEY } from "./manifest-list";
import { AppStateContext } from "../../state/context";
import { createAppState, type AppState } from "../../state/create-app-state";
import type { AppManifest, AppInstance } from "../../api/endpoints";
import type { FilterValue } from "./status-filter";

// Mock localStorage utilities — must include all exports used by createAppState
vi.mock("../../utils/local-storage", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../utils/local-storage")>();
  return {
    ...actual,
    getStoredSet: vi.fn().mockReturnValue(new Set<string>()),
    setStoredSet: vi.fn(),
  };
});

// Mock endpoints to prevent real API calls from ActionButtons
vi.mock("../../api/endpoints", () => ({
  startApp: vi.fn(),
  stopApp: vi.fn(),
  reloadApp: vi.fn(),
}));

const localStorage = await import("../../utils/local-storage");
const getStoredSet = localStorage.getStoredSet as ReturnType<typeof vi.fn>;
const setStoredSet = localStorage.setStoredSet as ReturnType<typeof vi.fn>;

function createInstance(overrides: Partial<AppInstance> = {}): AppInstance {
  return {
    app_key: "test_app",
    index: 0,
    instance_name: "inst_0",
    class_name: "TestApp",
    status: "running",
    error_message: null,
    error_traceback: null,
    owner_id: null,
    ...overrides,
  };
}

function createManifest(overrides: Partial<AppManifest> = {}): AppManifest {
  return {
    app_key: "test_app",
    class_name: "TestApp",
    display_name: "Test App",
    filename: "test_app.py",
    enabled: true,
    auto_loaded: true,
    status: "running",
    block_reason: null,
    instance_count: 1,
    instances: [],
    error_message: null,
    error_traceback: null,
    ...overrides,
  };
}

function createMultiInstanceManifest(appKey = "multi"): AppManifest {
  return createManifest({
    app_key: appKey,
    instance_count: 2,
    instances: [
      createInstance({ app_key: appKey, index: 0, instance_name: "inst_0" }),
      createInstance({ app_key: appKey, index: 1, instance_name: "inst_1" }),
    ],
  });
}

function createWrapper(state: AppState) {
  return function Wrapper({ children }: { children: ComponentChildren }) {
    return h(AppStateContext.Provider, { value: state }, children);
  };
}

describe("ManifestList", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    getStoredSet.mockReturnValue(new Set<string>());
  });

  // -- Rendering --

  it("renders null when manifests is null", () => {
    const filter = signal<FilterValue>("all");
    const { container } = render(
      <ManifestList manifests={null} filter={filter} />,
      { wrapper: createWrapper(state) },
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders table with app rows", () => {
    const manifests = [
      createManifest({ app_key: "app_a" }),
      createManifest({ app_key: "app_b", status: "stopped" }),
    ];
    const filter = signal<FilterValue>("all");

    const { getByTestId } = render(
      <ManifestList manifests={manifests} filter={filter} />,
      { wrapper: createWrapper(state) },
    );

    expect(getByTestId("app-row-app_a")).toBeDefined();
    expect(getByTestId("app-row-app_b")).toBeDefined();
  });

  it("shows empty message when filter matches nothing", () => {
    const manifests = [createManifest({ status: "running" })];
    const filter = signal<FilterValue>("failed");

    const { getByText } = render(
      <ManifestList manifests={manifests} filter={filter} />,
      { wrapper: createWrapper(state) },
    );

    expect(getByText("No apps match this filter.")).toBeDefined();
  });

  // -- Status filtering --

  it("filters manifests by status", () => {
    const manifests = [
      createManifest({ app_key: "running_app", status: "running" }),
      createManifest({ app_key: "stopped_app", status: "stopped" }),
    ];
    const filter = signal<FilterValue>("running");

    const { getByTestId, queryByTestId } = render(
      <ManifestList manifests={manifests} filter={filter} />,
      { wrapper: createWrapper(state) },
    );

    expect(getByTestId("app-row-running_app")).toBeDefined();
    expect(queryByTestId("app-row-stopped_app")).toBeNull();
  });

  it("uses live WS status over manifest status for filtering", () => {
    const manifests = [
      createManifest({ app_key: "my_app", status: "stopped" }),
    ];
    const filter = signal<FilterValue>("running");

    // WS says app is now running
    state.appStatus.value = { my_app: { status: "running", index: 0 } };

    const { getByTestId } = render(
      <ManifestList manifests={manifests} filter={filter} />,
      { wrapper: createWrapper(state) },
    );

    expect(getByTestId("app-row-my_app")).toBeDefined();
  });

  // -- Expand/collapse for multi-instance apps --

  it("does not show expand toggle for single-instance apps", () => {
    const manifests = [createManifest({ instance_count: 1 })];
    const filter = signal<FilterValue>("all");

    const { queryByTestId } = render(
      <ManifestList manifests={manifests} filter={filter} />,
      { wrapper: createWrapper(state) },
    );

    expect(queryByTestId("expand-toggle-test_app")).toBeNull();
  });

  it("shows expand toggle for multi-instance apps", () => {
    const manifests = [createMultiInstanceManifest("test_app")];
    const filter = signal<FilterValue>("all");

    const { getByTestId } = render(
      <ManifestList manifests={manifests} filter={filter} />,
      { wrapper: createWrapper(state) },
    );

    expect(getByTestId("expand-toggle-test_app")).toBeDefined();
  });

  it("expands and collapses multi-instance app rows", () => {
    const manifests = [createMultiInstanceManifest()];
    const filter = signal<FilterValue>("all");

    const { getByTestId, getByText, queryByText } = render(
      <ManifestList manifests={manifests} filter={filter} />,
      { wrapper: createWrapper(state) },
    );

    // Initially collapsed
    expect(queryByText("inst_0")).toBeNull();

    // Expand
    fireEvent.click(getByTestId("expand-toggle-multi"));
    expect(getByText("inst_0")).toBeDefined();
    expect(getByText("inst_1")).toBeDefined();

    // Collapse
    fireEvent.click(getByTestId("expand-toggle-multi"));
    expect(queryByText("inst_0")).toBeNull();
  });

  // -- LocalStorage persistence --

  it("persists expanded state to localStorage on toggle", () => {
    const manifests = [createMultiInstanceManifest()];
    const filter = signal<FilterValue>("all");

    const { getByTestId } = render(
      <ManifestList manifests={manifests} filter={filter} />,
      { wrapper: createWrapper(state) },
    );

    fireEvent.click(getByTestId("expand-toggle-multi"));

    expect(setStoredSet).toHaveBeenCalledWith(EXPANDED_KEY, new Set(["multi"]));
  });

  it("restores expanded state from localStorage on mount", () => {
    getStoredSet.mockReturnValue(new Set(["multi"]));

    const manifests = [createMultiInstanceManifest()];
    const filter = signal<FilterValue>("all");

    const { getByText } = render(
      <ManifestList manifests={manifests} filter={filter} />,
      { wrapper: createWrapper(state) },
    );

    // Should be expanded because localStorage had it
    expect(getByText("inst_0")).toBeDefined();
  });

  it("prunes stale keys from expanded set after manifests load", () => {
    // localStorage has "old_app" and "new_app" but manifests only have "new_app"
    getStoredSet.mockReturnValue(new Set(["old_app", "new_app"]));

    const manifests = [createMultiInstanceManifest("new_app")];
    const filter = signal<FilterValue>("all");

    const { getByTestId, getByText } = render(
      <ManifestList manifests={manifests} filter={filter} />,
      { wrapper: createWrapper(state) },
    );

    // "new_app" should still be expanded (survived prune), "old_app" pruned
    expect(getByText("inst_0")).toBeDefined();

    // After a toggle, the pruned set (without "old_app") is persisted
    fireEvent.click(getByTestId("expand-toggle-new_app")); // collapse
    expect(setStoredSet).toHaveBeenCalledWith(EXPANDED_KEY, new Set());

    fireEvent.click(getByTestId("expand-toggle-new_app")); // expand again
    expect(setStoredSet).toHaveBeenCalledWith(EXPANDED_KEY, new Set(["new_app"]));
    // "old_app" is NOT in the persisted set — it was pruned
  });
});

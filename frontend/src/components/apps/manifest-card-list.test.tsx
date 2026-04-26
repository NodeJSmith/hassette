import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { h } from "preact";
import { signal } from "@preact/signals";
import type { Signal } from "@preact/signals";
import type { ComponentChildren } from "preact";
import { ManifestCardList } from "./manifest-card-list";
import { AppStateContext } from "../../state/context";
import { createAppState, type AppState } from "../../state/create-app-state";
import { createManifest, createInstance } from "../../test/factories";
import type { AppManifest } from "../../api/endpoints";

// Mock endpoints to prevent real API calls from ActionButtons
vi.mock("../../api/endpoints", () => ({
  startApp: vi.fn(),
  stopApp: vi.fn(),
  reloadApp: vi.fn(),
}));

function createMultiInstanceManifest(appKey = "multi"): AppManifest {
  return createManifest({
    app_key: appKey,
    display_name: "Multi App",
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

describe("ManifestCardList", () => {
  let state: AppState;
  let expanded: Signal<Set<string>>;
  let toggleExpand: ReturnType<typeof vi.fn<(appKey: string) => void>>;

  beforeEach(() => {
    state = createAppState();
    expanded = signal(new Set<string>());
    toggleExpand = vi.fn<(appKey: string) => void>();
  });

  it("renders one card per manifest", () => {
    const manifests = [
      createManifest({ app_key: "app_a", display_name: "App A" }),
      createManifest({ app_key: "app_b", display_name: "App B" }),
      createManifest({ app_key: "app_c", display_name: "App C" }),
    ];

    const { getAllByTestId } = render(
      <ManifestCardList
        manifests={manifests}
        expanded={expanded}
        toggleExpand={toggleExpand}
        appStatus={state.appStatus}
      />,
      { wrapper: createWrapper(state) },
    );

    expect(getAllByTestId(/^manifest-card-/)).toHaveLength(3);
  });

  it("shows app name and status badge on each card", () => {
    const manifests = [createManifest({ app_key: "my_app", display_name: "My App", status: "running" })];

    const { getByTestId, getByText } = render(
      <ManifestCardList
        manifests={manifests}
        expanded={expanded}
        toggleExpand={toggleExpand}
        appStatus={state.appStatus}
      />,
      { wrapper: createWrapper(state) },
    );

    expect(getByTestId("manifest-card-my_app")).toBeDefined();
    expect(getByText("My App")).toBeDefined();
    expect(getByText("running")).toBeDefined();
  });

  it("shows action buttons on each card", () => {
    const manifests = [createManifest({ app_key: "my_app", status: "running" })];

    const { getByTestId } = render(
      <ManifestCardList
        manifests={manifests}
        expanded={expanded}
        toggleExpand={toggleExpand}
        appStatus={state.appStatus}
      />,
      { wrapper: createWrapper(state) },
    );

    // Running app should have Stop and Reload buttons
    expect(getByTestId("btn-stop-my_app")).toBeDefined();
    expect(getByTestId("btn-reload-my_app")).toBeDefined();
  });

  it("shows expand toggle for multi-instance apps", () => {
    const manifests = [createMultiInstanceManifest("multi_app")];

    const { getByTestId } = render(
      <ManifestCardList
        manifests={manifests}
        expanded={expanded}
        toggleExpand={toggleExpand}
        appStatus={state.appStatus}
      />,
      { wrapper: createWrapper(state) },
    );

    const toggle = getByTestId("expand-toggle-multi_app");
    expect(toggle).toBeDefined();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("does not show expand toggle for single-instance apps", () => {
    const manifests = [createManifest({ app_key: "single", instance_count: 1 })];

    const { queryByTestId } = render(
      <ManifestCardList
        manifests={manifests}
        expanded={expanded}
        toggleExpand={toggleExpand}
        appStatus={state.appStatus}
      />,
      { wrapper: createWrapper(state) },
    );

    expect(queryByTestId("expand-toggle-single")).toBeNull();
  });

  it("shows instance sub-cards when expanded", () => {
    expanded = signal(new Set(["multi_app"]));
    const manifests = [createMultiInstanceManifest("multi_app")];

    const { getByText } = render(
      <ManifestCardList
        manifests={manifests}
        expanded={expanded}
        toggleExpand={toggleExpand}
        appStatus={state.appStatus}
      />,
      { wrapper: createWrapper(state) },
    );

    expect(getByText("inst_0")).toBeDefined();
    expect(getByText("inst_1")).toBeDefined();
  });

  it("calls toggleExpand when expand toggle is clicked", () => {
    const manifests = [createMultiInstanceManifest("multi_app")];

    const { getByTestId } = render(
      <ManifestCardList
        manifests={manifests}
        expanded={expanded}
        toggleExpand={toggleExpand}
        appStatus={state.appStatus}
      />,
      { wrapper: createWrapper(state) },
    );

    fireEvent.click(getByTestId("expand-toggle-multi_app"));
    expect(toggleExpand).toHaveBeenCalledWith("multi_app");
  });

  it("links app name to detail page", () => {
    const manifests = [createManifest({ app_key: "my_app", display_name: "My App" })];

    const { getByText } = render(
      <ManifestCardList
        manifests={manifests}
        expanded={expanded}
        toggleExpand={toggleExpand}
        appStatus={state.appStatus}
      />,
      { wrapper: createWrapper(state) },
    );

    const link = getByText("My App").closest("a");
    expect(link?.getAttribute("href")).toBe("/apps/my_app");
  });

  it("shows instance count badge for multi-instance apps", () => {
    const manifests = [createMultiInstanceManifest("multi_app")];

    const { getByText } = render(
      <ManifestCardList
        manifests={manifests}
        expanded={expanded}
        toggleExpand={toggleExpand}
        appStatus={state.appStatus}
      />,
      { wrapper: createWrapper(state) },
    );

    expect(getByText("2 instances")).toBeDefined();
  });

  it("uses live WS status over manifest status", () => {
    const manifests = [createManifest({ app_key: "my_app", status: "stopped" })];
    state.appStatus.value = { my_app: { status: "running", index: 0 } };

    const { getByText } = render(
      <ManifestCardList
        manifests={manifests}
        expanded={expanded}
        toggleExpand={toggleExpand}
        appStatus={state.appStatus}
      />,
      { wrapper: createWrapper(state) },
    );

    // Should show live status "running" not manifest "stopped"
    expect(getByText("running")).toBeDefined();
  });
});

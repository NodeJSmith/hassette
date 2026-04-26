import { describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { ManifestRow } from "./manifest-row";
import { createManifest, createInstance } from "../../test/factories";

// Mock ActionButtons to avoid API call setup — we're testing ManifestRow rendering
vi.mock("./action-buttons", () => ({
  ActionButtons: ({ appKey, status }: { appKey: string; status: string }) => (
    <div data-testid={`action-buttons-${appKey}`} data-status={status} />
  ),
}));

describe("ManifestRow", () => {
  // -- Basic rendering --

  it("renders app_key as a link", () => {
    const manifest = createManifest({ app_key: "my_automation" });
    const { container } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    const link = container.querySelector(`a[href='/apps/my_automation']`);
    expect(link).not.toBeNull();
    expect(link!.textContent).toBe("my_automation");
  });

  it("renders display_name in second column", () => {
    const manifest = createManifest({ display_name: "My Automation" });
    const { getByText } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    expect(getByText("My Automation")).toBeDefined();
  });

  it("renders class_name below display_name when different", () => {
    const manifest = createManifest({ display_name: "My Automation", class_name: "MyAutomationClass" });
    const { getByText } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    expect(getByText("MyAutomationClass")).toBeDefined();
  });

  it("does not render duplicate class_name when it matches display_name", () => {
    const manifest = createManifest({ display_name: "TestApp", class_name: "TestApp" });
    const { queryAllByText } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    // Only the display_name cell should contain "TestApp" — class_name is hidden
    expect(queryAllByText("TestApp").length).toBe(1);
  });

  it("renders a row with testid matching app_key", () => {
    const manifest = createManifest({ app_key: "sensor_watch" });
    const { getByTestId } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    expect(getByTestId("app-row-sensor_watch")).toBeDefined();
  });

  it("renders ActionButtons with correct appKey and status", () => {
    const manifest = createManifest({ app_key: "my_app", status: "running" });
    const { getByTestId } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    const buttons = getByTestId("action-buttons-my_app");
    expect(buttons.getAttribute("data-status")).toBe("running");
  });

  // -- liveStatus override --

  it("uses liveStatus over manifest status when provided", () => {
    const manifest = createManifest({ app_key: "my_app", status: "stopped" });
    const { getByTestId } = render(
      <ManifestRow manifest={manifest} liveStatus="running" isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    const buttons = getByTestId("action-buttons-my_app");
    expect(buttons.getAttribute("data-status")).toBe("running");
  });

  // -- Error message --

  it("renders error_message in danger text when present", () => {
    const manifest = createManifest({ error_message: "Import failed" });
    const { container } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    const dangerSpan = container.querySelector(".ht-text-danger");
    expect(dangerSpan).not.toBeNull();
    expect(dangerSpan!.textContent).toBe("Import failed");
  });

  it("renders em dash when error_message is null", () => {
    const manifest = createManifest({ error_message: null });
    const { container } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    expect(container.textContent).toContain("—");
  });

  // -- Single instance: no expand toggle --

  it("does not render expand toggle for single-instance app", () => {
    const manifest = createManifest({ instance_count: 1 });
    const { queryByTestId } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    expect(queryByTestId(`expand-toggle-${manifest.app_key}`)).toBeNull();
  });

  // -- Multi-instance: expand toggle and instance rows --

  it("renders expand toggle for multi-instance app", () => {
    const manifest = createManifest({
      app_key: "multi",
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0" }),
        createInstance({ index: 1, instance_name: "inst_1" }),
      ],
    });
    const { getByTestId } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    expect(getByTestId("expand-toggle-multi")).toBeDefined();
  });

  it("calls onToggleExpand when expand button is clicked", () => {
    const onToggle = vi.fn();
    const manifest = createManifest({
      app_key: "multi",
      instance_count: 2,
      instances: [createInstance({ index: 0 }), createInstance({ index: 1 })],
    });
    const { getByTestId } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={onToggle} />,
    );
    fireEvent.click(getByTestId("expand-toggle-multi"));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("renders instance rows when isExpanded is true", () => {
    const manifest = createManifest({
      app_key: "multi",
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0" }),
        createInstance({ index: 1, instance_name: "inst_1" }),
      ],
    });
    const { getByText } = render(
      <ManifestRow manifest={manifest} isExpanded={true} onToggleExpand={vi.fn()} />,
    );
    expect(getByText("inst_0")).toBeDefined();
    expect(getByText("inst_1")).toBeDefined();
  });

  it("does not render instance rows when isExpanded is false", () => {
    const manifest = createManifest({
      app_key: "multi",
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0" }),
        createInstance({ index: 1, instance_name: "inst_1" }),
      ],
    });
    const { queryByText } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    expect(queryByText("inst_0")).toBeNull();
    expect(queryByText("inst_1")).toBeNull();
  });

  it("expand toggle has correct aria-expanded attribute", () => {
    const manifest = createManifest({
      app_key: "multi",
      instance_count: 2,
      instances: [createInstance({ index: 0 }), createInstance({ index: 1 })],
    });

    const { getByTestId: getNotExpanded } = render(
      <ManifestRow manifest={manifest} isExpanded={false} onToggleExpand={vi.fn()} />,
    );
    expect(getNotExpanded("expand-toggle-multi").getAttribute("aria-expanded")).toBe("false");
  });

  // -- Instance rows link to individual instance pages --

  it("instance row links to /apps/:app_key/:index", () => {
    const manifest = createManifest({
      app_key: "multi",
      instance_count: 2,
      instances: [createInstance({ index: 0, instance_name: "inst_0" })],
    });
    const { container } = render(
      <ManifestRow manifest={manifest} isExpanded={true} onToggleExpand={vi.fn()} />,
    );
    const link = container.querySelector("a[href='/apps/multi/0']");
    expect(link).not.toBeNull();
  });
});

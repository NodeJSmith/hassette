import { describe, expect, it, vi } from "vitest";
import { signal } from "@preact/signals";
import { LogsPage } from "./logs";
import { renderWithAppState } from "../test/render-helpers";
import { createManifest } from "../test/factories";

// Stub LogTable — it has its own extensive tests
vi.mock("../components/shared/log-table", () => ({
  LogTable: ({ showAppColumn, appKeys, hideTitle }: { showAppColumn: boolean; appKeys: string[]; hideTitle?: boolean }) => (
    <div
      data-testid="log-table"
      data-show-app-column={String(showAppColumn)}
      data-app-keys={appKeys.join(",")}
      data-hide-title={String(!!hideTitle)}
    />
  ),
}));

function withManifests(manifests: ReturnType<typeof createManifest>[]) {
  return { stateOverrides: { manifests: signal(manifests), manifestsLoading: signal(false) } };
}

describe("LogsPage", () => {
  it("renders logs page with card container", () => {
    const { container } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(container.querySelector(".ht-logs-page")).toBeDefined();
    expect(container.querySelector(".ht-card--logs-full")).toBeDefined();
  });

  it("renders LogTable component", () => {
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table")).toBeDefined();
  });

  it("passes showAppColumn=true to LogTable", () => {
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-show-app-column")).toBe("true");
  });

  it("passes sorted app keys from manifests to LogTable", () => {
    const manifests = [
      createManifest({ app_key: "zebra_app" }),
      createManifest({ app_key: "alpha_app" }),
    ];
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests(manifests));
    // App keys should be sorted alphabetically
    expect(getByTestId("log-table").getAttribute("data-app-keys")).toBe("alpha_app,zebra_app");
  });

  it("passes empty app keys when manifests have no data", () => {
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-app-keys")).toBe("");
  });

  it("renders LogTable inside a card", () => {
    const { container } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(container.querySelector(".ht-card")).not.toBeNull();
  });

  it("renders page-level h1 heading", () => {
    const { container } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(container.querySelector("h1.ht-display")?.textContent).toBe("logs");
  });

  it("passes hideTitle to LogTable", () => {
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-hide-title")).toBe("true");
  });
});

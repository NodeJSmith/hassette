import { describe, expect, it, vi, beforeEach } from "vitest";
import { signal } from "@preact/signals";
import { fireEvent } from "@testing-library/preact";
import { LogsPage } from "./logs";
import { renderWithAppState } from "../test/render-helpers";
import { createManifest } from "../test/factories";

// Reactive search signal to allow URL param simulation in logs page tests
import { signal as _signal } from "@preact/signals";
const mockSearchSignal = _signal("");
const mockNavigate = vi.fn((url: string) => {
  const qIdx = url.indexOf("?");
  mockSearchSignal.value = qIdx >= 0 ? url.slice(qIdx + 1) : "";
});

vi.mock("wouter", () => ({
  useSearch: () => mockSearchSignal.value,
  useLocation: () => ["/logs", mockNavigate],
  Link: ({ href, children, class: cls }: Record<string, unknown>) =>
    <a href={href as string} class={cls as string}>{children as never}</a>,
}));

// Stub LogTable — it has its own extensive tests
vi.mock("../components/shared/log-table", () => ({
  LogTable: ({
    showAppColumn,
    appKeys,
    hideTitle,
    mode,
    fetcher,
    hideExecutionId,
  }: {
    showAppColumn: boolean;
    appKeys: string[];
    hideTitle?: boolean;
    mode?: string;
    fetcher?: () => Promise<unknown[]>;
    hideExecutionId?: boolean;
  }) => (
    <div
      data-testid="log-table"
      data-show-app-column={String(showAppColumn)}
      data-app-keys={(appKeys ?? []).join(",")}
      data-hide-title={String(!!hideTitle)}
      data-mode={mode ?? "live"}
      data-has-fetcher={String(!!fetcher)}
      data-hide-execution-id={String(!!hideExecutionId)}
    />
  ),
}));

function withManifests(manifests: ReturnType<typeof createManifest>[]) {
  return { stateOverrides: { manifests: signal(manifests), manifestsLoading: signal(false) } };
}

beforeEach(() => {
  mockSearchSignal.value = "";
  mockNavigate.mockReset();
  mockNavigate.mockImplementation((url: string) => {
    const qIdx = url.indexOf("?");
    mockSearchSignal.value = qIdx >= 0 ? url.slice(qIdx + 1) : "";
  });
});

describe("LogsPage", () => {
  it("renders logs page with card container", () => {
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("logs-page")).toBeDefined();
    expect(getByTestId("logs-card")).toBeDefined();
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
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("logs-card")).toBeDefined();
  });

  it("renders page-level h1 heading", () => {
    const { container } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(container.querySelector("h1.ht-display")?.textContent).toBe("logs");
  });

  it("passes hideTitle to LogTable", () => {
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-hide-title")).toBe("true");
  });

  it("renders LogTable in live mode when no execution_id param present", () => {
    mockSearchSignal.value = "";
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-mode")).toBe("live");
  });

  it("renders LogTable in historical mode when execution_id URL param is present", () => {
    mockSearchSignal.value = "execution_id=abc-123";
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-mode")).toBe("historical");
  });

  it("passes a custom fetcher to LogTable when execution_id is present", () => {
    mockSearchSignal.value = "execution_id=abc-123";
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-has-fetcher")).toBe("true");
  });

  it("shows execution filter banner when execution_id param is present", () => {
    mockSearchSignal.value = "execution_id=abc-123";
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("execution-filter-banner")).toBeDefined();
  });

  it("banner contains the execution id", () => {
    mockSearchSignal.value = "execution_id=abc-123";
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("execution-filter-banner").textContent).toContain("abc-123");
  });

  it("banner has a clear filter link", () => {
    mockSearchSignal.value = "execution_id=abc-123";
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    const banner = getByTestId("execution-filter-banner");
    expect(banner.querySelector("a, button")).not.toBeNull();
  });

  it("clicking clear filter removes execution_id from URL", () => {
    mockSearchSignal.value = "execution_id=abc-123";
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    const clearLink = getByTestId("execution-filter-banner").querySelector("a, button") as HTMLElement;
    fireEvent.click(clearLink);
    expect(mockNavigate).toHaveBeenCalled();
    const [url] = mockNavigate.mock.calls[0];
    expect(url).not.toContain("execution_id");
  });

  it("hides execution_id column when filtering by execution_id", () => {
    mockSearchSignal.value = "execution_id=abc-123";
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-hide-execution-id")).toBe("true");
  });

  it("shows execution_id column in live mode (no filter)", () => {
    mockSearchSignal.value = "";
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-hide-execution-id")).toBe("false");
  });

  it("does not show banner in live mode", () => {
    mockSearchSignal.value = "";
    const { queryByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(queryByTestId("execution-filter-banner")).toBeNull();
  });
});

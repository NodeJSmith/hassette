import { describe, expect, it, vi, beforeEach } from "vitest";
import { signal } from "@preact/signals";
import { LogsPage } from "./logs";
import { renderWithAppState } from "../test/render-helpers";
import { createManifest } from "../test/factories";

const mockSearchSignal = signal("");
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

vi.mock("../components/shared/log-table", () => ({
  LogTable: ({
    context,
    appKeys,
    executionId,
  }: {
    context?: string;
    appKeys?: string[];
    executionId?: string | null;
  }) => {
    return (
      <div
        data-testid="log-table"
        data-context={context ?? "global"}
        data-app-keys={(appKeys ?? []).join(",")}
        data-execution-id={executionId ?? ""}
      />
    );
  },
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

  it("passes context=global to LogTable", () => {
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-context")).toBe("global");
  });

  it("passes sorted app keys from manifests to LogTable", () => {
    const manifests = [
      createManifest({ app_key: "zebra_app" }),
      createManifest({ app_key: "alpha_app" }),
    ];
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests(manifests));
    expect(getByTestId("log-table").getAttribute("data-app-keys")).toBe("alpha_app,zebra_app");
  });

  it("passes empty app keys when manifests have no data", () => {
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-app-keys")).toBe("");
  });

  it("renders page-level h1 heading", () => {
    const { container } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(container.querySelector("h1.ht-display")?.textContent).toBe("logs");
  });

  it("passes no executionId when URL param is absent", () => {
    mockSearchSignal.value = "";
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-execution-id")).toBe("");
  });

  it("passes executionId when URL param is present", () => {
    mockSearchSignal.value = "execution_id=abc-123";
    const { getByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(getByTestId("log-table").getAttribute("data-execution-id")).toBe("abc-123");
  });

  it("renders single layout regardless of execution_id presence", () => {
    mockSearchSignal.value = "execution_id=abc-123";
    const { queryByTestId } = renderWithAppState(<LogsPage />, withManifests([]));
    expect(queryByTestId("logs-card")).not.toBeNull();
  });
});

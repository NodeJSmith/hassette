import { signal } from "@preact/signals";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createWouterMock } from "../../test/mock-wouter";
import { renderWithAppState } from "../../test/render-helpers";
import { HandlersTab } from "./handlers-tab";
import { renderHandlersTab } from "./handlers-tab.test-helpers";

// Mock child components that make API calls
vi.mock("../shared/execution-table", () => ({
  ExecutionTable: ({ tableId, kind, records }: { tableId: string; kind: string; records: unknown[] }) => (
    <div data-testid={tableId} data-kind={kind} data-count={records.length}>
      {kind === "handler" ? "Invocations panel" : "Executions panel"}
    </div>
  ),
}));

vi.mock("./execution-detail", () => ({
  ExecutionDetailFetcher: (props: { executionId: string }) => (
    <div data-testid="execution-detail-fetcher">{props.executionId}</div>
  ),
}));

const mockNavigate = vi.fn();
const mockCorrectUrl = vi.fn();

vi.mock("wouter", () => createWouterMock({ useLocation: () => ["/apps/test_app/handlers", mockNavigate] }));

vi.mock("../../hooks/use-correct-url", () => ({
  useCorrectUrl: () => mockCorrectUrl,
}));

describe("HandlersTab rendering", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the master list container", () => {
    const { getByTestId } = renderHandlersTab();
    expect(getByTestId("handler-list")).toBeDefined();
  });

  it("renders empty state when no listeners or jobs", () => {
    const { getByTestId } = renderWithAppState(
      <HandlersTab listeners={[]} jobs={[]} selectedHandler={null} selectedExecId={null} appKey="test_app" />,
      { stateOverrides: { uptimeSeconds: signal<number | null>(120) } },
    );
    expect(getByTestId("handlers-empty")).toBeDefined();
  });

  it("shows detail pane placeholder when no item is selected", () => {
    const { getByTestId } = renderHandlersTab();
    expect(getByTestId("detail-placeholder")).toBeDefined();
  });

  it("does not show back button on desktop layout", () => {
    const { queryByTestId } = renderHandlersTab();
    expect(queryByTestId("back-to-list")).toBeNull();
  });
});

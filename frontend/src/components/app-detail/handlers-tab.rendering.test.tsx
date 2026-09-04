import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAppStore } from "../../state/store";
import { createListener } from "../../test/factories";
import { createWouterMock } from "../../test/mock-wouter";
import { createTestQueryClient } from "../../test/query-test-utils";
import { renderWithAppState } from "../../test/render-helpers";
import { HandlersTab } from "./handlers-tab";
import { renderHandlersTab } from "./handlers-tab.test-helpers";

/**
 * Fake ResizeObserver that records the last-observed element and lets tests fire a
 * resize callback manually — the global stub in test-setup.ts is a no-op, so any test
 * exercising the mobile breakpoint transition needs its own controllable instance.
 */
class MockResizeObserver {
  static instances: MockResizeObserver[] = [];
  element: Element | null = null;

  constructor(private readonly cb: ResizeObserverCallback) {
    MockResizeObserver.instances.push(this);
  }

  observe(el: Element) {
    this.element = el;
  }

  unobserve() {
    this.element = null;
  }

  disconnect() {
    this.element = null;
  }

  trigger(width: number) {
    this.cb([{ contentRect: { width } } as ResizeObserverEntry], this);
  }
}

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
      { storeOverrides: { uptimeSeconds: 120 } },
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

  it("re-establishes the resize observer after the empty state transitions to master-detail (issue #1785)", async () => {
    MockResizeObserver.instances = [];
    vi.stubGlobal("ResizeObserver", MockResizeObserver);

    const client = createTestQueryClient();
    useAppStore.setState({ uptimeSeconds: 120 });

    const { getByTestId, rerender } = render(
      <QueryClientProvider client={client}>
        <HandlersTab listeners={[]} jobs={[]} selectedHandler={null} selectedExecId={null} appKey="test_app" />
      </QueryClientProvider>,
    );

    expect(getByTestId("handlers-empty")).toBeDefined();

    const listener = createListener({ listener_id: 1 });
    rerender(
      <QueryClientProvider client={client}>
        <HandlersTab
          listeners={[listener]}
          jobs={[]}
          selectedHandler="listener/1"
          selectedExecId={null}
          appKey="test_app"
        />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(getByTestId("handler-list")).toBeDefined());

    const observer = MockResizeObserver.instances[MockResizeObserver.instances.length - 1];
    expect(observer?.element).toBeDefined();

    act(() => {
      observer?.trigger(400); // narrower than BREAKPOINT_MOBILE (768)
    });

    await waitFor(() => expect(getByTestId("back-to-list")).toBeDefined());

    vi.unstubAllGlobals();
  });
});

import { describe, expect, it, vi } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { HandlerInvocations } from "./handler-invocations";
import { createInvocation, createLogEntry } from "../../test/factories";
import type { components } from "../../api/generated-types";

type LogsByExecutionResponse = components["schemas"]["LogsByExecutionResponse"];

// Stub LogTable — it has its own extensive tests and pulls in wouter + AppStateContext.
// We capture the fetcher so we can invoke it to verify what data it would produce.
let capturedFetcher: (() => Promise<unknown>) | undefined;
vi.mock("../../components/shared/log-table", () => ({
  LogTable: ({
    fetcher,
    mode,
    useLocalState,
    hideExecutionId,
    hideTitle,
    showAppColumn,
  }: {
    fetcher?: () => Promise<unknown>;
    mode?: string;
    useLocalState?: boolean;
    hideExecutionId?: boolean;
    hideTitle?: boolean;
    showAppColumn?: boolean;
  }) => {
    capturedFetcher = fetcher;
    return (
      <div
        data-testid="log-table-stub"
        data-mode={mode ?? "live"}
        data-use-local-state={String(!!useLocalState)}
        data-hide-execution-id={String(!!hideExecutionId)}
        data-hide-title={String(!!hideTitle)}
        data-show-app-column={String(!!showAppColumn)}
        data-has-fetcher={String(!!fetcher)}
      />
    );
  },
}));

describe("HandlerInvocations", () => {
  it("renders empty state when invocations array is empty", () => {
    const { getByText } = render(
      <HandlerInvocations invocations={[]} listenerId={1} />,
    );
    expect(getByText("no invocations recorded")).toBeDefined();
  });

  it("renders table with testid matching listenerId", () => {
    const { getByTestId } = render(
      <HandlerInvocations invocations={[createInvocation()]} listenerId={42} />,
    );
    expect(getByTestId("invocation-table-42")).toBeDefined();
  });

  it("renders Time, Trigger, Duration, and Note column headers", () => {
    const { getByText } = render(
      <HandlerInvocations invocations={[createInvocation()]} listenerId={1} />,
    );
    expect(getByText("Time")).toBeDefined();
    expect(getByText("Trigger")).toBeDefined();
    expect(getByText("Duration")).toBeDefined();
    expect(getByText("Note")).toBeDefined();
  });

  it("renders error message in note column", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ status: "error", error_message: "Connection refused" })]}
        listenerId={1}
      />,
    );
    expect(container.textContent).toContain("Connection refused");
  });

  it("clicking row expands invocation detail with traceback", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[
          createInvocation({
            status: "error",
            error_message: "Something failed",
            error_traceback: "Traceback (most recent call last):\n  File test.py, line 1",
          }),
        ]}
        listenerId={1}
      />,
    );

    expect(container.querySelector("[data-testid='invocation-detail']")).toBeNull();

    const row = container.querySelector("[data-testid='invocation-row']");
    expect(row).not.toBeNull();
    fireEvent.click(row!);

    const detail = container.querySelector("[data-testid='invocation-detail']");
    expect(detail).not.toBeNull();
    expect(detail!.textContent).toContain("Traceback (most recent call last)");
  });

  it("clicking open row again collapses the detail", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ status: "error", error_traceback: "tb" })]}
        listenerId={1}
      />,
    );

    const row = container.querySelector("[data-testid='invocation-row']")!;
    fireEvent.click(row);
    expect(container.querySelector("[data-testid='invocation-detail']")).not.toBeNull();

    fireEvent.click(row);
    expect(container.querySelector("[data-testid='invocation-detail']")).toBeNull();
  });

  it("shows Show More button when invocations exceed 5", () => {
    const invocations = Array.from({ length: 6 }, (_, i) =>
      createInvocation({ execution_start_ts: 1700000000 + i }),
    );
    const { getByRole } = render(
      <HandlerInvocations invocations={invocations} listenerId={1} />,
    );
    expect(getByRole("button", { name: /show all/i })).toBeDefined();
  });

  it("does not show Show More button when invocations are 5 or fewer", () => {
    const invocations = Array.from({ length: 5 }, (_, i) =>
      createInvocation({ execution_start_ts: 1700000000 + i }),
    );
    const { queryByRole } = render(
      <HandlerInvocations invocations={invocations} listenerId={1} />,
    );
    expect(queryByRole("button", { name: /show all/i })).toBeNull();
  });

  it("renders multiple rows for multiple invocations", () => {
    const invocations = [
      createInvocation({ execution_start_ts: 1700000001 }),
      createInvocation({ execution_start_ts: 1700000002 }),
      createInvocation({ execution_start_ts: 1700000003 }),
    ];
    const { container } = render(
      <HandlerInvocations invocations={invocations} listenerId={1} />,
    );
    const rows = container.querySelectorAll("[data-testid='invocation-row']");
    expect(rows.length).toBe(3);
  });

  it("renders trigger origin in trigger column", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ trigger_origin: "REMOTE", trigger_context_id: "ctx-1" })]}
        listenerId={1}
      />,
    );
    expect(container.textContent).toContain("REMOTE");
  });

  it("shows context ID in expanded detail", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ trigger_context_id: "ctx-abc-123" })]}
        listenerId={1}
      />,
    );
    fireEvent.click(container.querySelector("[data-testid='invocation-row']")!);
    expect(container.textContent).toContain("ctx-abc-123");
  });

  it("expanded detail shows 2-column grid for execution ID and result", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ execution_id: "exec-123" })]}
        listenerId={1}
      />,
    );
    fireEvent.click(container.querySelector("[data-testid='invocation-row']")!);
    const grid = container.querySelector("[data-testid='invocation-detail-grid']");
    expect(grid).not.toBeNull();
    expect(container.textContent).toContain("exec-123");
  });

  // ── Logs section in InvocationDetail ──────────────────────────────────────

  it("shows 'No execution ID' message when execution_id is null", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ execution_id: null })]}
        listenerId={1}
      />,
    );
    fireEvent.click(container.querySelector("[data-testid='invocation-row']")!);
    const detail = container.querySelector("[data-testid='invocation-detail']");
    expect(detail).not.toBeNull();
    expect(detail!.textContent).toContain("No execution ID");
  });

  it("renders LogTable stub with correct props when execution_id is present", async () => {
    const execId = "aaaa-bbbb-cccc";
    server.use(
      http.get(`/api/logs/by-execution/${execId}`, () => {
        return HttpResponse.json<LogsByExecutionResponse>({
          records: [createLogEntry({ seq: 1, message: "handler started" })],
          truncated: false,
          retention_expired: false,
        });
      }),
    );

    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ execution_id: execId })]}
        listenerId={1}
      />,
    );

    fireEvent.click(container.querySelector("[data-testid='invocation-row']")!);

    await waitFor(() => {
      const stub = container.querySelector("[data-testid='log-table-stub']");
      expect(stub).not.toBeNull();
      expect(stub!.getAttribute("data-mode")).toBe("historical");
      expect(stub!.getAttribute("data-use-local-state")).toBe("true");
      expect(stub!.getAttribute("data-hide-execution-id")).toBe("true");
    });
  });

  it("fetcher passed to LogTable returns records from getLogsByExecution", async () => {
    const execId = "aaaa-bbbb-cccc";
    const logRecords = [
      createLogEntry({ seq: 1, message: "handler started" }),
      createLogEntry({ seq: 2, message: "handler finished" }),
    ];
    server.use(
      http.get(`/api/logs/by-execution/${execId}`, () => {
        return HttpResponse.json<LogsByExecutionResponse>({
          records: logRecords,
          truncated: false,
          retention_expired: false,
        });
      }),
    );

    capturedFetcher = undefined;
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ execution_id: execId })]}
        listenerId={1}
      />,
    );

    fireEvent.click(container.querySelector("[data-testid='invocation-row']")!);

    await waitFor(() => {
      expect(capturedFetcher).toBeDefined();
    });

    // The fetcher is a closure that returns the already-fetched records.
    const result = await capturedFetcher!();
    expect(result).toHaveLength(2);
    expect((result as typeof logRecords)[0].message).toBe("handler started");
    expect((result as typeof logRecords)[1].message).toBe("handler finished");
  });

  it("shows retention-expired message when response has retention_expired=true", async () => {
    const execId = "expired-exec-id";
    server.use(
      http.get(`/api/logs/by-execution/${execId}`, () => {
        return HttpResponse.json<LogsByExecutionResponse>({
          records: [],
          truncated: false,
          retention_expired: true,
        });
      }),
    );

    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ execution_id: execId })]}
        listenerId={1}
      />,
    );

    fireEvent.click(container.querySelector("[data-testid='invocation-row']")!);

    await waitFor(() => {
      expect(container.textContent).toContain("retention policy");
    });
  });

  it("shows empty state message when response has zero records and retention_expired=false", async () => {
    const execId = "empty-exec-id";
    server.use(
      http.get(`/api/logs/by-execution/${execId}`, () => {
        return HttpResponse.json<LogsByExecutionResponse>({
          records: [],
          truncated: false,
          retention_expired: false,
        });
      }),
    );

    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ execution_id: execId })]}
        listenerId={1}
      />,
    );

    fireEvent.click(container.querySelector("[data-testid='invocation-row']")!);

    await waitFor(() => {
      expect(container.textContent).toContain("No logs recorded");
    });
  });

  it("shows truncation notice and 'View all logs' link when truncated=true", async () => {
    const execId = "truncated-exec-id";
    server.use(
      http.get(`/api/logs/by-execution/${execId}`, () => {
        return HttpResponse.json<LogsByExecutionResponse>({
          records: [createLogEntry({ seq: 1, message: "a log line" })],
          truncated: true,
          retention_expired: false,
        });
      }),
    );

    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ execution_id: execId })]}
        listenerId={1}
      />,
    );

    fireEvent.click(container.querySelector("[data-testid='invocation-row']")!);

    await waitFor(() => {
      expect(container.textContent).toContain("View all logs");
    });
    const link = container.querySelector(`a[href*='${execId}']`);
    expect(link).not.toBeNull();
  });

  it("renders 'View all logs' link pointing to /logs with execution_id query param", async () => {
    const execId = "link-test-exec";
    server.use(
      http.get(`/api/logs/by-execution/${execId}`, () => {
        return HttpResponse.json<LogsByExecutionResponse>({
          records: [createLogEntry({ seq: 1, message: "some log" })],
          truncated: false,
          retention_expired: false,
        });
      }),
    );

    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ execution_id: execId })]}
        listenerId={1}
      />,
    );

    fireEvent.click(container.querySelector("[data-testid='invocation-row']")!);

    await waitFor(() => {
      const link = container.querySelector("[data-testid='view-all-logs-link']") as HTMLAnchorElement | null;
      expect(link).not.toBeNull();
      expect(link!.getAttribute("href")).toContain(`execution_id=${execId}`);
    });
  });

  it("shows error message when fetch fails", async () => {
    const execId = "exec-fail-123";
    const inv = createInvocation({ execution_id: execId });

    server.use(
      http.get("*/api/logs/by-execution/:id", () => HttpResponse.error()),
    );

    const { container } = render(<HandlerInvocations invocations={[inv]} listenerId={1} />);
    const row = container.querySelector("tbody tr") as HTMLElement;
    fireEvent.click(row);

    await waitFor(() => {
      expect(container.textContent).toContain("Failed to load logs");
    });
  });
});

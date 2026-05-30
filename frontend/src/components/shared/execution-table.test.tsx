import { fireEvent, render } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import { createExecution } from "../../test/factories";
import { ExecutionTable } from "./execution-table";

vi.mock("./execution-logs", () => ({
  ExecutionLogs: ({ executionId }: { executionId: string }) => (
    <div data-testid="execution-logs-section" data-execution-id={executionId} />
  ),
}));

describe("ExecutionTable", () => {
  // ── Empty states ──

  it("renders handler empty state when records are empty", () => {
    const { getByText } = render(<ExecutionTable records={[]} kind="handler" tableId="invocation-table-1" />);
    expect(getByText("no invocations recorded")).toBeDefined();
  });

  it("renders job empty state when records are empty", () => {
    const { getByText } = render(<ExecutionTable records={[]} kind="job" tableId="execution-table-1" />);
    expect(getByText("no executions recorded.")).toBeDefined();
  });

  // ── Table structure ──

  it("renders table with provided testid", () => {
    const { getByTestId } = render(
      <ExecutionTable records={[createExecution("job")]} kind="job" tableId="execution-table-99" />,
    );
    expect(getByTestId("execution-table-99")).toBeDefined();
  });

  it("renders unified column headers", () => {
    const { getByText } = render(<ExecutionTable records={[createExecution("job")]} kind="job" tableId="t" />);
    expect(getByText("Status")).toBeDefined();
    expect(getByText("Timestamp")).toBeDefined();
    expect(getByText("Duration")).toBeDefined();
    expect(getByText("Execution ID")).toBeDefined();
  });

  it("renders correct number of rows", () => {
    const records = [
      createExecution("job", { execution_start_ts: 1700000001 }),
      createExecution("job", { execution_start_ts: 1700000002 }),
      createExecution("job", { execution_start_ts: 1700000003 }),
    ];
    const { container } = render(<ExecutionTable records={records} kind="job" tableId="t" />);
    expect(container.querySelectorAll("[data-testid='execution-row']").length).toBe(3);
  });

  // ── Status cell inline labels ──

  it("shows error type inline with status for error rows", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { status: "error", error_type: "ValueError", error_message: "Task failed" })]}
        kind="job"
        tableId="t"
      />,
    );
    expect(container.textContent).toContain("ValueError");
  });

  it("shows truncated execution ID in table row", () => {
    const uuid = "abc12345-6789-abcd-ef01-234567890abc";
    const { container } = render(
      <ExecutionTable records={[createExecution("job", { execution_id: uuid })]} kind="job" tableId="t" />,
    );
    const row = container.querySelector("[data-testid='execution-row']")!;
    expect(row.textContent).toContain("abc12345");
    expect(row.textContent).not.toContain(uuid);
  });

  // ── Expand/collapse ──

  it("clicking row expands detail panel", () => {
    const { container } = render(
      <ExecutionTable records={[createExecution("job", { execution_id: "test-uuid" })]} kind="job" tableId="t" />,
    );

    expect(container.querySelector("[data-testid='execution-detail']")).toBeNull();
    fireEvent.click(container.querySelector("[data-testid='execution-row']")!);
    expect(container.querySelector("[data-testid='execution-detail']")).not.toBeNull();
  });

  it("clicking open row again collapses it", () => {
    const { container } = render(<ExecutionTable records={[createExecution("job")]} kind="job" tableId="t" />);

    const row = container.querySelector("[data-testid='execution-row']")!;
    fireEvent.click(row);
    expect(container.querySelector("[data-testid='execution-detail']")).not.toBeNull();

    fireEvent.click(row);
    expect(container.querySelector("[data-testid='execution-detail']")).toBeNull();
  });

  // ── Detail panel content ──

  it("expanded detail shows execution id", () => {
    const uuid = "abc12345-6789-abcd-ef01-234567890abc";
    const { container } = render(
      <ExecutionTable records={[createExecution("job", { execution_id: uuid })]} kind="job" tableId="t" />,
    );

    fireEvent.click(container.querySelector("[data-testid='execution-row']")!);
    expect(container.querySelector("[data-testid='execution-detail']")!.textContent).toContain(uuid);
  });

  it("expanded detail shows traceback for error execution", () => {
    const { container } = render(
      <ExecutionTable
        records={[
          createExecution("job", {
            status: "error",
            error_traceback:
              "Traceback (most recent call last):\n  File job.py, line 10\n    some_func()\nValueError: bad value",
          }),
        ]}
        kind="job"
        tableId="t"
      />,
    );

    fireEvent.click(container.querySelector("[data-testid='execution-row']")!);
    const tb = container.querySelector("[data-testid='execution-traceback']");
    expect(tb).not.toBeNull();
    expect(tb!.textContent).toContain("File job.py, line 10");
  });

  it("expanded detail shows logs section", () => {
    const { container } = render(
      <ExecutionTable records={[createExecution("job", { execution_id: "test-uuid" })]} kind="job" tableId="t" />,
    );

    fireEvent.click(container.querySelector("[data-testid='execution-row']")!);
    expect(container.querySelector("[data-testid='execution-logs-section']")).not.toBeNull();
  });

  it("shows 'No execution ID' when execution_id is null", () => {
    const { container } = render(
      <ExecutionTable records={[createExecution("job", { execution_id: null })]} kind="job" tableId="t" />,
    );

    fireEvent.click(container.querySelector("[data-testid='execution-row']")!);
    expect(container.textContent).toContain("No execution ID");
  });

  // ── Handler-specific: context section ──

  it("shows context section for handler invocations with trigger_context_id", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("handler", { trigger_context_id: "ctx-abc-123" })]}
        kind="handler"
        tableId="invocation-table-1"
      />,
    );

    fireEvent.click(container.querySelector("[data-testid='invocation-row']")!);
    expect(container.textContent).toContain("ctx-abc-123");
  });

  it("uses invocation-detail testid for handler kind", () => {
    const { container } = render(
      <ExecutionTable records={[createExecution("handler")]} kind="handler" tableId="invocation-table-1" />,
    );

    fireEvent.click(container.querySelector("[data-testid='invocation-row']")!);
    expect(container.querySelector("[data-testid='invocation-detail']")).not.toBeNull();
  });

  // ── Show More ──

  it("shows Show More button when records exceed 5", () => {
    const records = Array.from({ length: 6 }, (_, i) => createExecution("job", { execution_start_ts: 1700000000 + i }));
    const { getByRole } = render(<ExecutionTable records={records} kind="job" tableId="t" />);
    expect(getByRole("button", { name: /show all/i })).toBeDefined();
  });

  it("does not show Show More button for 5 or fewer", () => {
    const records = Array.from({ length: 5 }, (_, i) => createExecution("job", { execution_start_ts: 1700000000 + i }));
    const { queryByRole } = render(<ExecutionTable records={records} kind="job" tableId="t" />);
    expect(queryByRole("button", { name: /show all/i })).toBeNull();
  });
});

import { fireEvent, render } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import { createExecution } from "../../test/factories";
import { ExecutionTable } from "./execution-table";

const mockNavigate = vi.fn();
vi.mock("wouter", () => ({
  useLocation: () => ["/", mockNavigate],
}));

describe("ExecutionTable", () => {
  it("renders handler empty state when records are empty", () => {
    const { getByText } = render(<ExecutionTable records={[]} kind="handler" tableId="invocation-table-1" />);
    expect(getByText("no invocations recorded")).toBeDefined();
  });

  it("renders job empty state when records are empty", () => {
    const { getByText } = render(<ExecutionTable records={[]} kind="job" tableId="execution-table-1" />);
    expect(getByText("no executions recorded.")).toBeDefined();
  });

  it("renders table with provided testid", () => {
    const { getByTestId } = render(
      <ExecutionTable records={[createExecution("job")]} kind="job" tableId="execution-table-99" />,
    );
    expect(getByTestId("execution-table-99")).toBeDefined();
  });

  it("renders unified column headers", () => {
    const { getByText } = render(<ExecutionTable records={[createExecution("job")]} kind="job" tableId="t" />);
    expect(getByText("Status")).toBeDefined();
    expect(getByText("Execution")).toBeDefined();
    expect(getByText("Duration")).toBeDefined();
    expect(getByText("Time")).toBeDefined();
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

  it("shows a 'failed' status label for error rows instead of the raw error type", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { status: "error", error_type: "ValueError", error_message: "Task failed" })]}
        kind="job"
        tableId="t"
      />,
    );
    expect(container.textContent).toContain("failed");
    expect(container.textContent).not.toContain("ValueError");
  });

  it("shows an 'ok' status label for successful rows", () => {
    const { container } = render(
      <ExecutionTable records={[createExecution("job", { status: "success" })]} kind="job" tableId="t" />,
    );
    expect(container.textContent).toContain("ok");
  });

  it("shows truncated execution ID in table row", () => {
    const uuid = "abc12345-6789-abcd-ef01-234567890abc";
    const { container } = render(
      <ExecutionTable records={[createExecution("job", { execution_id: uuid })]} kind="job" tableId="t" />,
    );
    const row = container.querySelector("[data-testid='execution-row']")!;
    expect(row.textContent).toContain("67890abc");
    expect(row.textContent).not.toContain(uuid);
  });

  it("shows thread leaked badge when thread_leaked is true on a timed-out row", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { status: "timed_out", thread_leaked: true })]}
        kind="job"
        tableId="t"
      />,
    );
    expect(container.textContent).toContain("thread leaked");
  });

  it("does not show thread leaked badge when thread_leaked is false", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { status: "timed_out", thread_leaked: false })]}
        kind="job"
        tableId="t"
      />,
    );
    expect(container.textContent).not.toContain("thread leaked");
  });

  it("shows thread leaked badge alongside timed out label on same row", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { status: "timed_out", thread_leaked: true })]}
        kind="job"
        tableId="t"
      />,
    );
    expect(container.textContent).toContain("timed out");
    expect(container.textContent).toContain("thread leaked");
  });

  it("shows manual badge when trigger_mode is manual", () => {
    const { container } = render(
      <ExecutionTable records={[createExecution("job", { trigger_mode: "manual" })]} kind="job" tableId="t" />,
    );
    expect(container.textContent).toContain("manual");
  });

  it("does not show manual badge when trigger_mode is null", () => {
    const { container } = render(
      <ExecutionTable records={[createExecution("job", { trigger_mode: null })]} kind="job" tableId="t" />,
    );
    const row = container.querySelector("[data-testid='execution-row']")!;
    expect(row.textContent).not.toContain("manual");
  });

  it("shows a cancelled label on a cancelled row", () => {
    const { container } = render(
      <ExecutionTable records={[createExecution("job", { status: "cancelled" })]} kind="job" tableId="t" />,
    );
    expect(container.textContent).toContain("cancelled");
  });

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

  it("clicking row navigates to execution detail page when execLinkPrefix is set", () => {
    mockNavigate.mockClear();
    const execId = "abc12345-6789-abcd-ef01-234567890abc";
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { execution_id: execId })]}
        kind="job"
        tableId="t"
        execLinkPrefix="/apps/my_app/handlers/job/1"
      />,
    );
    fireEvent.click(container.querySelector("[data-testid='execution-row']")!);
    expect(mockNavigate).toHaveBeenCalledWith(`/apps/my_app/handlers/job/1/exec/${execId}`);
  });

  it("clicking row does not navigate when execLinkPrefix is not set", () => {
    mockNavigate.mockClear();
    const { container } = render(
      <ExecutionTable records={[createExecution("job", { execution_id: "some-id" })]} kind="job" tableId="t" />,
    );
    fireEvent.click(container.querySelector("[data-testid='execution-row']")!);
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});

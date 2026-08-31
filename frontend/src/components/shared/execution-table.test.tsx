import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createExecution } from "../../test/factories";
import { createWouterMock } from "../../test/mock-wouter";
import { formatTimestamp } from "../../utils/format";
import { ExecutionTable } from "./execution-table";

const mockNavigate = vi.fn();
vi.mock("wouter", () => createWouterMock({ useLocation: () => ["/", mockNavigate] }));

describe("ExecutionTable", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

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

  it("shows the full execution ID in table rows", () => {
    const uuid = "abc12345-6789-abcd-ef01-234567890abc";
    const { container } = render(
      <ExecutionTable records={[createExecution("job", { execution_id: uuid })]} kind="job" tableId="t" />,
    );
    const row = container.querySelector("[data-testid='execution-row']")!;
    expect(row.textContent).toContain(uuid);
  });

  it("renders formatted duration, relative time, and timestamp tooltip", () => {
    const now = 1_700_000_600;
    const executionStart = 1_700_000_000;
    vi.useFakeTimers();
    vi.setSystemTime(now * 1000);

    const { getByTestId, getByText } = render(
      <ExecutionTable
        records={[createExecution("job", { duration_ms: 1234, execution_start_ts: executionStart })]}
        kind="job"
        tableId="t"
      />,
    );
    const timeCell = getByTestId("execution-row").querySelector("td[title]");

    expect(getByText("1.2s")).toBeDefined();
    expect(timeCell?.textContent).toBe("10m ago");
    expect(timeCell?.getAttribute("title")).toBe(formatTimestamp(executionStart));
  });

  it("renders a complete details icon for navigable rows", () => {
    const { getByTestId } = render(
      <ExecutionTable
        records={[createExecution("job", { execution_id: "execution-id" })]}
        kind="job"
        tableId="t"
        appKey="my_app"
        handlerKind="job"
        handlerId={1}
      />,
    );

    expect(getByTestId("execution-detail-indicator").querySelector("svg")).not.toBeNull();
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

  it("clicking row navigates to execution detail page when handler props are set", async () => {
    const user = userEvent.setup();
    mockNavigate.mockClear();
    const execId = "abc12345-6789-abcd-ef01-234567890abc";
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { execution_id: execId })]}
        kind="job"
        tableId="t"
        appKey="my_app"
        handlerKind="job"
        handlerId={1}
      />,
    );
    await user.click(container.querySelector("[data-testid='execution-row']")!);
    expect(mockNavigate).toHaveBeenCalledWith(`/apps/my_app/handlers/job/1/exec/${execId}`);
  });

  it("renders no detail affordances or navigation when handler props are not set", async () => {
    const user = userEvent.setup();
    mockNavigate.mockClear();
    const { getByTestId, queryByLabelText, queryByTestId } = render(
      <ExecutionTable records={[createExecution("job", { execution_id: "some-id" })]} kind="job" tableId="t" />,
    );
    const row = getByTestId("execution-row");

    expect(queryByTestId("execution-detail-indicator")).toBeNull();
    expect(queryByLabelText("View execution detail")).toBeNull();

    await user.click(row);
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("moves the roving tabindex between rows with arrow keys", async () => {
    const user = userEvent.setup();
    const records = [
      createExecution("job", { execution_start_ts: 1700000001 }),
      createExecution("job", { execution_start_ts: 1700000002 }),
    ];
    const { container } = render(<ExecutionTable records={records} kind="job" tableId="t" />);
    const rows = container.querySelectorAll<HTMLElement>("[data-testid='execution-row']");

    expect(rows[0].tabIndex).toBe(0);
    expect(rows[1].tabIndex).toBe(-1);

    rows[0].focus();
    await user.keyboard("{ArrowDown}");

    expect(rows[0].tabIndex).toBe(-1);
    expect(rows[1].tabIndex).toBe(0);
    expect(document.activeElement).toBe(rows[1]);
  });

  it("activating a row with the keyboard navigates to execution detail page", async () => {
    const user = userEvent.setup();
    mockNavigate.mockClear();
    const execId = "abc12345-6789-abcd-ef01-234567890abc";
    const { getByTestId } = render(
      <ExecutionTable
        records={[createExecution("job", { execution_id: execId })]}
        kind="job"
        tableId="t"
        appKey="my_app"
        handlerKind="job"
        handlerId={1}
      />,
    );

    getByTestId("execution-row").focus();
    await user.keyboard("{Enter}");

    expect(mockNavigate).toHaveBeenCalledWith(`/apps/my_app/handlers/job/1/exec/${execId}`);
  });
});

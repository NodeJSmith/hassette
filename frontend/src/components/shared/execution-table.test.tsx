import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createExecution } from "../../test/factories";
import { createWouterMock } from "../../test/mock-wouter";
import { formatTimestamp } from "../../utils/format";
import { ExecutionTable } from "./execution-table";

const INCIDENTAL_TABLE_ID = "t";
const TEST_EXECUTION_ID = "abc12345-6789-abcd-ef01-234567890abc";
const BASE_TS = 1_700_000_000;
const TEN_MINUTES_IN_SECONDS = 600;
const NAVIGABLE_PROPS = { appKey: "my_app", handlerKind: "job", handlerId: 1 } as const;
const EXPECTED_DETAIL_PATH = `/apps/${NAVIGABLE_PROPS.appKey}/handlers/${NAVIGABLE_PROPS.handlerKind}/${NAVIGABLE_PROPS.handlerId}/exec/${TEST_EXECUTION_ID}`;

const mockNavigate = vi.fn();
vi.mock("wouter", () => createWouterMock({ useLocation: () => ["/", mockNavigate] }));

describe("ExecutionTable", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders handler empty state when records are empty", () => {
    const { getByText } = render(<ExecutionTable records={[]} kind="handler" tableId={INCIDENTAL_TABLE_ID} />);
    expect(getByText("no invocations recorded")).toBeDefined();
  });

  it("renders job empty state when records are empty", () => {
    const { getByText } = render(<ExecutionTable records={[]} kind="job" tableId={INCIDENTAL_TABLE_ID} />);
    expect(getByText("no executions recorded.")).toBeDefined();
  });

  it("renders table with provided testid", () => {
    const { getByTestId } = render(
      <ExecutionTable records={[createExecution("job")]} kind="job" tableId="execution-table-99" />,
    );
    expect(getByTestId("execution-table-99")).toBeDefined();
  });

  it("renders unified column headers", () => {
    const { getByText } = render(
      <ExecutionTable records={[createExecution("job")]} kind="job" tableId={INCIDENTAL_TABLE_ID} />,
    );
    expect(getByText("Status")).toBeDefined();
    expect(getByText("Execution")).toBeDefined();
    expect(getByText("Duration")).toBeDefined();
    expect(getByText("Time")).toBeDefined();
  });

  it("renders correct number of rows", () => {
    const records = [
      createExecution("job", { execution_start_ts: BASE_TS + 1 }),
      createExecution("job", { execution_start_ts: BASE_TS + 2 }),
      createExecution("job", { execution_start_ts: BASE_TS + 3 }),
    ];
    const { container } = render(<ExecutionTable records={records} kind="job" tableId={INCIDENTAL_TABLE_ID} />);
    expect(container.querySelectorAll("[data-testid='execution-row']").length).toBe(3);
  });

  it("shows a 'failed' status label for error rows instead of the raw error type", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { status: "error", error_type: "ValueError", error_message: "Task failed" })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
      />,
    );
    expect(container.textContent).toContain("failed");
    expect(container.textContent).not.toContain("ValueError");
  });

  it("shows an 'ok' status label for successful rows", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { status: "success" })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
      />,
    );
    expect(container.textContent).toContain("ok");
  });

  it("shows the full execution ID in table rows", () => {
    const { getByTestId } = render(
      <ExecutionTable
        records={[createExecution("job", { execution_id: TEST_EXECUTION_ID })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
      />,
    );
    expect(getByTestId("execution-row").textContent).toContain(TEST_EXECUTION_ID);
  });

  it("renders formatted duration, relative time, and timestamp tooltip", () => {
    const executionStart = BASE_TS;
    const now = BASE_TS + TEN_MINUTES_IN_SECONDS;
    vi.useFakeTimers();
    vi.setSystemTime(now * 1000);

    const { getByTestId, getByText } = render(
      <ExecutionTable
        records={[createExecution("job", { duration_ms: 1234, execution_start_ts: executionStart })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
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
        tableId={INCIDENTAL_TABLE_ID}
        {...NAVIGABLE_PROPS}
      />,
    );

    expect(getByTestId("execution-detail-indicator").querySelector("svg")).not.toBeNull();
  });

  it("shows thread leaked badge when thread_leaked is true on a timed-out row", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { status: "timed_out", thread_leaked: true })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
      />,
    );
    expect(container.textContent).toContain("thread leaked");
  });

  it("does not show thread leaked badge when thread_leaked is false", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { status: "timed_out", thread_leaked: false })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
      />,
    );
    expect(container.textContent).not.toContain("thread leaked");
  });

  it("shows thread leaked badge alongside timed out label on same row", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { status: "timed_out", thread_leaked: true })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
      />,
    );
    expect(container.textContent).toContain("timed out");
    expect(container.textContent).toContain("thread leaked");
  });

  it("shows manual badge when trigger_mode is manual", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { trigger_mode: "manual" })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
      />,
    );
    expect(container.textContent).toContain("manual");
  });

  it("does not show manual badge when trigger_mode is null", () => {
    const { getByTestId } = render(
      <ExecutionTable
        records={[createExecution("job", { trigger_mode: null })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
      />,
    );
    expect(getByTestId("execution-row").textContent).not.toContain("manual");
  });

  it("shows a cancelled label on a cancelled row", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { status: "cancelled" })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
      />,
    );
    expect(container.textContent).toContain("cancelled");
  });

  it("shows a skipped label on a skipped row", () => {
    const { container } = render(
      <ExecutionTable
        records={[createExecution("job", { status: "skipped" })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
      />,
    );
    expect(container.textContent).toContain("skipped");
  });

  it("shows Show More button when records exceed 5", () => {
    const records = Array.from({ length: 6 }, (_, i) => createExecution("job", { execution_start_ts: BASE_TS + i }));
    const { getByRole } = render(<ExecutionTable records={records} kind="job" tableId={INCIDENTAL_TABLE_ID} />);
    expect(getByRole("button", { name: /show all/i })).toBeDefined();
  });

  it("clicking Show More reveals the remaining rows and flips the button to Show less", async () => {
    const user = userEvent.setup();
    const records = Array.from({ length: 6 }, (_, i) => createExecution("job", { execution_start_ts: BASE_TS + i }));
    const { container, getByRole } = render(
      <ExecutionTable records={records} kind="job" tableId={INCIDENTAL_TABLE_ID} />,
    );
    expect(container.querySelectorAll("[data-testid='execution-row']").length).toBe(5);

    await user.click(getByRole("button", { name: /show all/i }));
    expect(container.querySelectorAll("[data-testid='execution-row']").length).toBe(6);

    await user.click(getByRole("button", { name: /show less/i }));
    expect(container.querySelectorAll("[data-testid='execution-row']").length).toBe(5);
  });

  it("does not show Show More button for 5 or fewer", () => {
    const records = Array.from({ length: 5 }, (_, i) => createExecution("job", { execution_start_ts: BASE_TS + i }));
    const { queryByRole } = render(<ExecutionTable records={records} kind="job" tableId={INCIDENTAL_TABLE_ID} />);
    expect(queryByRole("button", { name: /show all/i })).toBeNull();
  });

  it("clicking row navigates to execution detail page when handler props are set", async () => {
    const user = userEvent.setup();
    const { getByTestId } = render(
      <ExecutionTable
        records={[createExecution("job", { execution_id: TEST_EXECUTION_ID })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
        {...NAVIGABLE_PROPS}
      />,
    );
    await user.click(getByTestId("execution-row"));
    expect(mockNavigate).toHaveBeenCalledWith(EXPECTED_DETAIL_PATH);
  });

  it("renders no detail affordances or navigation when handler props are not set", async () => {
    const user = userEvent.setup();
    const { getByTestId, queryByLabelText, queryByTestId } = render(
      <ExecutionTable
        records={[createExecution("job", { execution_id: "some-id" })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
      />,
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
      createExecution("job", { execution_start_ts: BASE_TS + 1 }),
      createExecution("job", { execution_start_ts: BASE_TS + 2 }),
    ];
    const { container } = render(<ExecutionTable records={records} kind="job" tableId={INCIDENTAL_TABLE_ID} />);
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
    const { getByTestId } = render(
      <ExecutionTable
        records={[createExecution("job", { execution_id: TEST_EXECUTION_ID })]}
        kind="job"
        tableId={INCIDENTAL_TABLE_ID}
        {...NAVIGABLE_PROPS}
      />,
    );

    getByTestId("execution-row").focus();
    await user.keyboard("{Enter}");

    expect(mockNavigate).toHaveBeenCalledWith(EXPECTED_DETAIL_PATH);
  });
});

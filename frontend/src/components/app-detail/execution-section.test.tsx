import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ExecutionRecord } from "../shared/execution-table";
import { ExecutionSection } from "./execution-section";

vi.mock("../shared/execution-table", async () => {
  const actual = await vi.importActual<typeof import("../shared/execution-table")>("../shared/execution-table");
  return {
    ...actual,
    ExecutionTable: vi.fn((props: { records: ExecutionRecord[]; tableId: string }) => (
      <div data-testid="mock-execution-table" data-record-count={props.records.length} data-table-id={props.tableId}>
        execution table
      </div>
    )),
  };
});

const { ExecutionTable } = await import("../shared/execution-table");

const RECORD: ExecutionRecord = {
  execution_start_ts: 1_700_000_000,
  duration_ms: 12,
  status: "success",
  error_type: null,
  error_message: null,
  thread_leaked: false,
};

describe("ExecutionSection", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the heading text", () => {
    const { getByRole } = render(
      <ExecutionSection heading="Executions" records={[]} kind="handler" tableId="table-1" loading={false} />,
    );
    expect(getByRole("heading", { level: 3 }).textContent).toBe("Executions");
  });

  it("shows a spinner when loading and records is undefined", () => {
    const { getByTestId, queryByTestId } = render(
      <ExecutionSection heading="Executions" records={undefined} kind="handler" tableId="table-1" loading={true} />,
    );
    expect(getByTestId("spinner")).not.toBeNull();
    expect(queryByTestId("mock-execution-table")).toBeNull();
  });

  it("shows the ExecutionTable when records is an empty array (loaded but empty)", () => {
    const { getByTestId, queryByTestId } = render(
      <ExecutionSection heading="Executions" records={[]} kind="handler" tableId="table-1" loading={true} />,
    );
    expect(queryByTestId("spinner")).toBeNull();
    expect(getByTestId("mock-execution-table").getAttribute("data-record-count")).toBe("0");
  });

  it("shows the ExecutionTable when records exist, even if loading", () => {
    const { getByTestId, queryByTestId } = render(
      <ExecutionSection heading="Executions" records={[RECORD]} kind="handler" tableId="table-1" loading={true} />,
    );
    expect(queryByTestId("spinner")).toBeNull();
    expect(getByTestId("mock-execution-table").getAttribute("data-record-count")).toBe("1");
  });

  it("passes the correct props to ExecutionTable", () => {
    render(
      <ExecutionSection
        heading="Executions"
        records={[RECORD]}
        kind="job"
        tableId="table-42"
        loading={false}
        appKey="my_app"
        handlerKind="listener"
        handlerId={7}
        instanceQs="?instance=0"
      />,
    );

    // React calls function components with only a props argument (no Preact-style second
    // "context" argument), so the second call arg is undefined here.
    expect(ExecutionTable).toHaveBeenCalledWith(
      expect.objectContaining({
        records: [RECORD],
        kind: "job",
        tableId: "table-42",
        appKey: "my_app",
        handlerKind: "listener",
        handlerId: 7,
        instanceQs: "?instance=0",
      }),
      undefined,
    );
  });
});

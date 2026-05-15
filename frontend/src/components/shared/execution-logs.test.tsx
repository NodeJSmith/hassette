import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { ExecutionLogs } from "./execution-logs";

vi.mock("./log-table", () => ({
  LogTable: ({
    executionId,
    context,
    useLocalState,
  }: {
    executionId?: string;
    context?: string;
    useLocalState?: boolean;
  }) => (
    <div
      data-testid="log-table-stub"
      data-execution-id={executionId ?? ""}
      data-context={context ?? "global"}
      data-use-local-state={String(!!useLocalState)}
    />
  ),
}));

describe("ExecutionLogs", () => {
  it("renders LogTable with executionId prop", () => {
    const { getByTestId } = render(<ExecutionLogs executionId="test-exec-id" />);
    const stub = getByTestId("log-table-stub");
    expect(stub.getAttribute("data-execution-id")).toBe("test-exec-id");
  });

  it("passes correct props to LogTable", () => {
    const { getByTestId } = render(<ExecutionLogs executionId="test-id" />);
    const stub = getByTestId("log-table-stub");
    expect(stub.getAttribute("data-context")).toBe("execution");
    expect(stub.getAttribute("data-use-local-state")).toBe("true");
  });

  it("renders view-all-logs link with correct href", () => {
    const { getByTestId } = render(<ExecutionLogs executionId="abc-123" />);
    const link = getByTestId("view-all-logs-link") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/logs?execution_id=abc-123");
  });

  it("renders execution-logs-section wrapper", () => {
    const { getByTestId } = render(<ExecutionLogs executionId="test-id" />);
    expect(getByTestId("execution-logs-section")).toBeDefined();
  });
});

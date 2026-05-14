import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { ExecutionLogs } from "./execution-logs";

vi.mock("./log-table", () => ({
  LogTable: ({
    executionId,
    mode,
    useLocalState,
    hideTitle,
    showAppColumn,
  }: {
    executionId?: string;
    mode?: string;
    useLocalState?: boolean;
    hideTitle?: boolean;
    showAppColumn?: boolean;
  }) => (
    <div
      data-testid="log-table-stub"
      data-execution-id={executionId ?? ""}
      data-mode={mode ?? "live"}
      data-use-local-state={String(!!useLocalState)}
      data-hide-title={String(!!hideTitle)}
      data-show-app-column={String(!!showAppColumn)}
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
    expect(stub.getAttribute("data-mode")).toBe("live");
    expect(stub.getAttribute("data-use-local-state")).toBe("true");
    expect(stub.getAttribute("data-hide-title")).toBe("true");
    expect(stub.getAttribute("data-show-app-column")).toBe("false");
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

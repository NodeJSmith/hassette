import { describe, expect, it } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { JobExecutions } from "./job-executions";
import { createExecution } from "../../test/factories";

describe("JobExecutions", () => {
  it("renders 'No executions recorded' when executions array is empty", () => {
    const { getByText } = render(
      <JobExecutions executions={[]} jobId={1} />,
    );
    expect(getByText("no executions recorded.")).toBeDefined();
  });

  it("renders table with testid matching jobId", () => {
    const { getByTestId } = render(
      <JobExecutions executions={[createExecution()]} jobId={99} />,
    );
    expect(getByTestId("execution-table-99")).toBeDefined();
  });

  it("renders Status, Timestamp, Duration, and Error column headers", () => {
    const { getByText } = render(
      <JobExecutions executions={[createExecution()]} jobId={1} />,
    );
    expect(getByText("Status")).toBeDefined();
    expect(getByText("Timestamp")).toBeDefined();
    expect(getByText("Duration")).toBeDefined();
    expect(getByText("Error")).toBeDefined();
  });

  it("renders execution row with status shape", () => {
    const { container } = render(
      <JobExecutions executions={[createExecution({ status: "success" })]} jobId={1} />,
    );
    const row = container.querySelector("[data-testid='execution-row']");
    expect(row).not.toBeNull();
  });

  it("renders error message in error column", () => {
    const { getAllByText } = render(
      <JobExecutions
        executions={[createExecution({ status: "error", error_message: "Task failed" })]}
        jobId={1}
      />,
    );
    expect(getAllByText("Task failed").length).toBeGreaterThanOrEqual(1);
  });

  it("clicking execution row expands detail panel", () => {
    const { container } = render(
      <JobExecutions
        executions={[createExecution({ execution_id: "test-uuid-123" })]}
        jobId={1}
      />,
    );

    expect(container.querySelector("[data-testid='execution-detail']")).toBeNull();

    const row = container.querySelector("[data-testid='execution-row']") as HTMLElement;
    fireEvent.click(row);

    expect(container.querySelector("[data-testid='execution-detail']")).not.toBeNull();
  });

  it("expanded detail shows execution id", () => {
    const uuid = "abc12345-6789-abcd-ef01-234567890abc";
    const { container } = render(
      <JobExecutions
        executions={[createExecution({ execution_id: uuid })]}
        jobId={1}
      />,
    );

    const row = container.querySelector("[data-testid='execution-row']") as HTMLElement;
    fireEvent.click(row);

    const detail = container.querySelector("[data-testid='execution-detail']");
    expect(detail!.textContent).toContain(uuid);
  });

  it("expanded detail shows traceback for error execution", () => {
    const { container } = render(
      <JobExecutions
        executions={[
          createExecution({
            status: "error",
            error_traceback: "Traceback (most recent call last):\n  File job.py, line 10",
          }),
        ]}
        jobId={1}
      />,
    );

    const row = container.querySelector("[data-testid='execution-row']") as HTMLElement;
    fireEvent.click(row);

    const tb = container.querySelector("[data-testid='execution-traceback']");
    expect(tb).not.toBeNull();
    expect(tb!.textContent).toContain("Traceback (most recent call last)");
  });

  it("expanded detail shows logs section", () => {
    const { container } = render(
      <JobExecutions
        executions={[createExecution({ execution_id: "test-uuid" })]}
        jobId={1}
      />,
    );

    const row = container.querySelector("[data-testid='execution-row']") as HTMLElement;
    fireEvent.click(row);

    expect(container.querySelector("[data-testid='execution-logs-section']")).not.toBeNull();
  });

  it("shows Show More button when executions exceed 5", () => {
    const executions = Array.from({ length: 6 }, (_, i) =>
      createExecution({ execution_start_ts: 1700000000 + i }),
    );
    const { getByRole } = render(
      <JobExecutions executions={executions} jobId={1} />,
    );
    expect(getByRole("button", { name: /show all/i })).toBeDefined();
  });

  it("does not show Show More button for 5 or fewer executions", () => {
    const executions = Array.from({ length: 5 }, (_, i) =>
      createExecution({ execution_start_ts: 1700000000 + i }),
    );
    const { queryByRole } = render(
      <JobExecutions executions={executions} jobId={1} />,
    );
    expect(queryByRole("button", { name: /show all/i })).toBeNull();
  });

  it("renders Trace ID column header", () => {
    const { getByText } = render(
      <JobExecutions executions={[createExecution()]} jobId={1} />,
    );
    expect(getByText("Trace ID")).toBeDefined();
  });

  it("clicking expanded row again collapses it", () => {
    const { container } = render(
      <JobExecutions executions={[createExecution()]} jobId={1} />,
    );

    const row = container.querySelector("[data-testid='execution-row']") as HTMLElement;
    fireEvent.click(row);
    expect(container.querySelector("[data-testid='execution-detail']")).not.toBeNull();

    fireEvent.click(row);
    expect(container.querySelector("[data-testid='execution-detail']")).toBeNull();
  });

  it("renders dash for null execution_id in detail", () => {
    const { container } = render(
      <JobExecutions
        executions={[createExecution({ execution_id: null })]}
        jobId={1}
      />,
    );

    const row = container.querySelector("[data-testid='execution-row']") as HTMLElement;
    fireEvent.click(row);

    expect(container.querySelector("[data-testid='execution-logs-section']")!.textContent).toContain("No execution ID");
  });
});

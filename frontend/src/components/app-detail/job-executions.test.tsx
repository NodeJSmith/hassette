import { describe, expect, it } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { JobExecutions } from "./job-executions";
import type { JobExecutionData } from "../../api/endpoints";

function createExecution(overrides: Partial<JobExecutionData> = {}): JobExecutionData {
  return {
    execution_start_ts: 1700000000,
    duration_ms: 75,
    status: "success",
    source_tier: "app",
    error_type: null,
    error_message: null,
    error_traceback: null,
    ...overrides,
  };
}

describe("JobExecutions", () => {
  it("renders 'No executions recorded' when executions array is empty", () => {
    const { getByText } = render(
      <JobExecutions executions={[]} jobId={1} />,
    );
    expect(getByText("No executions recorded.")).toBeDefined();
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

  it("renders success badge for successful execution", () => {
    const { container } = render(
      <JobExecutions executions={[createExecution({ status: "success" })]} jobId={1} />,
    );
    const badge = container.querySelector(".ht-badge--success");
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toBe("success");
  });

  it("renders danger badge for failed execution", () => {
    const { container } = render(
      <JobExecutions
        executions={[createExecution({ status: "error", error_message: "Timeout" })]}
        jobId={1}
      />,
    );
    const badge = container.querySelector(".ht-badge--danger");
    expect(badge).not.toBeNull();
  });

  it("renders error message in error column", () => {
    const { getByText } = render(
      <JobExecutions
        executions={[createExecution({ status: "error", error_message: "Task failed" })]}
        jobId={1}
      />,
    );
    expect(getByText("Task failed")).toBeDefined();
  });

  it("shows traceback toggle button when error_traceback is present", () => {
    const { getByRole } = render(
      <JobExecutions
        executions={[
          createExecution({
            status: "error",
            error_message: "Boom",
            error_traceback: "Traceback (most recent call last):\n  File job.py",
          }),
        ]}
        jobId={1}
      />,
    );
    expect(getByRole("button", { name: /traceback/i })).toBeDefined();
  });

  it("clicking traceback button reveals execution-traceback pre element", () => {
    const { getByRole, container } = render(
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

    expect(container.querySelector("[data-testid='execution-traceback']")).toBeNull();

    fireEvent.click(getByRole("button", { name: /traceback/i }));

    const pre = container.querySelector("[data-testid='execution-traceback']");
    expect(pre).not.toBeNull();
    expect(pre!.textContent).toContain("Traceback (most recent call last)");
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

  it("renders dash in error column for successful execution", () => {
    const { container } = render(
      <JobExecutions
        executions={[createExecution({ status: "success", error_message: null })]}
        jobId={1}
      />,
    );
    expect(container.textContent).toContain("—");
  });

  it("renders multiple tbody rows for multiple executions", () => {
    const executions = [
      createExecution({ execution_start_ts: 1700000001 }),
      createExecution({ execution_start_ts: 1700000002 }),
    ];
    const { container } = render(
      <JobExecutions executions={executions} jobId={1} />,
    );
    const rows = container.querySelectorAll("tbody tr");
    expect(rows.length).toBe(2);
  });
});

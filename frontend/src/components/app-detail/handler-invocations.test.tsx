import { describe, expect, it } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { HandlerInvocations } from "./handler-invocations";
import type { HandlerInvocationData } from "../../api/endpoints";

function createInvocation(overrides: Partial<HandlerInvocationData> = {}): HandlerInvocationData {
  return {
    execution_start_ts: 1700000000,
    duration_ms: 50,
    status: "success",
    source_tier: "app",
    error_type: null,
    error_message: null,
    error_traceback: null,
    ...overrides,
  };
}

describe("HandlerInvocations", () => {
  it("renders 'No invocations recorded' when invocations array is empty", () => {
    const { getByText } = render(
      <HandlerInvocations invocations={[]} listenerId={1} />,
    );
    expect(getByText("No invocations recorded.")).toBeDefined();
  });

  it("renders table with testid matching listenerId", () => {
    const { getByTestId } = render(
      <HandlerInvocations invocations={[createInvocation()]} listenerId={42} />,
    );
    expect(getByTestId("invocation-table-42")).toBeDefined();
  });

  it("renders Status, Timestamp, Duration, and Error column headers", () => {
    const { getByText } = render(
      <HandlerInvocations invocations={[createInvocation()]} listenerId={1} />,
    );
    expect(getByText("Status")).toBeDefined();
    expect(getByText("Timestamp")).toBeDefined();
    expect(getByText("Duration")).toBeDefined();
    expect(getByText("Error")).toBeDefined();
  });

  it("renders success badge for successful invocation", () => {
    const { container } = render(
      <HandlerInvocations invocations={[createInvocation({ status: "success" })]} listenerId={1} />,
    );
    const badge = container.querySelector(".ht-badge--success");
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toBe("success");
  });

  it("renders danger badge for failed invocation", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ status: "error", error_message: "boom" })]}
        listenerId={1}
      />,
    );
    const badge = container.querySelector(".ht-badge--danger");
    expect(badge).not.toBeNull();
  });

  it("renders error message in error column", () => {
    const { getByText } = render(
      <HandlerInvocations
        invocations={[createInvocation({ status: "error", error_message: "Connection refused" })]}
        listenerId={1}
      />,
    );
    expect(getByText("Connection refused")).toBeDefined();
  });

  it("shows traceback toggle button when error_traceback is present", () => {
    const { getByRole } = render(
      <HandlerInvocations
        invocations={[
          createInvocation({
            status: "error",
            error_message: "Something failed",
            error_traceback: "Traceback (most recent call last):\n  File test.py",
          }),
        ]}
        listenerId={1}
      />,
    );
    const btn = getByRole("button", { name: /traceback/i });
    expect(btn).toBeDefined();
  });

  it("clicking traceback button expands the traceback row", () => {
    const { getByRole, container } = render(
      <HandlerInvocations
        invocations={[
          createInvocation({
            status: "error",
            error_traceback: "Traceback (most recent call last):\n  File test.py, line 1",
          }),
        ]}
        listenerId={1}
      />,
    );

    expect(container.querySelector("[data-testid='invocation-traceback']")).toBeNull();

    fireEvent.click(getByRole("button", { name: /traceback/i }));

    const pre = container.querySelector("[data-testid='invocation-traceback']");
    expect(pre).not.toBeNull();
    expect(pre!.textContent).toContain("Traceback (most recent call last)");
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

  it("shows dash in error column for successful invocation with no message", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ status: "success", error_message: null })]}
        listenerId={1}
      />,
    );
    // The ErrorCell renders "—" for no message and no traceback
    expect(container.textContent).toContain("—");
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
    const rows = container.querySelectorAll("tbody tr");
    expect(rows.length).toBe(3);
  });
});

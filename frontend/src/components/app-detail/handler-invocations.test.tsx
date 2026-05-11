import { describe, expect, it } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { HandlerInvocations } from "./handler-invocations";
import { createInvocation } from "../../test/factories";

describe("HandlerInvocations", () => {
  it("renders empty state when invocations array is empty", () => {
    const { getByText } = render(
      <HandlerInvocations invocations={[]} listenerId={1} />,
    );
    expect(getByText("no invocations recorded")).toBeDefined();
  });

  it("renders table with testid matching listenerId", () => {
    const { getByTestId } = render(
      <HandlerInvocations invocations={[createInvocation()]} listenerId={42} />,
    );
    expect(getByTestId("invocation-table-42")).toBeDefined();
  });

  it("renders Time, Trigger, Duration, and Note column headers", () => {
    const { getByText } = render(
      <HandlerInvocations invocations={[createInvocation()]} listenerId={1} />,
    );
    expect(getByText("Time")).toBeDefined();
    expect(getByText("Trigger")).toBeDefined();
    expect(getByText("Duration")).toBeDefined();
    expect(getByText("Note")).toBeDefined();
  });

  it("renders error message in note column", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ status: "error", error_message: "Connection refused" })]}
        listenerId={1}
      />,
    );
    expect(container.textContent).toContain("Connection refused");
  });

  it("clicking row expands invocation detail with traceback", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[
          createInvocation({
            status: "error",
            error_message: "Something failed",
            error_traceback: "Traceback (most recent call last):\n  File test.py, line 1",
          }),
        ]}
        listenerId={1}
      />,
    );

    expect(container.querySelector("[data-testid='invocation-detail']")).toBeNull();

    const row = container.querySelector(".ht-inv-row");
    expect(row).not.toBeNull();
    fireEvent.click(row!);

    const detail = container.querySelector("[data-testid='invocation-detail']");
    expect(detail).not.toBeNull();
    expect(detail!.textContent).toContain("Traceback (most recent call last)");
  });

  it("clicking open row again collapses the detail", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ status: "error", error_traceback: "tb" })]}
        listenerId={1}
      />,
    );

    const row = container.querySelector(".ht-inv-row")!;
    fireEvent.click(row);
    expect(container.querySelector("[data-testid='invocation-detail']")).not.toBeNull();

    fireEvent.click(row);
    expect(container.querySelector("[data-testid='invocation-detail']")).toBeNull();
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

  it("renders multiple rows for multiple invocations", () => {
    const invocations = [
      createInvocation({ execution_start_ts: 1700000001 }),
      createInvocation({ execution_start_ts: 1700000002 }),
      createInvocation({ execution_start_ts: 1700000003 }),
    ];
    const { container } = render(
      <HandlerInvocations invocations={invocations} listenerId={1} />,
    );
    const rows = container.querySelectorAll(".ht-inv-row");
    expect(rows.length).toBe(3);
  });

  it("renders trigger origin in trigger column", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ trigger_origin: "REMOTE", trigger_context_id: "ctx-1" })]}
        listenerId={1}
      />,
    );
    expect(container.textContent).toContain("REMOTE");
  });

  it("shows context ID in expanded detail", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ trigger_context_id: "ctx-abc-123" })]}
        listenerId={1}
      />,
    );
    fireEvent.click(container.querySelector(".ht-inv-row")!);
    expect(container.textContent).toContain("ctx-abc-123");
  });

  it("expanded detail shows 2-column grid for execution ID and result", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ execution_id: "exec-123" })]}
        listenerId={1}
      />,
    );
    fireEvent.click(container.querySelector(".ht-inv-row")!);
    const grid = container.querySelector(".ht-inv-detail__grid");
    expect(grid).not.toBeNull();
    expect(container.textContent).toContain("exec-123");
  });
});

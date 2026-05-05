import { describe, expect, it } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { HandlerInvocations } from "./handler-invocations";
import { createInvocation } from "../../test/factories";

describe("HandlerInvocations", () => {
  it("renders 'No invocations recorded' when invocations array is empty", () => {
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

  it("renders Status, Time, Trigger, Duration, and Note column headers", () => {
    const { getByText } = render(
      <HandlerInvocations invocations={[createInvocation()]} listenerId={1} />,
    );
    expect(getByText("Status")).toBeDefined();
    expect(getByText("Time")).toBeDefined();
    expect(getByText("Trigger")).toBeDefined();
    expect(getByText("Duration")).toBeDefined();
    expect(getByText("Note")).toBeDefined();
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

  it("renders error message in note column", () => {
    const { getAllByText } = render(
      <HandlerInvocations
        invocations={[createInvocation({ status: "error", error_message: "Connection refused" })]}
        listenerId={1}
      />,
    );
    expect(getAllByText("Connection refused").length).toBeGreaterThanOrEqual(1);
  });

  it("clicking error note with traceback expands the traceback row", () => {
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

    expect(container.querySelector("[data-testid='invocation-traceback']")).toBeNull();

    const expandable = container.querySelector(".ht-invocation-note--expandable");
    expect(expandable).not.toBeNull();
    fireEvent.click(expandable!);

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

  it("renders trigger origin in Trigger column", () => {
    const { container } = render(
      <HandlerInvocations invocations={[createInvocation({ trigger_origin: "LOCAL", trigger_context_id: "ctx-1" })]} listenerId={1} />,
    );
    expect(container.textContent).toContain("LOCAL");
  });

  it("shows trigger context in Trigger column with title", () => {
    const uuid = "deadbeef-1234-5678-90ab-cdef01234567";
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ trigger_context_id: uuid, trigger_origin: "LOCAL" })]}
        listenerId={1}
      />,
    );
    const cell = container.querySelector("[title='" + uuid + "']");
    expect(cell).not.toBeNull();
    expect(cell!.textContent).toBe("LOCAL");
  });

  it("renders trigger_origin in trigger column", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[createInvocation({ trigger_origin: "LOCAL", trigger_context_id: "ctx-abc" })]}
        listenerId={1}
      />,
    );
    expect(container.textContent).toContain("LOCAL");
  });

  it("traceback row spans all 5 columns", () => {
    const { container } = render(
      <HandlerInvocations
        invocations={[
          createInvocation({
            status: "error",
            error_message: "Something broke",
            error_traceback: "Traceback (most recent call last):\n  File test.py, line 1",
          }),
        ]}
        listenerId={1}
      />,
    );
    const expandable = container.querySelector(".ht-invocation-note--expandable");
    expect(expandable).not.toBeNull();
    fireEvent.click(expandable!);
    const tbRow = container.querySelector(".ht-traceback-row td");
    expect(tbRow).not.toBeNull();
    expect(tbRow!.getAttribute("colspan")).toBe("5");
  });
});

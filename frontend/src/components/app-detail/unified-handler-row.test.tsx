import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { JobData, ListenerData } from "../../api/endpoints";
import { createJob, createListener } from "../../test/factories";
import type { StatusKind } from "../../utils/status";
import { UnifiedHandlerRow, type UnifiedItem } from "./unified-handler-row";

const TESTID_SUBLINE_ERR = "handler-row-subline-err";
const TESTID_MODE_CHIP = "handler-row-mode-chip";
const TESTID_NEXT_RUN = "handler-row-next-run";
const TESTID_SCHEDULE_STATUS_BADGE = "schedule-status-badge";

function rowTestId(kind: "listener" | "job", id: number) {
  return `unified-row-${kind}-${id}`;
}

interface ItemOverrides {
  name?: string;
  humanDescription?: string | null;
  statusKind?: StatusKind;
}

interface RowPropOverrides {
  isSelected?: boolean;
  onSelect?: () => void;
}

function noop() {}

function renderRow(item: UnifiedItem, overrides: RowPropOverrides = {}) {
  return render(<UnifiedHandlerRow item={item} isSelected={false} onSelect={noop} {...overrides} />);
}

function makeListenerItem(overrides: Partial<ListenerData> = {}, itemOverrides: ItemOverrides = {}) {
  const listener = createListener(overrides);
  return {
    kind: "listener" as const,
    id: listener.listener_id,
    name: itemOverrides.name ?? (listener.handler_summary || listener.handler_method),
    humanDescription:
      itemOverrides.humanDescription !== undefined
        ? itemOverrides.humanDescription
        : (listener.human_description ?? null),
    statusKind: itemOverrides.statusKind ?? ("ok" as const),
    data: listener,
  };
}

function makeJobItem(overrides: Partial<JobData> = {}, itemOverrides: ItemOverrides = {}) {
  const job = createJob(overrides);
  return {
    kind: "job" as const,
    id: job.job_id,
    name: itemOverrides.name ?? job.job_name,
    humanDescription:
      itemOverrides.humanDescription !== undefined
        ? itemOverrides.humanDescription
        : job.trigger_label !== ""
          ? job.trigger_label
          : null,
    statusKind: itemOverrides.statusKind ?? ("ok" as const),
    data: job,
  };
}

describe("UnifiedHandlerRow — listener", () => {
  it("renders with data-testid containing kind and id", () => {
    const item = makeListenerItem({ listener_id: 42 });
    const { getByTestId } = renderRow(item);
    expect(getByTestId(rowTestId("listener", 42))).toBeDefined();
  });

  it("renders handler name", () => {
    const item = makeListenerItem({ handler_summary: "on_motion_detected()", listener_id: 1 });
    const { getByText } = renderRow(item);
    expect(getByText("on_motion_detected()")).toBeDefined();
  });

  it("exposes human_description via aria-label but not as a rendered line", () => {
    const item = makeListenerItem(
      { human_description: "When kitchen light changes", listener_id: 1 },
      { name: "on_light_change", humanDescription: "When kitchen light changes" },
    );
    const { getByTestId, queryByText } = renderRow(item);
    expect(getByTestId(rowTestId("listener", 1)).getAttribute("aria-label")).toBe(
      "on_light_change: When kitchen light changes",
    );
    expect(queryByText("When kitchen light changes")).toBeNull();
  });

  it("omits the description from the aria-label when humanDescription is null", () => {
    const item = makeListenerItem(
      { human_description: null, listener_id: 1 },
      { name: "on_change", humanDescription: null },
    );
    const { getByTestId } = renderRow(item);
    expect(getByTestId(rowTestId("listener", 1)).getAttribute("aria-label")).toBe("on_change");
  });

  it("renders invocation count in stats", () => {
    const item = makeListenerItem({ total_invocations: 7, listener_id: 1 });
    const { getByText } = renderRow(item);
    expect(getByText("7 calls")).toBeDefined();
  });

  it("renders failed count when failed > 0", () => {
    const item = makeListenerItem({ failed: 3, total_invocations: 10, listener_id: 1 });
    const { getByText } = renderRow(item);
    expect(getByText("3 failed")).toBeDefined();
  });

  it("renders timed_out count separately from failed", () => {
    const item = makeListenerItem({ timed_out: 2, failed: 1, total_invocations: 5, listener_id: 1 });
    const { getByText } = renderRow(item);
    expect(getByText("2 timed out")).toBeDefined();
    expect(getByText("1 failed")).toBeDefined();
  });

  it("does not render failed/timed_out when both are 0", () => {
    const item = makeListenerItem({ failed: 0, timed_out: 0, listener_id: 1 });
    const { queryByText } = renderRow(item);
    expect(queryByText(/failed/)).toBeNull();
    expect(queryByText(/timed out/)).toBeNull();
  });

  it("sets aria-pressed=true when isSelected is true", () => {
    const item = makeListenerItem({ listener_id: 1 });
    const { getByTestId } = renderRow(item, { isSelected: true });
    expect(getByTestId(rowTestId("listener", 1)).getAttribute("aria-pressed")).toBe("true");
  });

  it("sets aria-pressed=false when isSelected is false", () => {
    const item = makeListenerItem({ listener_id: 1 });
    const { getByTestId } = renderRow(item, { isSelected: false });
    expect(getByTestId(rowTestId("listener", 1)).getAttribute("aria-pressed")).toBe("false");
  });

  it("calls onSelect when clicked", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const item = makeListenerItem({ listener_id: 1 });
    const { getByRole } = renderRow(item, { onSelect });
    await user.click(getByRole("button"));
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it("calls onSelect when activated via Enter key (native button fires click)", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const item = makeListenerItem({ listener_id: 1 });
    const { getByRole } = renderRow(item, { onSelect });
    const button = getByRole("button");
    button.focus();
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it("calls onSelect when activated via Space key (native button fires click)", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const item = makeListenerItem({ listener_id: 1 });
    const { getByRole } = renderRow(item, { onSelect });
    const button = getByRole("button");
    button.focus();
    await user.keyboard(" ");
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it("includes a visible focus outline utility", () => {
    const item = makeListenerItem({ listener_id: 1 });
    const { getByRole } = renderRow(item);
    expect(getByRole("button").className).toContain("focus-visible:outline-solid");
    expect(getByRole("button").className).toContain("focus-visible:outline-primary");
  });
});

describe("UnifiedHandlerRow — idle state", () => {
  it("applies the dimmed idle styling when statusKind is mute", () => {
    const item = makeListenerItem(
      { listener_id: 1, total_invocations: 0, failed: 0, timed_out: 0 },
      { statusKind: "mute" },
    );
    const { getByTestId } = renderRow(item);
    expect(getByTestId(rowTestId("listener", 1)).className).toContain("opacity-60");
  });

  it("does not apply the dimmed idle styling when statusKind is ok", () => {
    const item = makeListenerItem({ listener_id: 1 });
    const { getByTestId } = renderRow(item);
    expect(getByTestId(rowTestId("listener", 1)).className).not.toContain("opacity-60");
  });
});

describe("UnifiedHandlerRow — subline switching", () => {
  it("shows last_error_message when handler has errors", () => {
    const item = makeListenerItem(
      {
        listener_id: 1,
        failed: 2,
        last_error_message: "KeyError: 'foo'",
        human_description: "When something changes",
      },
      { name: "on_change", humanDescription: "When something changes", statusKind: "err" },
    );
    const { queryByTestId } = renderRow(item);
    const errSubline = queryByTestId(TESTID_SUBLINE_ERR);
    expect(errSubline).not.toBeNull();
    expect(errSubline?.textContent).toContain("KeyError");
  });

  it("shows last_error_message when a failing job has errors", () => {
    const item = makeJobItem(
      { job_id: 1, failed: 3, last_error_message: "ConnectionError: timeout" },
      { name: "sync_data", humanDescription: null, statusKind: "err" },
    );
    const { queryByTestId } = renderRow(item);
    const errSubline = queryByTestId(TESTID_SUBLINE_ERR);
    expect(errSubline).not.toBeNull();
    expect(errSubline?.textContent).toContain("ConnectionError");
  });

  it("does not show a description line for healthy handlers (context lives in the detail pane)", () => {
    const item = makeListenerItem(
      {
        listener_id: 1,
        failed: 0,
        timed_out: 0,
        last_error_message: null,
        human_description: "Fires on door open",
      },
      { name: "on_door", humanDescription: "Fires on door open" },
    );
    const { getByTestId, queryByTestId } = renderRow(item);
    expect(queryByTestId(TESTID_SUBLINE_ERR)).toBeNull();
    expect(getByTestId(rowTestId("listener", 1)).getAttribute("aria-label")).toBe("on_door: Fires on door open");
  });

  it("shows next-run line for schedule jobs", () => {
    const item = makeJobItem(
      { job_id: 1, next_run: Math.floor(Date.now() / 1000) + 60 },
      { name: "my_job", humanDescription: null },
    );
    const { queryByTestId } = renderRow(item);
    expect(queryByTestId(TESTID_NEXT_RUN)).not.toBeNull();
  });
});

describe("UnifiedHandlerRow — mode chip", () => {
  it("renders mode chip for listener with mode=single", () => {
    const item = makeListenerItem({ mode: "single", listener_id: 1 });
    const { getByTestId } = renderRow(item);
    expect(getByTestId(TESTID_MODE_CHIP).textContent).toBe("single");
  });

  it("renders mode chip for listener with mode=parallel", () => {
    const item = makeListenerItem({ mode: "parallel", listener_id: 2 });
    const { getByTestId } = renderRow(item);
    expect(getByTestId(TESTID_MODE_CHIP).textContent).toBe("parallel");
  });

  it("renders mode chip for listener with mode=queued", () => {
    const item = makeListenerItem({ mode: "queued", listener_id: 3 });
    const { getByTestId } = renderRow(item);
    expect(getByTestId(TESTID_MODE_CHIP).textContent).toBe("queued");
  });

  it("renders mode chip for listener with mode=restart", () => {
    const item = makeListenerItem({ mode: "restart", listener_id: 4 });
    const { getByTestId } = renderRow(item);
    expect(getByTestId(TESTID_MODE_CHIP).textContent).toBe("restart");
  });

  it("does not render mode chip for job items", () => {
    const item = makeJobItem({ job_id: 5 });
    const { queryByTestId } = renderRow(item);
    expect(queryByTestId(TESTID_MODE_CHIP)).toBeNull();
  });
});

describe("UnifiedHandlerRow — job", () => {
  it("renders with data-testid containing kind='job' and job id", () => {
    const item = makeJobItem({ job_id: 7 });
    const { getByTestId } = renderRow(item);
    expect(getByTestId(rowTestId("job", 7))).toBeDefined();
  });

  it("renders job name", () => {
    const item = makeJobItem({ job_name: "cleanup_task", job_id: 1 });
    const { getByText } = renderRow(item);
    expect(getByText("cleanup_task")).toBeDefined();
  });

  it("exposes trigger_label as humanDescription via aria-label for jobs", () => {
    const item = makeJobItem(
      { job_id: 1, trigger_label: "every 5 minutes" },
      { name: "my_job", humanDescription: "every 5 minutes" },
    );
    const { getByTestId } = renderRow(item);
    expect(getByTestId(rowTestId("job", 1)).getAttribute("aria-label")).toBe("my_job: every 5 minutes");
  });

  it("renders execution count in stats", () => {
    const item = makeJobItem({ total_executions: 4, job_id: 1 });
    const { getByText } = renderRow(item);
    expect(getByText("4 runs")).toBeDefined();
  });

  it("renders timed_out separate from failed for jobs", () => {
    const item = makeJobItem({ timed_out: 1, failed: 2, total_executions: 10, job_id: 1 });
    const { getByText } = renderRow(item);
    expect(getByText("2 failed")).toBeDefined();
    expect(getByText("1 timed out")).toBeDefined();
  });

  it.each([
    ["manual", "manual"],
    ["waiting", "waiting"],
    ["completed", "completed"],
  ] as const)("renders schedule status badge '%s' for jobs", (status, label) => {
    const item = makeJobItem({ job_id: 1, schedule_status: status, next_run: null });
    const { getByTestId } = renderRow(item);
    expect(getByTestId(TESTID_SCHEDULE_STATUS_BADGE).textContent).toBe(label);
  });

  it("does not render a schedule status badge for a normal scheduled job", () => {
    const item = makeJobItem({ job_id: 1, schedule_status: "scheduled", schedule_status_reason: null });
    const { queryByTestId } = renderRow(item);
    expect(queryByTestId(TESTID_SCHEDULE_STATUS_BADGE)).toBeNull();
  });

  it("renders 'unknown' badge for scheduled jobs with legacy_unknown reason", () => {
    const item = makeJobItem({ job_id: 1, schedule_status: "scheduled", schedule_status_reason: "legacy_unknown" });
    const { getByTestId } = renderRow(item);
    expect(getByTestId(TESTID_SCHEDULE_STATUS_BADGE).textContent).toBe("unknown");
  });

  it("does not render a schedule status badge for listeners", () => {
    const item = makeListenerItem();
    const { queryByTestId } = renderRow(item);
    expect(queryByTestId(TESTID_SCHEDULE_STATUS_BADGE)).toBeNull();
  });
});

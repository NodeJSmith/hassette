import { describe, expect, it, vi } from "vitest";

import { createUnifiedRow } from "../test/factories";
import { createWouterMock } from "../test/mock-wouter";
import { renderWithAppState } from "../test/render-helpers";
import { formatRate, SECONDS_PER_HOUR } from "../utils/format";
import type { UnifiedRow } from "../utils/handler-rows";
import { HandlerMobileRow, HandlerTableRow } from "./handlers-rows";

vi.mock("wouter", () => createWouterMock());

function createRow(overrides: Partial<UnifiedRow> = {}): UnifiedRow {
  return createUnifiedRow({
    app_key: "my_app",
    name: "on_light_change",
    handler_method: "my_app.MyApp.on_light_change",
    runs: 42,
    failed: 2,
    timed_out: 1,
    avg_duration_ms: 150,
    ...overrides,
  });
}

// HandlerTableRow must be inside <table><tbody> or the DOM is invalid
function renderTableRow(row: UnifiedRow) {
  return renderWithAppState(
    <table>
      <tbody>
        <HandlerTableRow row={row} />
      </tbody>
    </table>,
  );
}

describe("HandlerTableRow", () => {
  it("renders kind badge 'event' for listener kind", () => {
    const { getByText } = renderTableRow(createRow({ kind: "listener" }));
    expect(getByText("event")).toBeDefined();
  });

  it("renders kind badge 'job' for job kind", () => {
    const { getByText } = renderTableRow(createRow({ kind: "job" }));
    expect(getByText("job")).toBeDefined();
  });

  it("shows app_key as a link", () => {
    const row = createRow({ app_key: "my_app" });
    const { getByRole } = renderTableRow(row);
    const link = getByRole("link", { name: /my_app/ });
    expect((link as HTMLAnchorElement).href).toContain("/apps/my_app");
  });

  it("shows name as a link pointing to handler deep-link", () => {
    const row = createRow({ app_key: "my_app", id: "listener/1", name: "on_light_change" });
    const { getByRole } = renderTableRow(row);
    const link = getByRole("link", { name: /on_light_change/ });
    expect((link as HTMLAnchorElement).href).toContain("/apps/my_app/handlers/listener/1");
  });

  it("name cell has title set to handler_method", () => {
    const row = createRow({ handler_method: "my_app.MyApp.on_light_change" });
    const { container } = renderTableRow(row);
    const td = container.querySelector("td[title]");
    expect(td?.getAttribute("title")).toBe("my_app.MyApp.on_light_change");
  });

  it("shows trigger when present", () => {
    const { getByText } = renderTableRow(createRow({ trigger: "state change" }));
    expect(getByText("state change")).toBeDefined();
  });

  it("shows '—' when trigger is null", () => {
    const { container } = renderTableRow(createRow({ trigger: null }));
    // The trigger cell is the 4th td (index 3)
    const tds = container.querySelectorAll("td");
    expect(tds[3].textContent).toBe("—");
  });

  it("shows runs count", () => {
    const { getByText } = renderTableRow(createRow({ runs: 42 }));
    expect(getByText("42")).toBeDefined();
  });

  it("shows failed count with danger emphasis when failed > 0", () => {
    const { container } = renderTableRow(createRow({ failed: 2, runs: 10 }));
    const failedCell = Array.from(container.querySelectorAll("td")).find((el) => el.textContent === "2");
    expect(failedCell?.getAttribute("data-emphasis")).toBe("danger");
  });

  it("shows 0 for failed when failed is 0", () => {
    const { container } = renderTableRow(createRow({ failed: 0 }));
    // 6th td (index 5) is the failed cell
    const tds = container.querySelectorAll("td");
    expect(tds[5].textContent).toBe("0");
  });

  it("shows timed_out with warning emphasis when timed_out > 0", () => {
    const { container } = renderTableRow(createRow({ timed_out: 3, failed: 0 }));
    const warningCell = Array.from(container.querySelectorAll("td")).find((el) => el.textContent === "3");
    expect(warningCell?.getAttribute("data-emphasis")).toBe("warning");
  });

  it("shows 0 for timed_out when timed_out is 0", () => {
    const { container } = renderTableRow(createRow({ timed_out: 0 }));
    // 7th td (index 6) is the timed_out cell
    const tds = container.querySelectorAll("td");
    expect(tds[6].textContent).toBe("0");
  });

  it("shows cancelled with cancel emphasis when cancelled > 0", () => {
    const { container } = renderTableRow(createRow({ cancelled: 5, failed: 0, timed_out: 0 }));
    const cancelCell = Array.from(container.querySelectorAll("td")).find((el) => el.textContent === "5");
    expect(cancelCell?.getAttribute("data-emphasis")).toBe("cancel");
  });

  it("shows 0 for cancelled when cancelled is 0", () => {
    const { container } = renderTableRow(createRow({ cancelled: 0 }));
    // 8th td (index 7) is the cancelled cell
    const tds = container.querySelectorAll("td");
    expect(tds[7].textContent).toBe("0");
  });

  it("shows error rate via formatRate", () => {
    const row = createRow({ failed: 2, runs: 42 });
    const expected = formatRate(2, 42);
    const { getByText } = renderTableRow(row);
    expect(getByText(expected)).toBeDefined();
  });

  it("shows '—' for next_run when next_run_ts is null and there is no schedule_status", () => {
    const { container } = renderTableRow(createRow({ next_run_ts: null, schedule_status: null }));
    // Last td (index 10) is the next_run cell
    const tds = container.querySelectorAll("td");
    expect(tds[10].textContent).toBe("—");
  });

  it.each([
    ["manual", "manual"],
    ["waiting", "waiting"],
    ["completed", "completed"],
  ] as const)(
    "shows schedule_status '%s' label in the next_run cell for jobs with null next_run_ts",
    (status, label) => {
      const { container } = renderTableRow(createRow({ kind: "job", next_run_ts: null, schedule_status: status }));
      const tds = container.querySelectorAll("td");
      expect(tds[10].textContent).toBe(label);
    },
  );

  it("shows 'unknown' in the next_run cell for legacy_unknown scheduled jobs", () => {
    const { container } = renderTableRow(
      createRow({
        kind: "job",
        next_run_ts: null,
        schedule_status: "scheduled",
        schedule_status_reason: "legacy_unknown",
      }),
    );
    const tds = container.querySelectorAll("td");
    expect(tds[10].textContent).toBe("unknown");
  });

  it("does not show schedule_status label for listeners even if schedule_status were set", () => {
    const { container } = renderTableRow(createRow({ kind: "listener", next_run_ts: null, schedule_status: "manual" }));
    const tds = container.querySelectorAll("td");
    expect(tds[10].textContent).toBe("—");
  });

  it("marks <tr> as failing when failed > 0", () => {
    const { container } = renderTableRow(createRow({ failed: 1 }));
    const tr = container.querySelector("tr");
    expect(tr?.getAttribute("data-state")).toBe("failing");
  });

  it("leaves <tr> in default state when failed is 0", () => {
    const { container } = renderTableRow(createRow({ failed: 0 }));
    const tr = container.querySelector("tr");
    expect(tr?.getAttribute("data-state")).toBe("default");
  });

  it("has correct data-testid for listener row", () => {
    const { getByTestId } = renderTableRow(createRow({ kind: "listener", id: "listener/1" }));
    expect(getByTestId("listener-row-listener/1")).toBeDefined();
  });

  it("has correct data-testid for job row", () => {
    const { getByTestId } = renderTableRow(createRow({ kind: "job", id: "job/10" }));
    expect(getByTestId("job-row-job/10")).toBeDefined();
  });
});

describe("HandlerMobileRow", () => {
  function renderMobileRow(row: UnifiedRow) {
    return renderWithAppState(<HandlerMobileRow row={row} />);
  }

  it("renders as an anchor with correct href", () => {
    const row = createRow({ app_key: "my_app", id: "listener/1" });
    const { container } = renderMobileRow(row);
    const anchor = container.querySelector("a");
    expect(anchor?.getAttribute("href")).toBe("/apps/my_app/handlers/listener/1");
  });

  it("shows app_key", () => {
    const { getByText } = renderMobileRow(createRow({ app_key: "my_app" }));
    expect(getByText("my_app")).toBeDefined();
  });

  it("shows name", () => {
    const { getByText } = renderMobileRow(createRow({ name: "on_light_change" }));
    expect(getByText("on_light_change")).toBeDefined();
  });

  it("shows 'failed' span with danger emphasis when failed > 0", () => {
    const { container } = renderMobileRow(createRow({ failed: 3, runs: 10 }));
    const dangerSpan = container.querySelector("span[data-emphasis='danger']");
    expect(dangerSpan).not.toBeNull();
    expect(dangerSpan?.textContent).toContain("3");
  });

  it("does not show failed span when failed is 0", () => {
    const { queryByText } = renderMobileRow(createRow({ failed: 0 }));
    expect(queryByText(/failed/)).toBeNull();
  });

  it("shows footer with 'next' for jobs that have next_run_ts", () => {
    const futureTs = Math.floor(Date.now() / 1000) + SECONDS_PER_HOUR;
    const row = createRow({ kind: "job", next_run_ts: futureTs });
    const { getByText } = renderMobileRow(row);
    // Footer renders "next <relative time>"
    expect(getByText(/next/)).toBeDefined();
  });

  it("does not show footer for listeners", () => {
    const futureTs = Math.floor(Date.now() / 1000) + SECONDS_PER_HOUR;
    // listeners always have next_run_ts: null, but even if we force one,
    // MobileRow only renders the footer for kind === "job"
    const row = createRow({ kind: "listener", next_run_ts: futureTs });
    const { queryByText } = renderMobileRow(row);
    expect(queryByText(/^next /i)).toBeNull();
  });

  it("does not show footer for jobs with null next_run_ts and no schedule_status", () => {
    const row = createRow({ kind: "job", next_run_ts: null, schedule_status: null });
    const { queryByText } = renderMobileRow(row);
    expect(queryByText(/^next /i)).toBeNull();
  });

  it("shows schedule_status label (without 'next' prefix) for jobs with null next_run_ts", () => {
    const row = createRow({ kind: "job", next_run_ts: null, schedule_status: "manual" });
    const { getByTestId } = renderMobileRow(row);
    expect(getByTestId("handler-row-schedule-status").textContent).toBe("manual");
  });

  it("has correct data-testid", () => {
    const { getByTestId } = renderMobileRow(createRow({ kind: "listener", id: "listener/1" }));
    expect(getByTestId("listener-row-listener/1")).toBeDefined();
  });
});

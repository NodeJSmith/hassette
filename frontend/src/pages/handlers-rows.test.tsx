import { describe, expect, it, vi } from "vitest";

import { renderWithAppState } from "../test/render-helpers";
import { formatRate } from "../utils/format";
import type { UnifiedRow } from "../utils/handler-rows";
import { HandlerMobileRow, HandlerTableRow } from "./handlers-rows";

vi.mock("wouter", () => ({
  Link: ({ href, children, class: cls }: Record<string, unknown>) => (
    <a href={href as string} class={cls as string}>
      {children as never}
    </a>
  ),
}));

function createRow(overrides: Partial<UnifiedRow> = {}): UnifiedRow {
  return {
    kind: "listener",
    id: "listener/1",
    app_key: "my_app",
    name: "on_light_change",
    handler_method: "my_app.MyApp.on_light_change",
    trigger: "state change",
    runs: 42,
    failed: 2,
    timed_out: 1,
    cancelled: 0,
    avg_duration_ms: 150,
    next_run_ts: null,
    source_tier: "app",
    ...overrides,
  };
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

  it("shows failed count with danger class when failed > 0", () => {
    const { container } = renderTableRow(createRow({ failed: 2, runs: 10 }));
    const dangerCells = container.querySelectorAll("td.ht-text-danger");
    // The failed count cell and the error rate cell both get danger class
    expect(dangerCells.length).toBeGreaterThan(0);
    const failedCell = Array.from(dangerCells).find((el) => el.textContent === "2");
    expect(failedCell).toBeDefined();
  });

  it("shows 0 for failed when failed is 0", () => {
    const { container } = renderTableRow(createRow({ failed: 0 }));
    // 6th td (index 5) is the failed cell
    const tds = container.querySelectorAll("td");
    expect(tds[5].textContent).toBe("0");
  });

  it("shows timed_out with warning class when timed_out > 0", () => {
    const { container } = renderTableRow(createRow({ timed_out: 3, failed: 0 }));
    const warningCell = container.querySelector("td.ht-text-warning");
    expect(warningCell).not.toBeNull();
    expect(warningCell?.textContent).toBe("3");
  });

  it("shows 0 for timed_out when timed_out is 0", () => {
    const { container } = renderTableRow(createRow({ timed_out: 0 }));
    // 7th td (index 6) is the timed_out cell
    const tds = container.querySelectorAll("td");
    expect(tds[6].textContent).toBe("0");
  });

  it("shows cancelled with cancel class when cancelled > 0", () => {
    const { container } = renderTableRow(createRow({ cancelled: 5, failed: 0, timed_out: 0 }));
    const cancelCell = container.querySelector("td.ht-text-cancel");
    expect(cancelCell).not.toBeNull();
    expect(cancelCell?.textContent).toBe("5");
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

  it("shows '—' for next_run when next_run_ts is null", () => {
    const { container } = renderTableRow(createRow({ next_run_ts: null }));
    // Last td (index 10) is the next_run cell
    const tds = container.querySelectorAll("td");
    expect(tds[10].textContent).toBe("—");
  });

  it("applies rowFailing class on <tr> when failed > 0", () => {
    const { container } = renderTableRow(createRow({ failed: 1 }));
    const tr = container.querySelector("tr");
    // The CSS module class name won't be the literal "rowFailing", but it
    // will contain "rowFailing" as part of the generated class string.
    const classes = tr?.className ?? "";
    expect(classes).toMatch(/rowFailing/);
  });

  it("does not apply rowFailing class when failed is 0", () => {
    const { container } = renderTableRow(createRow({ failed: 0 }));
    const tr = container.querySelector("tr");
    const classes = tr?.className ?? "";
    expect(classes).not.toMatch(/rowFailing/);
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

  it("shows 'failed' span with danger class when failed > 0", () => {
    const { container } = renderMobileRow(createRow({ failed: 3, runs: 10 }));
    const dangerSpan = container.querySelector("span.ht-text-danger");
    expect(dangerSpan).not.toBeNull();
    expect(dangerSpan?.textContent).toContain("3");
  });

  it("does not show failed span when failed is 0", () => {
    const { queryByText } = renderMobileRow(createRow({ failed: 0 }));
    expect(queryByText(/failed/)).toBeNull();
  });

  it("shows footer with 'next' for jobs that have next_run_ts", () => {
    const futureTs = Math.floor(Date.now() / 1000) + 3600;
    const row = createRow({ kind: "job", next_run_ts: futureTs });
    const { getByText } = renderMobileRow(row);
    // Footer renders "next <relative time>"
    expect(getByText(/next/)).toBeDefined();
  });

  it("does not show footer for listeners", () => {
    const futureTs = Math.floor(Date.now() / 1000) + 3600;
    // listeners always have next_run_ts: null, but even if we force one,
    // MobileRow only renders the footer for kind === "job"
    const row = createRow({ kind: "listener", next_run_ts: futureTs });
    const { container } = renderMobileRow(row);
    // The mobileCardFooter div should not be present
    const classes = Array.from(container.querySelectorAll("div")).map((el) => el.className);
    const hasFooter = classes.some((c) => c.match(/mobileCardFooter/));
    expect(hasFooter).toBe(false);
  });

  it("does not show footer for jobs with null next_run_ts", () => {
    const row = createRow({ kind: "job", next_run_ts: null });
    const { container } = renderMobileRow(row);
    const divs = Array.from(container.querySelectorAll("div"));
    const hasFooter = divs.some((el) => el.className.match(/mobileCardFooter/));
    expect(hasFooter).toBe(false);
  });

  it("has correct data-testid", () => {
    const { getByTestId } = renderMobileRow(createRow({ kind: "listener", id: "listener/1" }));
    expect(getByTestId("listener-row-listener/1")).toBeDefined();
  });
});

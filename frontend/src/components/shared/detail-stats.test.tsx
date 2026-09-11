import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DetailStats, type DetailStatsCell } from "./detail-stats";

const STATS_TEST_ID = "stats";
// DetailStats derives each cell's testid from the parent testid.
const STATS_CELL_SELECTOR = `[data-testid='${STATS_TEST_ID}-cell']`;

describe("DetailStats", () => {
  const baseCells: DetailStatsCell[] = [
    { label: "Calls", value: 10 },
    { label: "Successful", value: 8 },
    { label: "Failed", value: 2, tone: "err" },
  ];

  it("renders all cells with labels and values", () => {
    const { getByTestId } = render(<DetailStats cells={baseCells} data-testid={STATS_TEST_ID} />);
    const row = getByTestId(STATS_TEST_ID);
    expect(row.textContent).toContain("Calls");
    expect(row.textContent).toContain("10");
    expect(row.textContent).toContain("Successful");
    expect(row.textContent).toContain("8");
  });

  it("applies err tone via data-tone attribute", () => {
    const { getByTestId } = render(<DetailStats cells={baseCells} data-testid={STATS_TEST_ID} />);
    const errValue = getByTestId(STATS_TEST_ID).querySelector("[data-tone='err']");
    expect(errValue).not.toBeNull();
    expect(errValue?.textContent).toBe("2");
  });

  it("applies warn tone via data-tone attribute", () => {
    const cells: DetailStatsCell[] = [{ label: "Timed Out", value: 3, tone: "warn" }];
    const { getByTestId } = render(<DetailStats cells={cells} data-testid={STATS_TEST_ID} />);
    const warnValue = getByTestId(STATS_TEST_ID).querySelector("[data-tone='warn']");
    expect(warnValue).not.toBeNull();
    expect(warnValue?.textContent).toBe("3");
  });

  it("renders string values (dashes for empty)", () => {
    const cells: DetailStatsCell[] = [
      { label: "Min", value: "—" },
      { label: "Max", value: "—" },
    ];
    const { getByTestId } = render(<DetailStats cells={cells} data-testid={STATS_TEST_ID} />);
    const statCells = getByTestId(STATS_TEST_ID).querySelectorAll(STATS_CELL_SELECTOR);
    const labelValuePairs = Array.from(statCells, (cell) => Array.from(cell.children, (child) => child.textContent));
    expect(labelValuePairs).toEqual([
      ["Min", "—"],
      ["Max", "—"],
    ]);
  });

  it("generates per-cell testids from parent testid", () => {
    const { getByTestId } = render(<DetailStats cells={baseCells} data-testid={STATS_TEST_ID} />);
    const cells = getByTestId(STATS_TEST_ID).querySelectorAll(STATS_CELL_SELECTOR);
    expect(cells.length).toBe(3);
  });
});

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { DetailStats, type DetailStatsCell } from "./detail-stats";

describe("DetailStats", () => {
  const baseCells: DetailStatsCell[] = [
    { label: "Calls", value: 10 },
    { label: "Successful", value: 8 },
    { label: "Failed", value: 2, tone: "err" },
  ];

  it("renders all cells with labels and values", () => {
    const { getByTestId } = render(<DetailStats cells={baseCells} data-testid="stats" />);
    const row = getByTestId("stats");
    expect(row.textContent).toContain("Calls");
    expect(row.textContent).toContain("10");
    expect(row.textContent).toContain("Successful");
    expect(row.textContent).toContain("8");
  });

  it("applies err tone via data-tone attribute", () => {
    const { getByTestId } = render(<DetailStats cells={baseCells} data-testid="stats" />);
    const errValue = getByTestId("stats").querySelector("[data-tone='err']");
    expect(errValue).not.toBeNull();
    expect(errValue?.textContent).toBe("2");
  });

  it("applies warn tone via data-tone attribute", () => {
    const cells: DetailStatsCell[] = [{ label: "Timed Out", value: 3, tone: "warn" }];
    const { getByTestId } = render(<DetailStats cells={cells} data-testid="stats" />);
    const warnValue = getByTestId("stats").querySelector("[data-tone='warn']");
    expect(warnValue).not.toBeNull();
    expect(warnValue?.textContent).toBe("3");
  });

  it("renders string values (dashes for empty)", () => {
    const cells: DetailStatsCell[] = [
      { label: "Min", value: "—" },
      { label: "Max", value: "—" },
    ];
    const { getByTestId } = render(<DetailStats cells={cells} data-testid="stats" />);
    const row = getByTestId("stats");
    expect(row.textContent).toContain("Min");
    expect(row.textContent).toContain("Max");
    const dashCells = row.querySelectorAll("[data-testid='stats-cell']");
    expect(dashCells.length).toBe(2);
  });

  it("generates per-cell testids from parent testid", () => {
    const { getByTestId } = render(<DetailStats cells={baseCells} data-testid="stats" />);
    const cells = getByTestId("stats").querySelectorAll("[data-testid='stats-cell']");
    expect(cells.length).toBe(3);
  });
});

import { render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { createJob, createListener } from "../../test/factories";
import { OverviewHealthStrip } from "./health-strip";

describe("OverviewHealthStrip", () => {
  it("renders 5 columns with correct labels", () => {
    const { container } = render(<OverviewHealthStrip listeners={[createListener()]} jobs={[createJob()]} />);
    const cards = container.querySelectorAll("[data-testid='stats-strip-cell']");
    expect(cards.length).toBe(5);
    // Check all 5 labels (CSS text-transform: uppercase applies visually; DOM text is mixed case)
    const text = container.textContent ?? "";
    expect(text.toLowerCase()).toContain("handlers");
    expect(text.toLowerCase()).toContain("total runs");
    expect(text.toLowerCase()).toContain("failed");
    expect(text.toLowerCase()).toContain("error rate");
    expect(text.toLowerCase()).toContain("avg duration");
  });

  it("renders combined handler + job count in HANDLERS column", () => {
    const listeners = [createListener({ listener_id: 1 }), createListener({ listener_id: 2 })];
    const jobs = [createJob({ job_id: 10 })];
    const { container } = render(<OverviewHealthStrip listeners={listeners} jobs={jobs} />);
    const cards = container.querySelectorAll("[data-testid='stats-strip-cell']");
    expect(cards[0].textContent).toContain("3");
  });

  it("renders combined invocations + executions in TOTAL RUNS column", () => {
    const listeners = [createListener({ listener_id: 1, total_invocations: 10 })];
    const jobs = [createJob({ job_id: 1, total_executions: 5 })];
    const { container } = render(<OverviewHealthStrip listeners={listeners} jobs={jobs} />);
    const cards = container.querySelectorAll("[data-testid='stats-strip-cell']");
    const text = cards[1].textContent ?? "";
    expect(text).toContain("15");
  });

  it("shows failed count and applies err tone when > 0", () => {
    const listeners = [createListener({ listener_id: 1, failed: 3, total_invocations: 10 })];
    const { container } = render(<OverviewHealthStrip listeners={listeners} jobs={[]} />);
    const errValue = container.querySelector("[data-tone='err']");
    expect(errValue).not.toBeNull();
    expect(errValue?.textContent).toContain("3");
  });

  it("renders 0 for FAILED when count is 0", () => {
    const { container } = render(<OverviewHealthStrip listeners={[createListener({ failed: 0 })]} jobs={[]} />);
    const cards = container.querySelectorAll("[data-testid='stats-strip-cell']");
    expect(cards[2].textContent).toContain("0");
  });

  it("renders 0% for ERROR RATE when there are no runs", () => {
    const { getByTestId } = render(<OverviewHealthStrip listeners={[]} jobs={[]} />);
    const strip = getByTestId("overview-health-strip");
    expect(strip.textContent).toContain("0%");
  });

  it("computes ERROR RATE from failed + timed out runs", () => {
    const listeners = [createListener({ listener_id: 1, total_invocations: 10, failed: 1, timed_out: 1 })];
    const { container } = render(<OverviewHealthStrip listeners={listeners} jobs={[]} />);
    const cards = container.querySelectorAll("[data-testid='stats-strip-cell']");
    // (1 failed + 1 timed out) / 10 runs = 20%
    expect(cards[3].textContent).toContain("20%");
  });

  it("applies err tone to ERROR RATE when there are errors", () => {
    const listeners = [createListener({ listener_id: 1, total_invocations: 10, failed: 2, timed_out: 0 })];
    const { container } = render(<OverviewHealthStrip listeners={listeners} jobs={[]} />);
    const cards = container.querySelectorAll("[data-testid='stats-strip-cell']");
    expect(cards[3].querySelector("[data-tone='err']")).not.toBeNull();
  });

  it("does not apply a tone to ERROR RATE when there are no errors", () => {
    const listeners = [createListener({ listener_id: 1, total_invocations: 10, failed: 0, timed_out: 0 })];
    const { container } = render(<OverviewHealthStrip listeners={listeners} jobs={[]} />);
    const cards = container.querySelectorAll("[data-testid='stats-strip-cell']");
    expect(cards[3].querySelector("[data-tone='err']")).toBeNull();
  });

  it("shows weighted average duration across listeners and jobs", () => {
    const listeners = [
      createListener({ listener_id: 1, total_invocations: 10, avg_duration_ms: 100 }),
      createListener({ listener_id: 2, total_invocations: 0, avg_duration_ms: 5000 }),
    ];
    const jobs = [createJob({ job_id: 1, total_executions: 10, avg_duration_ms: 300 })];
    const { container } = render(<OverviewHealthStrip listeners={listeners} jobs={jobs} />);
    const cards = container.querySelectorAll("[data-testid='stats-strip-cell']");
    // (100*10 + 300*10) / 20 = 200ms — the idle listener's 5000ms is excluded (0 runs)
    expect(cards[4].textContent).toContain("200.0ms");
  });

  it("shows a dash for AVG DURATION when no handlers have run", () => {
    const { container } = render(
      <OverviewHealthStrip listeners={[createListener({ total_invocations: 0 })]} jobs={[]} />,
    );
    const cards = container.querySelectorAll("[data-testid='stats-strip-cell']");
    expect(cards[4].textContent).toContain("—");
  });

  it("renders testid overview-health-strip", () => {
    const { getByTestId } = render(<OverviewHealthStrip listeners={[]} jobs={[]} />);
    expect(getByTestId("overview-health-strip")).toBeDefined();
  });
});

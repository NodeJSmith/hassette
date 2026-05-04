import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { HandlersHealthStrip } from "./health-strip";
import { createListener, createJob } from "../../test/factories";

describe("HandlersHealthStrip", () => {
  it("renders 5 columns with correct labels", () => {
    const { container } = render(
      <HandlersHealthStrip listeners={[createListener()]} jobs={[createJob()]} />,
    );
    const cards = container.querySelectorAll(".ht-health-card");
    expect(cards.length).toBe(5);
    // Check all 5 labels (CSS text-transform: uppercase applies visually; DOM text is mixed case)
    const text = container.textContent ?? "";
    expect(text.toLowerCase()).toContain("handlers");
    expect(text.toLowerCase()).toContain("invocations");
    expect(text).toContain("1H");
    expect(text.toLowerCase()).toContain("success rate");
    expect(text.toLowerCase()).toContain("failed");
    expect(text.toLowerCase()).toContain("timed out");
  });

  it("renders handler + job count in HANDLERS column", () => {
    const listeners = [createListener({ listener_id: 1 }), createListener({ listener_id: 2 })];
    const jobs = [createJob({ job_id: 10 })];
    const { container } = render(
      <HandlersHealthStrip listeners={listeners} jobs={jobs} />,
    );
    const cards = container.querySelectorAll(".ht-health-card");
    expect(cards[0].textContent).toContain("2");
    expect(cards[0].textContent).toContain("1");
  });

  it("renders total invocations + executions in INVOCATIONS column", () => {
    const listeners = [createListener({ listener_id: 1, total_invocations: 10 })];
    const jobs = [createJob({ job_id: 1, total_executions: 5 })];
    const { container } = render(
      <HandlersHealthStrip listeners={listeners} jobs={jobs} />,
    );
    const cards = container.querySelectorAll(".ht-health-card");
    const text = cards[1].textContent ?? "";
    expect(text).toContain("10");
    expect(text).toContain("5");
  });

  it("renders 100% success rate when no errors", () => {
    const listeners = [createListener({ listener_id: 1, total_invocations: 5, failed: 0, timed_out: 0 })];
    const { getByTestId } = render(
      <HandlersHealthStrip listeners={listeners} jobs={[]} />,
    );
    const strip = getByTestId("handlers-health-strip");
    expect(strip.textContent).toContain("100%");
  });

  it("applies warn tone to SUCCESS RATE when there are errors", () => {
    const listeners = [
      createListener({ listener_id: 1, total_invocations: 10, failed: 2, timed_out: 0 }),
    ];
    const { container } = render(
      <HandlersHealthStrip listeners={listeners} jobs={[]} />,
    );
    const warnCard = container.querySelector(".ht-health-card__value--warning");
    expect(warnCard).not.toBeNull();
  });

  it("shows failed count and applies err tone when > 0", () => {
    const listeners = [
      createListener({ listener_id: 1, failed: 3, total_invocations: 10 }),
    ];
    const { container } = render(
      <HandlersHealthStrip listeners={listeners} jobs={[]} />,
    );
    const errCard = container.querySelector(".ht-health-card__value--danger");
    expect(errCard).not.toBeNull();
    expect(errCard?.textContent).toContain("3");
  });

  it("shows timed_out count and applies warn tone when > 0", () => {
    const listeners = [
      createListener({ listener_id: 1, timed_out: 1, total_invocations: 5 }),
    ];
    const { container } = render(
      <HandlersHealthStrip listeners={listeners} jobs={[]} />,
    );
    const warnCards = container.querySelectorAll(".ht-health-card__value--warning");
    // At least one warn-toned value for timed_out
    expect(warnCards.length).toBeGreaterThanOrEqual(1);
  });

  it("renders em dash for FAILED when count is 0", () => {
    const { container } = render(
      <HandlersHealthStrip listeners={[createListener({ failed: 0 })]} jobs={[]} />,
    );
    const cards = container.querySelectorAll(".ht-health-card");
    // FAILED card (index 3) should show em dash
    expect(cards[3].textContent).toContain("—");
  });

  it("renders em dash for TIMED OUT when count is 0", () => {
    const { container } = render(
      <HandlersHealthStrip listeners={[createListener({ timed_out: 0 })]} jobs={[]} />,
    );
    const cards = container.querySelectorAll(".ht-health-card");
    // TIMED OUT card (index 4) should show em dash
    expect(cards[4].textContent).toContain("—");
  });

  it("renders testid handlers-health-strip", () => {
    const { getByTestId } = render(
      <HandlersHealthStrip listeners={[]} jobs={[]} />,
    );
    expect(getByTestId("handlers-health-strip")).toBeDefined();
  });
});

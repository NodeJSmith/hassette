import { describe, expect, it } from "vitest";
import { HealthStrip } from "./health-strip";
import { createHealthData } from "../../test/factories";
import { renderWithAppState } from "../../test/render-helpers";

describe("HealthStrip", () => {
  it("renders nothing when health is null", () => {
    const { container } = renderWithAppState(<HealthStrip health={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the health strip container when health is provided", () => {
    const { getByTestId } = renderWithAppState(
      <HealthStrip health={createHealthData()} />,
    );
    expect(getByTestId("health-strip")).toBeDefined();
  });

  it("renders Error Rate metric with formatted percentage", () => {
    const { getByText } = renderWithAppState(
      <HealthStrip health={createHealthData({ error_rate: 12.5, error_rate_class: "warn" })} />,
    );
    expect(getByText("Error Rate")).toBeDefined();
    expect(getByText("12.5%")).toBeDefined();
  });

  it("renders Handler Avg metric with formatted duration when > 0", () => {
    const { getByText } = renderWithAppState(
      <HealthStrip health={createHealthData({ handler_avg_duration: 125 })} />,
    );
    expect(getByText("Handler Avg")).toBeDefined();
    expect(getByText("125.0ms")).toBeDefined();
  });

  it("renders Handler Avg as em dash when handler_avg_duration is 0", () => {
    const { getAllByText } = renderWithAppState(
      <HealthStrip health={createHealthData({ handler_avg_duration: 0 })} />,
    );
    const dashes = getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it("renders Job Avg metric with formatted duration when > 0", () => {
    const { getByText } = renderWithAppState(
      <HealthStrip health={createHealthData({ job_avg_duration: 88 })} />,
    );
    expect(getByText("Job Avg")).toBeDefined();
    expect(getByText("88.0ms")).toBeDefined();
  });

  it("renders Job Avg as em dash when job_avg_duration is 0", () => {
    const { getAllByText } = renderWithAppState(
      <HealthStrip health={createHealthData({ job_avg_duration: 0 })} />,
    );
    const dashes = getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it("renders Last Activity label", () => {
    const { getByText } = renderWithAppState(
      <HealthStrip health={createHealthData({ last_activity_ts: null })} />,
    );
    expect(getByText("Last Activity")).toBeDefined();
  });

  it("renders em dash for Last Activity when last_activity_ts is null", () => {
    const { getAllByText } = renderWithAppState(
      <HealthStrip health={createHealthData({ last_activity_ts: null })} />,
    );
    const dashes = getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it("applies success variant class for good error_rate_class", () => {
    const { container } = renderWithAppState(
      <HealthStrip health={createHealthData({ error_rate_class: "good" })} />,
    );
    const successCards = container.querySelectorAll(".ht-health-card__value--success");
    expect(successCards.length).toBeGreaterThanOrEqual(1);
  });

  it("applies warning variant class for warn error_rate_class", () => {
    const { container } = renderWithAppState(
      <HealthStrip health={createHealthData({ error_rate_class: "warn" })} />,
    );
    const warnEl = container.querySelector(".ht-health-card__value--warning");
    expect(warnEl).not.toBeNull();
  });

  it("applies danger variant class for bad error_rate_class", () => {
    const { container } = renderWithAppState(
      <HealthStrip health={createHealthData({ error_rate_class: "bad" })} />,
    );
    const dangerEl = container.querySelector(".ht-health-card__value--danger");
    expect(dangerEl).not.toBeNull();
  });

  it("renders 0.0% error rate without crashing", () => {
    const { getByText } = renderWithAppState(
      <HealthStrip health={createHealthData({ error_rate: 0, error_rate_class: "good" })} />,
    );
    expect(getByText("0.0%")).toBeDefined();
  });

  it("renders 4 health cards", () => {
    const { container } = renderWithAppState(
      <HealthStrip health={createHealthData()} />,
    );
    const cards = container.querySelectorAll(".ht-health-card");
    expect(cards.length).toBe(4);
  });
});

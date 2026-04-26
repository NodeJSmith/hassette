import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { HealthStrip } from "./health-strip";
import { createHealthData } from "../../test/factories";

describe("HealthStrip", () => {
  it("renders nothing when health is null", () => {
    const { container } = render(<HealthStrip health={null} status="running" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the health strip container when health is provided", () => {
    const { getByTestId } = render(
      <HealthStrip health={createHealthData()} status="running" />,
    );
    expect(getByTestId("health-strip")).toBeDefined();
  });

  it("renders Status metric with capitalized status value", () => {
    const { getByText } = render(
      <HealthStrip health={createHealthData()} status="running" />,
    );
    expect(getByText("Status")).toBeDefined();
    expect(getByText("Running")).toBeDefined();
  });

  it("renders Error Rate metric with formatted percentage", () => {
    const { getByText } = render(
      <HealthStrip health={createHealthData({ error_rate: 12.5, error_rate_class: "warn" })} status="running" />,
    );
    expect(getByText("Error Rate")).toBeDefined();
    expect(getByText("12.5%")).toBeDefined();
  });

  it("renders Handler Avg metric with formatted duration when > 0", () => {
    const { getByText } = render(
      <HealthStrip health={createHealthData({ handler_avg_duration: 125 })} status="running" />,
    );
    expect(getByText("Handler Avg")).toBeDefined();
    expect(getByText("125.0ms")).toBeDefined();
  });

  it("renders Handler Avg as em dash when handler_avg_duration is 0", () => {
    const { getAllByText } = render(
      <HealthStrip health={createHealthData({ handler_avg_duration: 0 })} status="running" />,
    );
    // The em dash "—" appears for both handler and job avg when zero
    const dashes = getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it("renders Job Avg as em dash when job_avg_duration is 0", () => {
    const { getAllByText } = render(
      <HealthStrip health={createHealthData({ job_avg_duration: 0 })} status="running" />,
    );
    const dashes = getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it("applies success variant class for running status", () => {
    const { container } = render(
      <HealthStrip health={createHealthData()} status="running" />,
    );
    const statusValue = container.querySelector(".ht-health-card__value--success");
    expect(statusValue).not.toBeNull();
  });

  it("applies danger variant class for failed status", () => {
    const { container } = render(
      <HealthStrip health={createHealthData()} status="failed" />,
    );
    const statusValue = container.querySelector(".ht-health-card__value--danger");
    expect(statusValue).not.toBeNull();
  });

  it("applies success variant class for good error_rate_class", () => {
    const { container } = render(
      <HealthStrip health={createHealthData({ error_rate_class: "good" })} status="running" />,
    );
    const errorRateCards = container.querySelectorAll(".ht-health-card__value--success");
    // Both status and error rate should be success
    expect(errorRateCards.length).toBeGreaterThanOrEqual(2);
  });

  it("applies warning variant class for warn error_rate_class", () => {
    const { container } = render(
      <HealthStrip health={createHealthData({ error_rate_class: "warn" })} status="running" />,
    );
    const warnEl = container.querySelector(".ht-health-card__value--warning");
    expect(warnEl).not.toBeNull();
  });

  it("applies danger variant class for bad error_rate_class", () => {
    const { container } = render(
      <HealthStrip health={createHealthData({ error_rate_class: "bad" })} status="running" />,
    );
    const dangerEl = container.querySelector(".ht-health-card__value--danger");
    expect(dangerEl).not.toBeNull();
  });

  it("renders 0.0% error rate without crashing", () => {
    const { getByText } = render(
      <HealthStrip health={createHealthData({ error_rate: 0, error_rate_class: "good" })} status="running" />,
    );
    expect(getByText("0.0%")).toBeDefined();
  });
});

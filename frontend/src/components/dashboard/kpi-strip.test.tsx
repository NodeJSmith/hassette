import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { KpiStrip } from "./kpi-strip";
import { createKpis } from "../../test/factories";

describe("KpiStrip", () => {
  it("returns null when data is null", () => {
    const { container } = render(<KpiStrip data={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders all 5 KPI card labels", () => {
    const { getByText } = render(<KpiStrip data={createKpis()} />);
    expect(getByText("Error Rate")).toBeDefined();
    expect(getByText("Apps")).toBeDefined();
    expect(getByText("Handlers")).toBeDefined();
    expect(getByText("Jobs")).toBeDefined();
    expect(getByText("Uptime")).toBeDefined();
  });

  it("renders error rate value formatted to 1 decimal", () => {
    const { getByText } = render(
      <KpiStrip data={createKpis({ error_rate: 3.5 })} />,
    );
    expect(getByText("3.5%")).toBeDefined();
  });

  it("renders app count from appCount prop", () => {
    const { container } = render(
      <KpiStrip data={createKpis()} appCount={7} />,
    );
    // The "Apps" card shows appCount as its value
    const valueEl = Array.from(container.querySelectorAll(".ht-health-card__value")).find(
      (el) => el.textContent === "7",
    );
    expect(valueEl).toBeDefined();
  });

  it("renders running count in the Apps detail", () => {
    const { getByText } = render(
      <KpiStrip data={createKpis()} appCount={5} runningCount={3} />,
    );
    expect(getByText("3 running")).toBeDefined();
  });

  it("renders handler count", () => {
    const data = createKpis({ total_handlers: 12 });
    const { getByText } = render(<KpiStrip data={data} />);
    expect(getByText("12")).toBeDefined();
  });

  it("renders job count", () => {
    const data = createKpis({ total_jobs: 8 });
    const { getByText } = render(<KpiStrip data={data} />);
    expect(getByText("8")).toBeDefined();
  });

  it("renders invocation count in handler detail", () => {
    const data = createKpis({ total_invocations: 100 });
    const { getByText } = render(<KpiStrip data={data} />);
    expect(getByText("100 invocations")).toBeDefined();
  });

  it("pluralizes 1 invocation correctly", () => {
    const data = createKpis({ total_invocations: 1 });
    const { getByText } = render(<KpiStrip data={data} />);
    expect(getByText("1 invocation")).toBeDefined();
  });

  it("renders execution count in jobs detail", () => {
    const data = createKpis({ total_executions: 42 });
    const { getByText } = render(<KpiStrip data={data} />);
    expect(getByText("42 executions")).toBeDefined();
  });

  it("shows 'No data' in error rate detail when no invocations or executions", () => {
    const data = createKpis({
      total_invocations: 0,
      total_executions: 0,
    });
    const { getByText } = render(<KpiStrip data={data} />);
    expect(getByText("No data")).toBeDefined();
  });

  it("shows error count over invocation count in error rate detail when invocations > 0", () => {
    const data = createKpis({
      total_invocations: 50,
      total_executions: 0,
      total_errors: 5,
      total_timed_out: 0,
      total_job_errors: 0,
      total_job_timed_out: 0,
    });
    const { getByText } = render(<KpiStrip data={data} />);
    // "5 / 50 invocations"
    expect(getByText("5 / 50 invocations")).toBeDefined();
  });

  it("applies success variant class for good error rate", () => {
    const data = createKpis({ error_rate: 0, error_rate_class: "good" });
    const { getByTestId } = render(<KpiStrip data={data} />);
    const strip = getByTestId("kpi-strip");
    const valueEl = strip.querySelector(".ht-health-card__value--success");
    expect(valueEl).not.toBeNull();
  });

  it("applies warning variant class for warn error rate", () => {
    const data = createKpis({ error_rate: 10, error_rate_class: "warn" });
    const { getByTestId } = render(<KpiStrip data={data} />);
    const strip = getByTestId("kpi-strip");
    const valueEl = strip.querySelector(".ht-health-card__value--warning");
    expect(valueEl).not.toBeNull();
  });

  it("applies danger variant class for bad error rate", () => {
    const data = createKpis({ error_rate: 50, error_rate_class: "bad" });
    const { getByTestId } = render(<KpiStrip data={data} />);
    const strip = getByTestId("kpi-strip");
    const valueEl = strip.querySelector(".ht-health-card__value--danger");
    expect(valueEl).not.toBeNull();
  });

  it("shows em-dash for uptime when uptime_seconds is null", () => {
    const data = createKpis({ uptime_seconds: null });
    const { getByText } = render(<KpiStrip data={data} />);
    expect(getByText("—")).toBeDefined();
  });

  it("shows em-dash for uptime when uptime_seconds is zero", () => {
    const data = createKpis({ uptime_seconds: 0 });
    const { getByText } = render(<KpiStrip data={data} />);
    expect(getByText("—")).toBeDefined();
  });

  it("shows hours and minutes for uptime when seconds > 0", () => {
    // 3661 seconds = 1h 1m
    const data = createKpis({ uptime_seconds: 3661 });
    const { getByText } = render(<KpiStrip data={data} />);
    expect(getByText("1h 1m")).toBeDefined();
  });

  it("shows 0h 0m for uptime_seconds that is just above zero but less than 60", () => {
    const data = createKpis({ uptime_seconds: 30 });
    const { getByText } = render(<KpiStrip data={data} />);
    expect(getByText("0h 0m")).toBeDefined();
  });

  it("renders kpi-strip container with data-testid", () => {
    const { getByTestId } = render(<KpiStrip data={createKpis()} />);
    expect(getByTestId("kpi-strip")).toBeDefined();
  });

  it("zero appCount and runningCount render correctly", () => {
    const { getByText } = render(
      <KpiStrip data={createKpis()} appCount={0} runningCount={0} />,
    );
    expect(getByText("0 running")).toBeDefined();
  });
});

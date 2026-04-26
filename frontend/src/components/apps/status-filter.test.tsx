import { describe, expect, it } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { StatusFilter, type FilterValue } from "./status-filter";

function createCounts(overrides: Record<string, number> = {}): Record<string, number> {
  return {
    running: 3,
    failed: 1,
    stopped: 2,
    disabled: 0,
    ...overrides,
  };
}

describe("StatusFilter", () => {
  it("renders all filter tabs: All, Running, Failed, Stopped, Disabled", () => {
    const active = signal<FilterValue>("all");
    const { getByTestId } = render(<StatusFilter active={active} counts={createCounts()} />);
    expect(getByTestId("tab-all")).toBeDefined();
    expect(getByTestId("tab-running")).toBeDefined();
    expect(getByTestId("tab-failed")).toBeDefined();
    expect(getByTestId("tab-stopped")).toBeDefined();
    expect(getByTestId("tab-disabled")).toBeDefined();
  });

  it("renders All tab with total count across all statuses", () => {
    const active = signal<FilterValue>("all");
    const counts = { running: 3, failed: 1, stopped: 2, disabled: 0 };
    const { getByTestId } = render(<StatusFilter active={active} counts={counts} />);
    const allTab = getByTestId("tab-all");
    // Total = 3 + 1 + 2 + 0 = 6
    expect(allTab.textContent).toContain("6");
  });

  it("renders individual status counts in each tab", () => {
    const active = signal<FilterValue>("all");
    const counts = { running: 5, failed: 2, stopped: 1, disabled: 3 };
    const { getByTestId } = render(<StatusFilter active={active} counts={counts} />);
    expect(getByTestId("tab-running").textContent).toContain("5");
    expect(getByTestId("tab-failed").textContent).toContain("2");
    expect(getByTestId("tab-stopped").textContent).toContain("1");
    expect(getByTestId("tab-disabled").textContent).toContain("3");
  });

  it("renders 0 for a status not present in counts", () => {
    const active = signal<FilterValue>("all");
    const { getByTestId } = render(<StatusFilter active={active} counts={{}} />);
    expect(getByTestId("tab-running").textContent).toContain("0");
  });

  it("clicking a tab sets active signal to that filter", () => {
    const active = signal<FilterValue>("all");
    const { getByTestId } = render(<StatusFilter active={active} counts={createCounts()} />);

    fireEvent.click(getByTestId("tab-running").querySelector("button")!);
    expect(active.value).toBe("running");
  });

  it("clicking All tab resets active signal to 'all'", () => {
    const active = signal<FilterValue>("failed");
    const { getByTestId } = render(<StatusFilter active={active} counts={createCounts()} />);

    fireEvent.click(getByTestId("tab-all").querySelector("button")!);
    expect(active.value).toBe("all");
  });

  it("clicking failed tab sets active to 'failed'", () => {
    const active = signal<FilterValue>("all");
    const { getByTestId } = render(<StatusFilter active={active} counts={createCounts()} />);

    fireEvent.click(getByTestId("tab-failed").querySelector("button")!);
    expect(active.value).toBe("failed");
  });

  it("active tab button has aria-pressed=true", () => {
    const active = signal<FilterValue>("running");
    const { getByTestId } = render(<StatusFilter active={active} counts={createCounts()} />);
    const runningBtn = getByTestId("tab-running").querySelector("button")!;
    expect(runningBtn.getAttribute("aria-pressed")).toBe("true");
  });

  it("inactive tab buttons have aria-pressed=false", () => {
    const active = signal<FilterValue>("running");
    const { getByTestId } = render(<StatusFilter active={active} counts={createCounts()} />);
    const allBtn = getByTestId("tab-all").querySelector("button")!;
    expect(allBtn.getAttribute("aria-pressed")).toBe("false");
  });

  it("renders container with role=group and aria-label for accessibility", () => {
    const active = signal<FilterValue>("all");
    const { container } = render(<StatusFilter active={active} counts={createCounts()} />);
    const group = container.querySelector("[role='group']");
    expect(group).not.toBeNull();
    expect(group!.getAttribute("aria-label")).toBe("App status filter");
  });

  it("tab labels are capitalized (All, Running, Failed, etc.)", () => {
    const active = signal<FilterValue>("all");
    const { getByTestId } = render(<StatusFilter active={active} counts={createCounts()} />);
    expect(getByTestId("tab-all").textContent).toContain("All");
    expect(getByTestId("tab-running").textContent).toContain("Running");
    expect(getByTestId("tab-stopped").textContent).toContain("Stopped");
  });
});

import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { FrameworkHealth } from "./framework-health";
import type { FrameworkSummary } from "../../api/endpoints";

vi.mock("../../hooks/use-scoped-api", () => ({
  useScopedApi: vi.fn(),
}));

import { useScopedApi } from "../../hooks/use-scoped-api";

function makeSummary(data: FrameworkSummary | null = null) {
  return {
    data: signal(data),
    loading: signal(false),
    error: signal<string | null>(null),
    refetch: vi.fn(),
  };
}

describe("FrameworkHealth", () => {
  it("test_renders_count_badge: shows error count badge", () => {
    vi.mocked(useScopedApi).mockReturnValue(
      makeSummary({ total_errors: 3, total_job_errors: 1 }),
    );
    const { getByTestId } = render(<FrameworkHealth />);
    const badge = getByTestId("framework-error-count");
    expect(badge.textContent).toBe("4");
  });

  it("shows zero count when no errors", () => {
    vi.mocked(useScopedApi).mockReturnValue(
      makeSummary({ total_errors: 0, total_job_errors: 0 }),
    );
    const { getByTestId } = render(<FrameworkHealth />);
    const badge = getByTestId("framework-error-count");
    expect(badge.textContent).toBe("0");
    expect(badge.className).toContain("ht-badge--success");
  });

  it("badge shows danger variant when errors present", () => {
    vi.mocked(useScopedApi).mockReturnValue(
      makeSummary({ total_errors: 2, total_job_errors: 0 }),
    );
    const { getByTestId } = render(<FrameworkHealth />);
    const badge = getByTestId("framework-error-count");
    expect(badge.className).toContain("ht-badge--danger");
  });

  it("test_no_error_feed_expansion: no expandable error list or aria-expanded", () => {
    vi.mocked(useScopedApi).mockReturnValue(
      makeSummary({ total_errors: 5, total_job_errors: 2 }),
    );
    const { container, queryByRole } = render(<FrameworkHealth />);
    // No expand button
    expect(queryByRole("button")).toBeNull();
    // No aria-expanded attribute anywhere
    expect(container.querySelector("[aria-expanded]")).toBeNull();
    // No error feed rendered
    expect(container.querySelector("[data-testid='dashboard-errors']")).toBeNull();
  });

  it("shows System Health label", () => {
    vi.mocked(useScopedApi).mockReturnValue(
      makeSummary({ total_errors: 0, total_job_errors: 0 }),
    );
    const { getByText } = render(<FrameworkHealth />);
    expect(getByText("System Health")).toBeDefined();
  });
});

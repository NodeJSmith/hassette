import { describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/preact";
import { HandlerHealthCard } from "./handler-health-card";
import { createListener, createJob } from "../../test/factories";
import { buildItems } from "./handler-list";

// Mock wouter for navigation assertions
const mockNavigate = vi.fn();

vi.mock("wouter", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: preact.ComponentChildren; [k: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
  ),
  useLocation: () => ["/", mockNavigate],
}));

function makeListenerItem(overrides: Parameters<typeof createListener>[0] = {}) {
  const listener = createListener({ listener_id: 1, ...overrides });
  return buildItems([listener], [])[0];
}

function makeJobItem(overrides: Parameters<typeof createJob>[0] = {}) {
  const job = createJob({ job_id: 1, ...overrides });
  return buildItems([], [job])[0];
}

function renderCard(
  item: ReturnType<typeof buildItems>[number],
  { appKey = "test_app", instanceQs = "" } = {},
) {
  return render(
    <HandlerHealthCard item={item} appKey={appKey} instanceQs={instanceQs} />,
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Test 1: Healthy listener renders name, kind chip, run count
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — healthy listener", () => {
  it("renders handler name, kind chip, and run count", () => {
    const item = makeListenerItem({
      listener_id: 42,
      handler_method: "on_motion",
      listener_kind: "state change",
      total_invocations: 5,
      failed: 0,
      timed_out: 0,
    });
    const { container, getByText } = renderCard(item);

    // Name should appear as a link
    const link = container.querySelector("a");
    expect(link).not.toBeNull();
    expect(link!.textContent).toContain("on_motion");

    // Kind chip
    expect(getByText("state change")).toBeDefined();

    // Run count via pluralize
    expect(container.textContent).toContain("5 calls");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 2: Healthy job renders name, kind chip, run count
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — healthy job", () => {
  it("renders handler name, kind chip, and run count", () => {
    const item = makeJobItem({
      job_id: 7,
      job_name: "my_task",
      trigger_type: "interval",
      total_executions: 3,
      failed: 0,
      timed_out: 0,
    });
    const { container, getByText } = renderCard(item);

    const link = container.querySelector("a");
    expect(link).not.toBeNull();
    expect(link!.textContent).toContain("my_task");

    // Kind chip for job
    expect(getByText("interval")).toBeDefined();

    // Run count via pluralize — jobs use "run"
    expect(container.textContent).toContain("3 runs");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 3: Failing handler shows error type and error message
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — failing handler", () => {
  it("shows error type and error message when handler is failing", () => {
    const item = makeListenerItem({
      listener_id: 1,
      failed: 2,
      last_error_type: "KeyError",
      last_error_message: "missing key 'state'",
    });
    const { container } = renderCard(item);

    expect(container.textContent).toContain("KeyError");
    expect(container.textContent).toContain("missing key 'state'");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 3b: Timed-out handler shows "timed out" as error type fallback
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — timed out handler", () => {
  it("shows 'timed out' when handler has timeouts but no error type", () => {
    const item = makeListenerItem({
      listener_id: 1,
      timed_out: 3,
      failed: 0,
      last_error_type: null,
      last_error_message: null,
    });
    const { container } = renderCard(item);

    expect(container.textContent).toContain("timed out");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 4: Healthy handler does not show error type or error message
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — no errors shown for healthy handler", () => {
  it("does not show error type or error message when handler is healthy", () => {
    const item = makeListenerItem({
      listener_id: 1,
      failed: 0,
      timed_out: 0,
      last_error_type: null,
      last_error_message: null,
    });
    const { container } = renderCard(item);

    // No error content should appear
    expect(container.textContent).not.toContain("KeyError");
    expect(container.textContent).not.toContain("missing key");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 5: Error rate shown when failed > 0
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — error rate shown when failed > 0", () => {
  it("shows error rate when there are failures", () => {
    const item = makeListenerItem({
      listener_id: 1,
      total_invocations: 10,
      failed: 2,
      last_error_type: "ValueError",
      last_error_message: "bad value",
    });
    const { container } = renderCard(item);

    // 2/10 = 20.0%
    expect(container.textContent).toContain("20.0%");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 6: Error rate omitted when failed is 0
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — error rate omitted when failed is 0", () => {
  it("does not show error rate when failed is 0", () => {
    const item = makeListenerItem({
      listener_id: 1,
      total_invocations: 10,
      failed: 0,
      timed_out: 0,
    });
    const { container } = renderCard(item);

    expect(container.textContent).not.toContain("%");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 7: Shows "—" for avg duration when it is 0
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — avg duration", () => {
  it("shows em dash for avg duration when avg_duration_ms is 0", () => {
    const item = makeListenerItem({
      listener_id: 1,
      avg_duration_ms: 0,
      last_invoked_at: 1000,
    });
    const { container } = renderCard(item);

    expect(container.textContent).toContain("—");
  });

  it("shows formatted duration when avg_duration_ms is positive", () => {
    const item = makeListenerItem({
      listener_id: 1,
      avg_duration_ms: 250,
    });
    const { container } = renderCard(item);

    expect(container.textContent).toContain("250.0ms");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 8: Shows "—" for last active when timestamp is null
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — last active dash when null", () => {
  it("shows em dash for last active when timestamp is null", () => {
    const item = makeListenerItem({
      listener_id: 1,
      avg_duration_ms: 150,
      last_invoked_at: null,
    });
    const { container } = renderCard(item);

    expect(container.textContent).toContain("150.0ms");
    expect(container.textContent).toContain("—");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 9: Whole card click navigates to correct handler detail path
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — card click navigation", () => {
  it("navigates to handler detail page when card is clicked", () => {
    mockNavigate.mockClear();
    const item = makeListenerItem({ listener_id: 4 });
    const { getByTestId } = renderCard(item, { appKey: "my_app" });

    const card = getByTestId("overview-health-card-listener-4");
    fireEvent.click(card);

    expect(mockNavigate).toHaveBeenCalledWith("/apps/my_app/handlers/h-4");
  });

  it("navigates to job handler detail page when job card is clicked", () => {
    mockNavigate.mockClear();
    const item = makeJobItem({ job_id: 9 });
    const { getByTestId } = renderCard(item, { appKey: "my_app" });

    const card = getByTestId("overview-health-card-job-9");
    fireEvent.click(card);

    expect(mockNavigate).toHaveBeenCalledWith("/apps/my_app/handlers/j-9");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 10: Enter key on focused card navigates
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — Enter key navigation", () => {
  it("navigates when Enter key is pressed on the card", () => {
    mockNavigate.mockClear();
    const item = makeListenerItem({ listener_id: 5 });
    const { getByTestId } = renderCard(item, { appKey: "my_app" });

    const card = getByTestId("overview-health-card-listener-5");
    fireEvent.keyDown(card, { key: "Enter" });

    expect(mockNavigate).toHaveBeenCalledWith("/apps/my_app/handlers/h-5");
  });

  it("navigates when Space key is pressed on the card", () => {
    mockNavigate.mockClear();
    const item = makeListenerItem({ listener_id: 5 });
    const { getByTestId } = renderCard(item, { appKey: "my_app" });

    const card = getByTestId("overview-health-card-listener-5");
    fireEvent.keyDown(card, { key: " " });

    expect(mockNavigate).toHaveBeenCalledWith("/apps/my_app/handlers/h-5");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 11: Name link click navigates without double navigation (stopPropagation)
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — name link stopPropagation", () => {
  it("name link click does not trigger card onClick (stopPropagation)", () => {
    mockNavigate.mockClear();
    const item = makeListenerItem({ listener_id: 6 });
    const { container } = renderCard(item, { appKey: "my_app" });

    const link = container.querySelector("a");
    expect(link).not.toBeNull();

    fireEvent.click(link!);

    // Card's navigate should NOT have been called (stopPropagation prevents it)
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 12: Long handler name gets the name CSS class (truncation)
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — long name CSS class", () => {
  it("applies name class to the handler name link", () => {
    const item = makeListenerItem({
      listener_id: 1,
      handler_method: "a_very_long_handler_method_name_that_should_truncate",
    });
    const { container } = renderCard(item);

    // The link should have the .name CSS module class applied
    const link = container.querySelector("a");
    expect(link).not.toBeNull();
    // The link should have a class attribute (CSS module class for truncation)
    expect(link!.className).toBeTruthy();
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Test 13: data-testid includes kind and id
// ──────────────────────────────────────────────────────────────────────────────

describe("HandlerHealthCard — data-testid", () => {
  it("includes kind and id in data-testid for listener", () => {
    const item = makeListenerItem({ listener_id: 99 });
    const { getByTestId } = renderCard(item);
    expect(getByTestId("overview-health-card-listener-99")).toBeDefined();
  });

  it("includes kind and id in data-testid for job", () => {
    const item = makeJobItem({ job_id: 77 });
    const { getByTestId } = renderCard(item);
    expect(getByTestId("overview-health-card-job-77")).toBeDefined();
  });
});

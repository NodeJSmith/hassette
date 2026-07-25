import { signal } from "@preact/signals";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockMediaQueryMatches, renderWithAppState } from "../../test/render-helpers";
import { SystemHealth } from "./system-health";

describe("SystemHealth — connection states", () => {
  it("renders connected state with visually-hidden status text", () => {
    const { getByTestId } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: { connection: signal("connected") },
    });
    const indicator = getByTestId("ws-indicator");
    expect(indicator.getAttribute("role")).toBe("status");
    expect(indicator.textContent).toBe("Connected");
  });

  it("renders connecting state with visible text label", () => {
    const { getByText } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: { connection: signal("connecting") },
    });
    expect(getByText("Connecting...")).toBeDefined();
  });

  it("renders disconnected state with visible text label", () => {
    const { getByText, getByTestId } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: { connection: signal("disconnected") },
    });
    expect(getByText("Disconnected")).toBeDefined();
    expect(getByTestId("ws-indicator").getAttribute("role")).toBe("status");
  });

  it("renders reconnecting state with visible text label", () => {
    const { getByText, getByTestId } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: { connection: signal("reconnecting") },
    });
    expect(getByText("Reconnecting...")).toBeDefined();
    expect(getByTestId("ws-indicator").getAttribute("role")).toBe("status");
  });

  it("always includes status text for screen readers", () => {
    const { getByTestId } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: { connection: signal("disconnected") },
    });
    expect(getByTestId("ws-indicator").textContent).toBe("Disconnected");
  });

  it("shows the connected label visibly in the stacked variant", () => {
    const { getByText } = renderWithAppState(<SystemHealth variant="stacked" />, {
      stateOverrides: { connection: signal("connected") },
    });
    expect(getByText("Connected").className).not.toContain("visually-hidden");
  });
});

describe("SystemHealth — compact labels at mobile widths", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("clips the connection label instead of dropping it", () => {
    mockMediaQueryMatches(true);
    const { getByTestId } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: { connection: signal("disconnected") },
    });
    const label = getByTestId("ws-indicator").querySelector("[data-testid='health-label']");
    // Clipped, not removed — the live region still has to announce the change.
    expect(label?.className).toContain("visually-hidden");
    expect(getByTestId("ws-indicator").textContent).toBe("Disconnected");
  });

  it("clips the alert labels so the cluster reads as bare dots", () => {
    mockMediaQueryMatches(true);
    const { getByTestId } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: { errorHandlerFailures: signal(2) },
    });
    const indicator = getByTestId("error-handler-failures-indicator");
    expect(indicator.querySelector("[data-testid='health-label']")?.className).toContain("visually-hidden");
    expect(indicator.getAttribute("aria-label")).toBe("2 handler errors");
  });

  it("keeps labels visible in the stacked variant at the same width", () => {
    mockMediaQueryMatches(true);
    const { getByText } = renderWithAppState(<SystemHealth variant="stacked" />, {
      stateOverrides: { connection: signal("disconnected") },
    });
    expect(getByText("Disconnected").className).not.toContain("visually-hidden");
  });
});

describe("SystemHealth — database degraded indicator", () => {
  it("shows database degraded indicator when connected and degraded", () => {
    const { getByLabelText } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: {
        connection: signal("connected"),
        telemetryDegraded: signal(true),
      },
    });
    expect(getByLabelText("database degraded")).toBeDefined();
  });

  it("hides database degraded indicator when disconnected even if degraded", () => {
    const { queryByLabelText } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: {
        connection: signal("disconnected"),
        telemetryDegraded: signal(true),
      },
    });
    expect(queryByLabelText("database degraded")).toBeNull();
  });

  it("hides database degraded indicator when not degraded", () => {
    const { queryByLabelText } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: {
        connection: signal("connected"),
        telemetryDegraded: signal(false),
      },
    });
    expect(queryByLabelText("database degraded")).toBeNull();
  });
});

describe("SystemHealth — dropped events indicator", () => {
  it("shows dropped events when overflow > 0", () => {
    const { getByTestId } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: {
        connection: signal("connected"),
        droppedOverflow: signal(3),
        droppedExhausted: signal(0),
        droppedShutdown: signal(0),
      },
    });
    expect(getByTestId("dropped-events-indicator").textContent).toContain("3 dropped");
  });

  it("sums all drop counters in the label", () => {
    const { getByTestId } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: {
        connection: signal("connected"),
        droppedOverflow: signal(1),
        droppedExhausted: signal(2),
        droppedShutdown: signal(1),
      },
    });
    expect(getByTestId("dropped-events-indicator").textContent).toContain("4 dropped");
  });

  it("hides dropped events indicator when total is 0", () => {
    const { queryByTestId } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: {
        droppedOverflow: signal(0),
        droppedExhausted: signal(0),
        droppedShutdown: signal(0),
      },
    });
    expect(queryByTestId("dropped-events-indicator")).toBeNull();
  });
});

describe("SystemHealth — error handler failures indicator", () => {
  it("shows error handler failures when > 0", () => {
    const { getByTestId } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: { errorHandlerFailures: signal(2) },
    });
    expect(getByTestId("error-handler-failures-indicator")).toBeDefined();
  });

  it("hides error handler failures when 0", () => {
    const { queryByTestId } = renderWithAppState(<SystemHealth variant="compact" />, {
      stateOverrides: { errorHandlerFailures: signal(0) },
    });
    expect(queryByTestId("error-handler-failures-indicator")).toBeNull();
  });
});

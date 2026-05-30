import { signal } from "@preact/signals";
import { fireEvent } from "@testing-library/preact";
import type { ComponentProps } from "preact";
import { createRef } from "preact";
import { describe, expect, it, vi } from "vitest";

import { renderWithAppState } from "../../test/render-helpers";
import { StatusBar } from "./status-bar";

const baseProps: ComponentProps<typeof StatusBar> = {
  onMenuClick: vi.fn(),
  drawerOpen: false,
  hamburgerRef: createRef(),
};

// Mock setStoredValue so theme changes don't hit localStorage
vi.mock("../../utils/local-storage", () => ({
  setStoredValue: vi.fn(),
  getStoredValue: vi.fn(),
}));

// TimePresetSelector now calls useQueryParams (useSearch from wouter).
// StatusBar tests render without a Router provider, so mock the hook.
vi.mock("../../hooks/use-query-params", () => ({
  useQueryParams: () => ({ get: () => null, set: vi.fn() }),
}));

describe("StatusBar — connection states", () => {
  it("renders connected state with visually-hidden status text", () => {
    const { getByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: { connection: signal("connected") },
    });
    const indicator = getByTestId("ws-indicator");
    expect(indicator.getAttribute("role")).toBe("status");
    expect(indicator.textContent).toBe("Connected");
  });

  it("renders connecting state with visible text label", () => {
    const { getByText } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: { connection: signal("connecting") },
    });
    expect(getByText("Connecting...")).toBeDefined();
  });

  it("renders disconnected state with visible text label", () => {
    const { getByText, getByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: { connection: signal("disconnected") },
    });
    expect(getByText("Disconnected")).toBeDefined();
    const indicator = getByTestId("ws-indicator");
    expect(indicator.getAttribute("role")).toBe("status");
  });

  it("renders reconnecting state with visible text label", () => {
    const { getByText, getByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: { connection: signal("reconnecting") },
    });
    expect(getByText("Reconnecting...")).toBeDefined();
    const indicator = getByTestId("ws-indicator");
    expect(indicator.getAttribute("role")).toBe("status");
  });

  it("uses role=status for screen reader announcements", () => {
    const { getByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: { connection: signal("connected") },
    });
    const indicator = getByTestId("ws-indicator");
    expect(indicator.getAttribute("role")).toBe("status");
  });

  it("always includes status text for screen readers", () => {
    const { getByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: { connection: signal("disconnected") },
    });
    const indicator = getByTestId("ws-indicator");
    expect(indicator.textContent).toBe("Disconnected");
  });
});

describe("StatusBar — database degraded indicator", () => {
  it("shows database degraded indicator when connected and degraded", () => {
    const { getByLabelText } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: {
        connection: signal("connected"),
        telemetryDegraded: signal(true),
      },
    });
    expect(getByLabelText("database degraded")).toBeDefined();
  });

  it("hides database degraded indicator when disconnected even if degraded", () => {
    const { queryByLabelText } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: {
        connection: signal("disconnected"),
        telemetryDegraded: signal(true),
      },
    });
    expect(queryByLabelText("database degraded")).toBeNull();
  });

  it("hides database degraded indicator when not degraded", () => {
    const { queryByLabelText } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: {
        connection: signal("connected"),
        telemetryDegraded: signal(false),
      },
    });
    expect(queryByLabelText("database degraded")).toBeNull();
  });
});

describe("StatusBar — dropped events indicator", () => {
  it("shows dropped events when overflow > 0", () => {
    const { getByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: {
        connection: signal("connected"),
        droppedOverflow: signal(3),
        droppedExhausted: signal(0),
        droppedShutdown: signal(0),
      },
    });
    const indicator = getByTestId("dropped-events-indicator");
    expect(indicator.textContent).toContain("3 dropped");
  });

  it("sums all drop counters in the label", () => {
    const { getByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: {
        connection: signal("connected"),
        droppedOverflow: signal(1),
        droppedExhausted: signal(2),
        droppedShutdown: signal(1),
      },
    });
    const indicator = getByTestId("dropped-events-indicator");
    expect(indicator.textContent).toContain("4 dropped");
  });

  it("hides dropped events indicator when total is 0", () => {
    const { queryByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: {
        droppedOverflow: signal(0),
        droppedExhausted: signal(0),
        droppedShutdown: signal(0),
      },
    });
    expect(queryByTestId("dropped-events-indicator")).toBeNull();
  });
});

describe("StatusBar — error handler failures indicator", () => {
  it("shows error handler failures when > 0", () => {
    const { getByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: { errorHandlerFailures: signal(2) },
    });
    expect(getByTestId("error-handler-failures-indicator")).toBeDefined();
  });

  it("hides error handler failures when 0", () => {
    const { queryByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: { errorHandlerFailures: signal(0) },
    });
    expect(queryByTestId("error-handler-failures-indicator")).toBeNull();
  });
});

describe("StatusBar — theme toggle", () => {
  it("renders theme toggle button", () => {
    const { getByTestId } = renderWithAppState(<StatusBar {...baseProps} />);
    expect(getByTestId("theme-toggle")).toBeDefined();
  });

  it("toggles theme from dark to light on click", () => {
    const themeSignal = signal<"dark" | "light">("dark");
    const { getByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: { theme: themeSignal },
    });
    const button = getByTestId("theme-toggle");
    expect(button.getAttribute("aria-label")).toBe("Switch to light mode");
    fireEvent.click(button);
    expect(themeSignal.value).toBe("light");
  });

  it("toggles theme from light to dark on click", () => {
    const themeSignal = signal<"dark" | "light">("light");
    const { getByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      stateOverrides: { theme: themeSignal },
    });
    const button = getByTestId("theme-toggle");
    expect(button.getAttribute("aria-label")).toBe("Switch to dark mode");
    fireEvent.click(button);
    expect(themeSignal.value).toBe("dark");
  });
});

describe("StatusBar — time preset selector", () => {
  it("renders the time preset selector", () => {
    const { container } = renderWithAppState(<StatusBar {...baseProps} />);
    expect(container.querySelector("[data-testid='time-preset-selector']")).not.toBeNull();
  });

  it("renders all 4 time preset buttons", () => {
    const { getByText } = renderWithAppState(<StatusBar {...baseProps} />);
    expect(getByText("Since restart")).toBeDefined();
    expect(getByText("1h")).toBeDefined();
    expect(getByText("24h")).toBeDefined();
    expect(getByText("7d")).toBeDefined();
  });
});

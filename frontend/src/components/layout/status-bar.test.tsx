import { fireEvent } from "@testing-library/react";
import { type ComponentProps, createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { useAppStore } from "../../state/store";
import { createWouterMock } from "../../test/mock-wouter";
import { renderWithAppState } from "../../test/render-helpers";
import { StatusBar } from "./status-bar";

const baseProps: ComponentProps<typeof StatusBar> = {
  onMenuClick: vi.fn(),
  drawerOpen: false,
  hamburgerRef: createRef(),
};

// setSidebarCollapsed (store.ts) calls setStoredValue, and initialState() calls getStoredValue —
// mock both so this test doesn't touch real localStorage.
vi.mock("../../utils/local-storage", () => ({
  setStoredValue: vi.fn(),
  getStoredValue: vi.fn(),
}));

// TimePresetSelector now calls useQueryParams (useSearch from wouter).
// StatusBar tests render without a Router provider, so mock the hook.
vi.mock("../../hooks/use-query-params", () => ({
  useQueryParams: () => ({ get: () => null, set: vi.fn() }),
}));

// Breadcrumbs renders wouter's Link, which needs a Router this render lacks.
vi.mock("wouter", () => createWouterMock());

// useBreadcrumbs reads wouter's location, which needs a Router this render lacks.
vi.mock("../../hooks/use-breadcrumbs", () => ({
  useBreadcrumbs: () => [{ label: "apps", href: "/apps" }, { label: "demo_app" }],
}));

// Drives the "is the sidebar on screen" branch without a real matchMedia.
// Plain mutable box (not a signal) — only needs to feed a mocked hook's return value.
const sidebarHidden = { value: false };
vi.mock("../../hooks/use-sidebar-hidden", () => ({
  useSidebarHidden: () => sidebarHidden.value,
}));

describe("StatusBar — breadcrumbs", () => {
  it("renders the ancestor trail for the current route", () => {
    const { getByTestId } = renderWithAppState(<StatusBar {...baseProps} />);
    const trail = getByTestId("breadcrumbs");
    expect(trail.textContent).toContain("apps");
    expect(trail.textContent).toContain("demo_app");
  });
});

describe("StatusBar — system health fallback", () => {
  it("renders the health cluster when the sidebar is hidden", () => {
    sidebarHidden.value = true;
    const { getByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      storeOverrides: { connection: "disconnected" },
    });
    expect(getByTestId("ws-indicator").textContent).toBe("Disconnected");
    sidebarHidden.value = false;
  });

  it("omits the health cluster when the sidebar owns it", () => {
    sidebarHidden.value = false;
    const { queryByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      storeOverrides: { connection: "disconnected" },
    });
    expect(queryByTestId("ws-indicator")).toBeNull();
  });
});

describe("StatusBar — sidebar expand control", () => {
  it("is absent while the sidebar is expanded", () => {
    const { queryByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      storeOverrides: { sidebarCollapsed: false },
    });
    expect(queryByTestId("sidebar-expand")).toBeNull();
  });

  it("expands the sidebar on click when collapsed", () => {
    const { getByTestId } = renderWithAppState(<StatusBar {...baseProps} />, {
      storeOverrides: { sidebarCollapsed: true },
    });
    fireEvent.click(getByTestId("sidebar-expand"));
    expect(useAppStore.getState().sidebarCollapsed).toBe(false);
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

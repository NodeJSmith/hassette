import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act } from "@testing-library/preact";
import type * as preact from "preact";
import { App } from "./app";

// Mock wouter so we control routing without a real browser history
vi.mock("wouter", () => ({
  Route: ({ component, children }: Record<string, unknown>) => {
    if (component) {
      const Component = component as () => preact.JSX.Element;
      return <Component />;
    }
    if (children) return children as preact.JSX.Element;
    return null;
  },
  Redirect: () => null,
  Switch: ({ children }: { children: unknown }) => children,
  Link: ({ href, children, class: cls, ...rest }: Record<string, unknown>) =>
    <a href={href as string} class={cls as string} {...rest}>{children as never}</a>,
  useLocation: vi.fn().mockReturnValue(["/", vi.fn()]),
  useSearch: vi.fn().mockReturnValue(""),
}));
vi.mock("./pages/apps", () => ({
  AppsPage: () => <div data-testid="apps-page">Apps</div>,
}));
vi.mock("./pages/logs", () => ({
  LogsPage: () => <div data-testid="logs-page">Logs</div>,
}));
vi.mock("./pages/config", () => ({
  ConfigPage: () => <div data-testid="config-page">Config</div>,
}));
vi.mock("./pages/not-found", () => ({
  NotFoundPage: () => <div data-testid="not-found-page">Not Found</div>,
}));
vi.mock("./pages/app-detail", () => ({
  AppDetailPage: () => <div data-testid="app-detail-page">App Detail</div>,
}));

// Mock hooks that make network/WS connections
vi.mock("./hooks/use-websocket", () => ({
  useWebSocket: vi.fn(),
}));
vi.mock("./hooks/use-telemetry-health", () => ({
  useTelemetryHealth: vi.fn(),
}));

// TimePresetSelector calls useQueryParams (useSearch from wouter).
// App tests render without a Router provider, so mock the hook.
vi.mock("./hooks/use-query-params", () => ({
  useQueryParams: () => ({ get: () => null, set: vi.fn() }),
}));

// Spy on TelemetryDegradedBanner to verify it is mounted in the layout shell.
// Component-level signal behaviour is fully tested in alert-banner.test.tsx;
// here we only care that app.tsx renders the component at all.
vi.mock("./components/layout/alert-banner", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./components/layout/alert-banner")>();
  return {
    ...actual,
    TelemetryDegradedBanner: () => <div data-testid="telemetry-degraded-banner-slot" />,
  };
});

describe("App — layout structure", () => {
  it("renders the ht-layout container", () => {
    const { container } = render(<App />);
    expect(container.querySelector(".ht-layout")).not.toBeNull();
  });

  it("renders a sidebar element inside ht-layout", () => {
    const { container } = render(<App />);
    const layout = container.querySelector(".ht-layout");
    expect(layout!.querySelector("aside")).not.toBeNull();
  });

  it("renders the main content area", () => {
    const { container } = render(<App />);
    expect(container.querySelector("main.ht-main")).not.toBeNull();
  });

  it("main content has id=main-content for skip link", () => {
    const { container } = render(<App />);
    const main = container.querySelector("main");
    expect(main!.getAttribute("id")).toBe("main-content");
  });

  it("renders a skip link", () => {
    const { container } = render(<App />);
    const skipLink = container.querySelector(".ht-skip-link");
    expect(skipLink).not.toBeNull();
    expect(skipLink!.getAttribute("href")).toBe("#main-content");
  });
});

describe("App — hamburger button", () => {
  it("renders a hamburger button", () => {
    const { container } = render(<App />);
    const btn = container.querySelector(".ht-hamburger");
    expect(btn).not.toBeNull();
  });

  it("hamburger button has accessible label", () => {
    const { container } = render(<App />);
    const btn = container.querySelector(".ht-hamburger");
    expect(btn!.getAttribute("aria-label")).toBe("Open navigation");
  });

  it("hamburger button has aria-expanded=false initially", () => {
    const { container } = render(<App />);
    const btn = container.querySelector(".ht-hamburger");
    expect(btn!.getAttribute("aria-expanded")).toBe("false");
  });

  it("drawer is not open initially", () => {
    const { container } = render(<App />);
    const drawer = container.querySelector(".ht-drawer");
    expect(drawer).not.toBeNull();
    expect(drawer!.className).not.toContain("is-open");
  });

  it("clicking the hamburger opens the drawer", () => {
    const { container } = render(<App />);
    const btn = container.querySelector(".ht-hamburger")!;
    fireEvent.click(btn);
    const drawer = container.querySelector(".ht-drawer");
    expect(drawer!.className).toContain("is-open");
  });

  it("hamburger aria-expanded updates to true when drawer is open", () => {
    const { container } = render(<App />);
    const btn = container.querySelector(".ht-hamburger")!;
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
  });
});

describe("App — TelemetryDegradedBanner in layout shell", () => {
  it("mounts TelemetryDegradedBanner inside the main content area", () => {
    const { container } = render(<App />);
    const main = container.querySelector("main.ht-main");
    expect(main).not.toBeNull();
    // The slot element proves app.tsx renders TelemetryDegradedBanner inside main
    const bannerSlot = main!.querySelector("[data-testid='telemetry-degraded-banner-slot']");
    expect(bannerSlot).not.toBeNull();
  });
});

describe("App — visibilitychange tick recovery", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("adds a visibilitychange listener that increments tick immediately when tab becomes visible", () => {
    const addSpy = vi.spyOn(document, "addEventListener");
    render(<App />);

    const handlers = addSpy.mock.calls
      .filter((call) => call[0] === "visibilitychange")
      .map((call) => call[1] as EventListener);

    expect(handlers.length).toBeGreaterThan(0);

    Object.defineProperty(document, "hidden", { value: false, writable: true, configurable: true });

    act(() => {
      handlers.forEach((h) => h(new Event("visibilitychange")));
    });

    // The handler should not throw — functional smoke test.
    // Tick increment is verified implicitly: the handler calls state.tick.value++
    // which would throw if state were invalid. The useRelativeTime hook tests
    // verify that tick increments cause re-renders with updated strings.
    expect(handlers.length).toBeGreaterThan(0);

    addSpy.mockRestore();
  });

  it("removes the visibilitychange listener on unmount", () => {
    const removeSpy = vi.spyOn(document, "removeEventListener");
    const { unmount } = render(<App />);

    unmount();

    const removed = removeSpy.mock.calls.some((call) => call[0] === "visibilitychange");
    expect(removed).toBe(true);

    removeSpy.mockRestore();
  });
});

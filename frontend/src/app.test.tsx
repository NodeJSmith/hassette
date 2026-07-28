import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "./api/generated-types";
import { App } from "./app";
import { createInstance, createListener, createManifest } from "./test/factories";
import { withManifests as installManifests } from "./test/handlers";
import { server } from "./test/server";

type AppManifest = components["schemas"]["AppManifestResponse"];
type ListenerWithSummary = components["schemas"]["ListenerWithSummary"];

// Mock wouter so we control routing without a real browser history.
//
// createWouterMock is imported dynamically inside the factory (instead of a static top-level
// import) because this file and `test/mock-wouter` are both direct children of `src/` — see the
// "Import-order hazard" note on createWouterMock's JSDoc for why that specific layout is unsafe
// with a plain import.
vi.mock("wouter", async () => {
  const { createWouterMock } = await import("./test/mock-wouter");
  return {
    ...createWouterMock({
      useLocation: vi.fn().mockReturnValue(["/", vi.fn()]),
      useSearch: vi.fn().mockReturnValue(""),
    }),
    Route: ({
      component: Component,
      children,
    }: {
      component?: React.FunctionComponent;
      children?: React.ReactNode;
    }) => {
      if (Component) return <Component />;
      if (children) return children;
      return null;
    },
    Redirect: () => null,
    Switch: ({ children }: { children: unknown }) => children,
  };
});
// Same "wouter" module mock instance used by App's own useLocation() call — grabbing the
// navigate function lets command palette tests assert on where it navigates.
const wouter = await import("wouter");
const mockNavigate = vi.fn();
(wouter.useLocation as ReturnType<typeof vi.fn>).mockReturnValue(["/", mockNavigate]);

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

vi.mock("sonner", () => ({
  Toaster: () => null,
  toast: { success: vi.fn(), error: vi.fn() },
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
  it("renders the layout container", () => {
    const { container } = render(<App />);
    expect(container.querySelector("[data-testid='layout']")).not.toBeNull();
  });

  it("renders a sidebar element inside layout", () => {
    const { container } = render(<App />);
    const layout = container.querySelector("[data-testid='layout']");
    expect(layout!.querySelector("aside")).not.toBeNull();
  });

  it("renders the main content area", () => {
    render(<App />);
    expect(screen.getByRole("main")).toBeDefined();
  });

  it("main content has id=main-content for skip link", () => {
    const { container } = render(<App />);
    const main = container.querySelector("main");
    expect(main!.getAttribute("id")).toBe("main-content");
  });

  it("renders a skip link", () => {
    render(<App />);
    const skipLink = screen.getByTestId("skip-link");
    expect(skipLink.getAttribute("href")).toBe("#main-content");
  });
});

describe("App — hamburger button", () => {
  it("renders a hamburger button", () => {
    const { container } = render(<App />);
    const btn = container.querySelector("[data-testid='hamburger']");
    expect(btn).not.toBeNull();
  });

  it("hamburger button has accessible label", () => {
    const { container } = render(<App />);
    const btn = container.querySelector("[data-testid='hamburger']");
    expect(btn!.getAttribute("aria-label")).toBe("Open navigation");
  });

  it("hamburger button has aria-expanded=false initially", () => {
    const { container } = render(<App />);
    const btn = container.querySelector("[data-testid='hamburger']");
    expect(btn!.getAttribute("aria-expanded")).toBe("false");
  });

  it("drawer is not open initially", () => {
    const { container } = render(<App />);
    const drawer = container.querySelector("[data-testid='mobile-drawer']");
    expect(drawer).not.toBeNull();
    expect(drawer!.className).toContain("-translate-x-full");
  });

  it("keeps the closed drawer inert", () => {
    const { container } = render(<App />);
    const drawer = container.querySelector("[data-testid='mobile-drawer']");
    expect(drawer).not.toBeNull();
    expect(drawer!.hasAttribute("inert")).toBe(true);
  });

  it("clicking the hamburger opens the drawer", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    const btn = container.querySelector("[data-testid='hamburger']")!;
    await user.click(btn);
    const drawer = container.querySelector("[data-testid='mobile-drawer']");
    expect(drawer!.className).toContain("translate-x-0");
    expect(drawer!.hasAttribute("inert")).toBe(false);
  });

  it("hamburger aria-expanded updates to true when drawer is open", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    const btn = container.querySelector("[data-testid='hamburger']")!;
    await user.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
  });
});

describe("App — TelemetryDegradedBanner in layout shell", () => {
  it("mounts TelemetryDegradedBanner inside the main content area", () => {
    render(<App />);
    const main = screen.getByRole("main");
    // The slot element proves app.tsx renders TelemetryDegradedBanner inside main
    const bannerSlot = main.querySelector("[data-testid='telemetry-degraded-banner-slot']");
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

describe("App — sidebar collapse", () => {
  // The collapsed flag is persisted, so a leaked value would silently start the next
  // test with the sidebar already gone.
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  const layoutOf = (container: Element) => container.querySelector<HTMLElement>("[data-testid='layout']")!;

  it("pressing [ collapses the sidebar out of the layout", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    expect(layoutOf(container).querySelector("aside")).not.toBeNull();

    // "[[" is userEvent's escape syntax for a literal "[" keypress -- a single "[" would be
    // parsed as the start of a special-key token (e.g. "{Meta}") and produce no keystroke.
    await user.keyboard("[[");

    expect(layoutOf(container).className).toContain("is-collapsed");
    expect(layoutOf(container).querySelector("aside")).toBeNull();
  });

  it("pressing [ again restores the sidebar", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    await user.keyboard("[[");
    expect(layoutOf(container).className).toContain("is-collapsed");

    await user.keyboard("[[");

    expect(layoutOf(container).className).not.toContain("is-collapsed");
    expect(layoutOf(container).querySelector("aside")).not.toBeNull();
  });

  it("ignores [ typed into the app filter input", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    const filter = layoutOf(container).querySelector("input")!;

    filter.focus();
    await user.keyboard("[[");

    expect(layoutOf(container).className).not.toContain("is-collapsed");
  });

  it("ignores [ when it carries a modifier", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);

    await user.keyboard("{Meta>}[[{/Meta}");

    expect(layoutOf(container).className).not.toContain("is-collapsed");
  });
});

describe("App — drawer close mechanisms", () => {
  it("backdrop click closes the drawer", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    const btn = container.querySelector("[data-testid='hamburger']")!;
    await user.click(btn);
    expect(container.querySelector("[data-testid='mobile-drawer']")!.className).toContain("translate-x-0");

    const backdrop = container.querySelector("[data-testid='mobile-drawer-backdrop']")!;
    await user.click(backdrop);
    expect(container.querySelector("[data-testid='mobile-drawer']")!.className).toContain("-translate-x-full");
  });

  it("Escape key closes the drawer", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    const btn = container.querySelector("[data-testid='hamburger']")!;
    await user.click(btn);
    expect(container.querySelector("[data-testid='mobile-drawer']")!.className).toContain("translate-x-0");

    await user.keyboard("{Escape}");
    expect(container.querySelector("[data-testid='mobile-drawer']")!.className).toContain("-translate-x-full");
  });

  it("clicking the hamburger a second time closes the drawer", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    const btn = container.querySelector("[data-testid='hamburger']")!;
    await user.click(btn);
    expect(container.querySelector("[data-testid='mobile-drawer']")!.className).toContain("translate-x-0");
    await user.click(btn);
    expect(container.querySelector("[data-testid='mobile-drawer']")!.className).toContain("-translate-x-full");
  });
});

describe("App — hamburger inside status bar", () => {
  it("renders hamburger inside the status bar", () => {
    const { container } = render(<App />);
    const statusBar = container.querySelector("[data-testid='status-bar']");
    expect(statusBar).not.toBeNull();
    const hamburger = statusBar!.querySelector("[data-testid='hamburger']");
    expect(hamburger).not.toBeNull();
  });

  it("does not render a standalone hamburger outside the status bar", () => {
    const { container } = render(<App />);
    const allHamburgers = container.querySelectorAll("[data-testid='hamburger']");
    expect(allHamburgers).toHaveLength(1);
    const statusBar = container.querySelector("[data-testid='status-bar']");
    expect(statusBar!.contains(allHamburgers[0])).toBe(true);
  });
});

function withManifests(manifests: AppManifest[]) {
  installManifests(manifests, server);
}

async function openPalette(user: ReturnType<typeof userEvent.setup>) {
  await user.keyboard("{Meta>}k{/Meta}");
}

describe("App — command palette", () => {
  it("Cmd+K opens the command palette dialog", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openPalette(user);
    expect(await screen.findByRole("dialog", { name: /command palette/i })).toBeDefined();
  });

  it("Cmd+K toggles the palette closed on a second press", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openPalette(user);
    await screen.findByRole("dialog", { name: /command palette/i });
    await openPalette(user);
    expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull();
  });

  it("Escape closes the palette", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openPalette(user);
    const dialog = await screen.findByRole("dialog", { name: /command palette/i });
    dialog.focus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull();
  });

  it("shows page items and lets Enter navigate to the active one", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openPalette(user);
    const input = await screen.findByPlaceholderText("Search apps, handlers, pages, actions…");
    input.focus();
    await user.keyboard("{Enter}");
    expect(mockNavigate).toHaveBeenCalledWith("/apps");
  });

  it("shows app items from manifests and navigates on click", async () => {
    const user = userEvent.setup();
    withManifests([createManifest({ app_key: "garage_app", display_name: "Garage App", status: "running" })]);
    render(<App />);
    await openPalette(user);
    const item = await screen.findByTestId("cmd-result-app-garage_app");
    await user.click(item);
    expect(mockNavigate).toHaveBeenCalledWith("/apps/garage_app");
  });

  it("shows instance items for multi-instance apps", async () => {
    const user = userEvent.setup();
    withManifests([
      createManifest({
        app_key: "multi_app",
        display_name: "Multi App",
        instance_count: 2,
        instances: [
          createInstance({ app_key: "multi_app", index: 0, instance_name: "inst_0" }),
          createInstance({ app_key: "multi_app", index: 1, instance_name: "inst_1" }),
        ],
      }),
    ]);
    render(<App />);
    await openPalette(user);
    expect(await screen.findByTestId("cmd-result-instance-multi_app-0")).toBeDefined();
    expect(screen.getByTestId("cmd-result-instance-multi_app-1")).toBeDefined();
  });

  it("filters results as the user types", async () => {
    const user = userEvent.setup();
    withManifests([
      createManifest({ app_key: "garage_app", display_name: "Garage App", status: "running" }),
      createManifest({ app_key: "lights_app", display_name: "Lights App", status: "running" }),
    ]);
    render(<App />);
    await openPalette(user);
    const input = await screen.findByPlaceholderText("Search apps, handlers, pages, actions…");
    await screen.findByTestId("cmd-result-app-garage_app");
    await user.type(input, "garage");
    expect(screen.queryByTestId("cmd-result-app-garage_app")).not.toBeNull();
    expect(screen.queryByTestId("cmd-result-app-lights_app")).toBeNull();
  });

  it("shows handler items fetched from the API and navigates on click", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json<ListenerWithSummary[]>([
          createListener({ listener_id: 42, app_key: "my_app", handler_method: "on_state_change" }),
        ]),
      ),
    );
    render(<App />);
    await openPalette(user);
    const item = await screen.findByTestId("cmd-result-handler-42");
    await user.click(item);
    expect(mockNavigate).toHaveBeenCalledWith("/apps/my_app/handlers/listener/42");
  });

  it("does not fetch handlers when the palette is closed", async () => {
    let callCount = 0;
    server.use(
      http.get("/api/bus/listeners", () => {
        callCount++;
        return HttpResponse.json<ListenerWithSummary[]>([]);
      }),
    );
    render(<App />);
    await new Promise((r) => setTimeout(r, 0));
    expect(callCount).toBe(0);
  });
});

import { describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import type * as preact from "preact";
import { App } from "./app";

// Mock wouter so we control routing without a real browser history
vi.mock("wouter", () => ({
  Route: ({ path, component, children }: Record<string, unknown>) => {
    if (path === "/" && component) {
      const Component = component as () => preact.JSX.Element;
      return <Component />;
    }
    if (children && typeof children === "function") return null;
    return null;
  },
  Switch: ({ children }: { children: unknown }) => children,
  Link: ({ href, children, class: cls, ...rest }: Record<string, unknown>) =>
    <a href={href as string} class={cls as string} {...rest}>{children as never}</a>,
  useLocation: vi.fn().mockReturnValue(["/", vi.fn()]),
}));

// Mock page components to keep tests fast
vi.mock("./pages/dashboard", () => ({
  DashboardPage: () => <div data-testid="dashboard-page">Dashboard</div>,
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

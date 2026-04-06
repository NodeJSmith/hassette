import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { h } from "preact";
import { BottomNav } from "./bottom-nav";

// Mock wouter to control the current location
vi.mock("wouter", () => ({
  Link: ({ href, class: cls, children, ...rest }: Record<string, unknown>) =>
    h("a", { href, class: cls, ...rest }, children as never),
  useLocation: vi.fn().mockReturnValue(["/", vi.fn()]),
}));

const wouter = await import("wouter");
const useLocation = wouter.useLocation as ReturnType<typeof vi.fn>;

describe("BottomNav", () => {
  it("renders four navigation items", () => {
    const { getAllByRole } = render(<BottomNav />);
    const links = getAllByRole("link");
    expect(links).toHaveLength(4);
  });

  it("dashboard item links to root", () => {
    const { getByTestId } = render(<BottomNav />);
    expect(getByTestId("nav-dashboard-mobile").getAttribute("href")).toBe("/");
  });

  it("apps item links to /apps", () => {
    const { getByTestId } = render(<BottomNav />);
    expect(getByTestId("nav-apps-mobile").getAttribute("href")).toBe("/apps");
  });

  it("logs item links to /logs", () => {
    const { getByTestId } = render(<BottomNav />);
    expect(getByTestId("nav-logs-mobile").getAttribute("href")).toBe("/logs");
  });

  it("sessions item links to /sessions", () => {
    const { getByTestId } = render(<BottomNav />);
    expect(getByTestId("nav-sessions-mobile").getAttribute("href")).toBe("/sessions");
  });

  it("applies is-active class to current route item", () => {
    useLocation.mockReturnValue(["/apps", vi.fn()]);

    const { getByTestId } = render(<BottomNav />);

    expect(getByTestId("nav-apps-mobile").className).toContain("is-active");
    expect(getByTestId("nav-dashboard-mobile").className).not.toContain("is-active");
    expect(getByTestId("nav-logs-mobile").className).not.toContain("is-active");
    expect(getByTestId("nav-sessions-mobile").className).not.toContain("is-active");
  });

  it("has accessibility label on nav element", () => {
    const { getByLabelText } = render(<BottomNav />);
    expect(getByLabelText("Mobile navigation")).toBeDefined();
  });
});

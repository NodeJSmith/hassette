import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { h } from "preact";
import { Sidebar } from "./sidebar";

// Mock wouter to control the current location
vi.mock("wouter", () => ({
  Link: ({ href, class: cls, children, "aria-label": ariaLabel, "aria-current": ariaCurrent, ...rest }: Record<string, unknown>) =>
    h("a", { href, class: cls, "aria-label": ariaLabel, "aria-current": ariaCurrent, ...rest }, children as never),
  useLocation: vi.fn().mockReturnValue(["/", vi.fn()]),
}));

const wouter = await import("wouter");
const useLocation = wouter.useLocation as ReturnType<typeof vi.fn>;

describe("Sidebar", () => {
  it("renders an aside element with correct class", () => {
    const { container } = render(<Sidebar />);
    expect(container.querySelector("aside.ht-sidebar")).not.toBeNull();
  });

  it("renders main navigation with accessibility label", () => {
    const { getByLabelText } = render(<Sidebar />);
    expect(getByLabelText("Main navigation")).toBeDefined();
  });

  it("renders four navigation links", () => {
    const { getAllByRole } = render(<Sidebar />);
    // Includes brand link + 4 nav links
    const links = getAllByRole("link");
    // Brand link + 4 nav items = 5 total
    expect(links.length).toBe(5);
  });

  it("renders dashboard nav link to root", () => {
    const { getByTestId } = render(<Sidebar />);
    const link = getByTestId("nav-dashboard");
    expect(link.getAttribute("href")).toBe("/");
  });

  it("renders apps nav link to /apps", () => {
    const { getByTestId } = render(<Sidebar />);
    const link = getByTestId("nav-apps");
    expect(link.getAttribute("href")).toBe("/apps");
  });

  it("renders logs nav link to /logs", () => {
    const { getByTestId } = render(<Sidebar />);
    const link = getByTestId("nav-logs");
    expect(link.getAttribute("href")).toBe("/logs");
  });

  it("renders sessions nav link to /sessions", () => {
    const { getByTestId } = render(<Sidebar />);
    const link = getByTestId("nav-sessions");
    expect(link.getAttribute("href")).toBe("/sessions");
  });

  it("applies is-active class to dashboard link when at root", () => {
    useLocation.mockReturnValue(["/", vi.fn()]);
    const { getByTestId } = render(<Sidebar />);
    expect(getByTestId("nav-dashboard").className).toContain("is-active");
    expect(getByTestId("nav-apps").className).not.toContain("is-active");
    expect(getByTestId("nav-logs").className).not.toContain("is-active");
    expect(getByTestId("nav-sessions").className).not.toContain("is-active");
  });

  it("applies is-active class to apps link when at /apps", () => {
    useLocation.mockReturnValue(["/apps", vi.fn()]);
    const { getByTestId } = render(<Sidebar />);
    expect(getByTestId("nav-apps").className).toContain("is-active");
    expect(getByTestId("nav-dashboard").className).not.toContain("is-active");
  });

  it("applies is-active class to logs link when at /logs", () => {
    useLocation.mockReturnValue(["/logs", vi.fn()]);
    const { getByTestId } = render(<Sidebar />);
    expect(getByTestId("nav-logs").className).toContain("is-active");
    expect(getByTestId("nav-dashboard").className).not.toContain("is-active");
  });

  it("applies is-active class to sessions link when at /sessions", () => {
    useLocation.mockReturnValue(["/sessions", vi.fn()]);
    const { getByTestId } = render(<Sidebar />);
    expect(getByTestId("nav-sessions").className).toContain("is-active");
    expect(getByTestId("nav-dashboard").className).not.toContain("is-active");
  });

  it("active link has aria-current='page'", () => {
    useLocation.mockReturnValue(["/apps", vi.fn()]);
    const { getByTestId } = render(<Sidebar />);
    expect(getByTestId("nav-apps").getAttribute("aria-current")).toBe("page");
    expect(getByTestId("nav-dashboard").getAttribute("aria-current")).toBeNull();
  });

  it("marks dashboard active when path starts with / (exact match only)", () => {
    // /apps should NOT activate dashboard
    useLocation.mockReturnValue(["/apps", vi.fn()]);
    const { getByTestId } = render(<Sidebar />);
    expect(getByTestId("nav-dashboard").className).not.toContain("is-active");
  });

  it("activates apps link on sub-path /apps/my_app", () => {
    useLocation.mockReturnValue(["/apps/my_app", vi.fn()]);
    const { getByTestId } = render(<Sidebar />);
    expect(getByTestId("nav-apps").className).toContain("is-active");
  });

  it("renders brand link to home", () => {
    const { getByLabelText } = render(<Sidebar />);
    const brandLink = getByLabelText("Hassette home");
    expect(brandLink.getAttribute("href")).toBe("/");
  });
});

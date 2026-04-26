import { describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { SessionScopeToggle } from "./session-scope-toggle";
import { renderWithAppState } from "../../test/render-helpers";

vi.mock("../../utils/local-storage", () => ({
  setStoredValue: vi.fn(),
  getStoredValue: vi.fn(),
}));

describe("SessionScopeToggle", () => {
  it("renders two scope buttons", () => {
    const { getAllByRole } = renderWithAppState(<SessionScopeToggle />);
    const buttons = getAllByRole("button");
    expect(buttons).toHaveLength(2);
  });

  it("renders 'This Session' button", () => {
    const { getByTestId } = renderWithAppState(<SessionScopeToggle />);
    const btn = getByTestId("scope-current");
    expect(btn.textContent).toBe("This Session");
  });

  it("renders 'All Time' button", () => {
    const { getByTestId } = renderWithAppState(<SessionScopeToggle />);
    const btn = getByTestId("scope-all");
    expect(btn.textContent).toBe("All Time");
  });

  it("marks current scope button as active by default", () => {
    const scopeSignal = signal<"current" | "all">("current");
    const { getByTestId } = renderWithAppState(<SessionScopeToggle />, {
      stateOverrides: { sessionScope: scopeSignal },
    });
    expect(getByTestId("scope-current").className).toContain("is-active");
    expect(getByTestId("scope-all").className).not.toContain("is-active");
  });

  it("marks all-time scope button as active when scope is 'all'", () => {
    const scopeSignal = signal<"current" | "all">("all");
    const { getByTestId } = renderWithAppState(<SessionScopeToggle />, {
      stateOverrides: { sessionScope: scopeSignal },
    });
    expect(getByTestId("scope-all").className).toContain("is-active");
    expect(getByTestId("scope-current").className).not.toContain("is-active");
  });

  it("active button has aria-pressed=true", () => {
    const scopeSignal = signal<"current" | "all">("current");
    const { getByTestId } = renderWithAppState(<SessionScopeToggle />, {
      stateOverrides: { sessionScope: scopeSignal },
    });
    expect(getByTestId("scope-current").getAttribute("aria-pressed")).toBe("true");
    expect(getByTestId("scope-all").getAttribute("aria-pressed")).toBe("false");
  });

  it("clicking 'All Time' changes scope signal to 'all'", () => {
    const scopeSignal = signal<"current" | "all">("current");
    const { getByTestId } = renderWithAppState(<SessionScopeToggle />, {
      stateOverrides: { sessionScope: scopeSignal },
    });
    fireEvent.click(getByTestId("scope-all"));
    expect(scopeSignal.value).toBe("all");
  });

  it("clicking 'This Session' changes scope signal to 'current'", () => {
    const scopeSignal = signal<"current" | "all">("all");
    const { getByTestId } = renderWithAppState(<SessionScopeToggle />, {
      stateOverrides: { sessionScope: scopeSignal },
    });
    fireEvent.click(getByTestId("scope-current"));
    expect(scopeSignal.value).toBe("current");
  });

  it("clicking the already-active button is a no-op", () => {
    const scopeSignal = signal<"current" | "all">("current");
    const { getByTestId } = renderWithAppState(<SessionScopeToggle />, {
      stateOverrides: { sessionScope: scopeSignal },
    });
    fireEvent.click(getByTestId("scope-current"));
    expect(scopeSignal.value).toBe("current");
  });

  it("container has role=group with accessibility label", () => {
    const { getByRole } = renderWithAppState(<SessionScopeToggle />);
    const group = getByRole("group", { name: /telemetry time scope/i });
    expect(group).toBeDefined();
  });
});

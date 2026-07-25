import { signal } from "@preact/signals";
import { fireEvent } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import { renderWithAppState } from "../../test/render-helpers";
import { ThemeToggle } from "./theme-toggle";

// Mock setStoredValue so theme changes don't hit localStorage
vi.mock("../../utils/local-storage", () => ({
  setStoredValue: vi.fn(),
  getStoredValue: vi.fn(),
}));

describe("ThemeToggle", () => {
  it("renders theme toggle button", () => {
    const { getByTestId } = renderWithAppState(<ThemeToggle />);
    expect(getByTestId("theme-toggle")).toBeDefined();
  });

  it("toggles theme from dark to light on click", () => {
    const themeSignal = signal<"dark" | "light">("dark");
    const { getByTestId } = renderWithAppState(<ThemeToggle />, {
      stateOverrides: { theme: themeSignal },
    });
    const button = getByTestId("theme-toggle");
    expect(button.getAttribute("aria-label")).toBe("Switch to light mode");
    fireEvent.click(button);
    expect(themeSignal.value).toBe("light");
  });

  it("toggles theme from light to dark on click", () => {
    const themeSignal = signal<"dark" | "light">("light");
    const { getByTestId } = renderWithAppState(<ThemeToggle />, {
      stateOverrides: { theme: themeSignal },
    });
    const button = getByTestId("theme-toggle");
    expect(button.getAttribute("aria-label")).toBe("Switch to dark mode");
    fireEvent.click(button);
    expect(themeSignal.value).toBe("dark");
  });
});

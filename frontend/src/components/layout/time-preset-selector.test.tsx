import { describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { TimePresetSelector } from "./time-preset-selector";
import { renderWithAppState } from "../../test/render-helpers";
import type { TimePreset } from "../../state/create-app-state";

// Mock setStoredValue so we don't touch localStorage in tests
vi.mock("../../utils/local-storage", () => ({
  setStoredValue: vi.fn(),
  getStoredValue: vi.fn(),
}));

describe("TimePresetSelector — rendering", () => {
  it("renders all 4 preset buttons", () => {
    const { getAllByRole } = renderWithAppState(<TimePresetSelector />);
    const buttons = getAllByRole("button");
    expect(buttons).toHaveLength(4);
  });

  it("renders the Since restart preset", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />);
    expect(getByText("Since restart")).toBeDefined();
  });

  it("renders the 1h preset", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />);
    expect(getByText("1h")).toBeDefined();
  });

  it("renders the 24h preset", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />);
    expect(getByText("24h")).toBeDefined();
  });

  it("renders the 7d preset", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />);
    expect(getByText("7d")).toBeDefined();
  });
});

describe("TimePresetSelector — active state", () => {
  it("marks the current preset as active", () => {
    const preset = signal<TimePreset>("1h");
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { timePreset: preset },
    });
    const btn = getByText("1h");
    expect(btn.className).toContain("is-active");
  });

  it("does not mark other presets as active", () => {
    const preset = signal<TimePreset>("1h");
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { timePreset: preset },
    });
    expect(getByText("Since restart").className).not.toContain("is-active");
    expect(getByText("24h").className).not.toContain("is-active");
    expect(getByText("7d").className).not.toContain("is-active");
  });

  it("sets aria-pressed=true on the active preset", () => {
    const preset = signal<TimePreset>("24h");
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { timePreset: preset },
    });
    expect(getByText("24h").getAttribute("aria-pressed")).toBe("true");
  });

  it("sets aria-pressed=false on inactive presets", () => {
    const preset = signal<TimePreset>("24h");
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { timePreset: preset },
    });
    expect(getByText("1h").getAttribute("aria-pressed")).toBe("false");
  });
});

describe("TimePresetSelector — interactions", () => {
  it("clicking a preset updates the signal", () => {
    const preset = signal<TimePreset>("since-restart");
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { timePreset: preset },
    });
    fireEvent.click(getByText("7d"));
    expect(preset.value).toBe("7d");
  });

  it("clicking Since restart sets since-restart value", () => {
    const preset = signal<TimePreset>("7d");
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { timePreset: preset },
    });
    fireEvent.click(getByText("Since restart"));
    expect(preset.value).toBe("since-restart");
  });
});

describe("TimePresetSelector — uptime display", () => {
  it("shows uptime when uptimeSeconds is a finite number", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: {
        uptimeSeconds: signal(3661),
      },
    });
    // 3661s = 1h 1m
    expect(getByText(/up 1h 1m/)).toBeDefined();
  });

  it("does not show uptime when uptimeSeconds is null", () => {
    const { queryByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: {
        uptimeSeconds: signal(null),
      },
    });
    expect(queryByText(/up /)).toBeNull();
  });

  it("formats seconds-only uptime correctly", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { uptimeSeconds: signal(45) },
    });
    expect(getByText("up 45s")).toBeDefined();
  });

  it("formats minutes uptime correctly", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { uptimeSeconds: signal(125) },
    });
    expect(getByText("up 2m")).toBeDefined();
  });
});

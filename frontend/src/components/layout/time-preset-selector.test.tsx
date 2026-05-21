import { signal } from "@preact/signals";
import { fireEvent } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TimePreset } from "../../state/create-app-state";
import { renderWithAppState } from "../../test/render-helpers";
import { TimePresetSelector } from "./time-preset-selector";

// Mock setStoredValue so we don't touch localStorage in tests
vi.mock("../../utils/local-storage", () => ({
  setStoredValue: vi.fn(),
  getStoredValue: vi.fn(),
}));

// Mock useQueryParams so we can control ?window= param in tests
const mockQpGet = vi.fn().mockReturnValue(null);
const mockQpSet = vi.fn();
vi.mock("../../hooks/use-query-params", () => ({
  useQueryParams: () => ({ get: mockQpGet, set: mockQpSet }),
}));

beforeEach(() => {
  mockQpGet.mockReturnValue(null);
  mockQpSet.mockClear();
});

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
  it("marks the current preset as active via aria-pressed", () => {
    const preset = signal<TimePreset>("1h");
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { timePreset: preset },
    });
    const btn = getByText("1h");
    expect(btn.getAttribute("aria-pressed")).toBe("true");
  });

  it("does not mark other presets as active", () => {
    const preset = signal<TimePreset>("1h");
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { timePreset: preset },
    });
    expect(getByText("Since restart").getAttribute("aria-pressed")).toBe("false");
    expect(getByText("24h").getAttribute("aria-pressed")).toBe("false");
    expect(getByText("7d").getAttribute("aria-pressed")).toBe("false");
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

describe("TimePresetSelector — URL sync on click", () => {
  it("clicking a preset calls qp.set with the new window value", () => {
    const preset = signal<TimePreset>("since-restart");
    renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { timePreset: preset },
    });
    fireEvent.click(document.querySelector("button[aria-pressed='false']")!);
    expect(mockQpSet).toHaveBeenCalled();
    const callArg = mockQpSet.mock.calls[0][0] as Record<string, string>;
    expect(callArg).toHaveProperty("window");
  });

  it("clicking 7d calls qp.set({ window: '7d' })", () => {
    const preset = signal<TimePreset>("since-restart");
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { timePreset: preset },
    });
    fireEvent.click(getByText("7d"));
    expect(mockQpSet).toHaveBeenCalledWith({ window: "7d" });
  });

  it("clicking a preset updates urlWindowParam signal", () => {
    const preset = signal<TimePreset>("since-restart");
    const urlWindowParam = signal<TimePreset | null>(null);
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { timePreset: preset, urlWindowParam },
    });
    fireEvent.click(getByText("24h"));
    expect(urlWindowParam.value).toBe("24h");
  });
});

describe("TimePresetSelector — URL window param on load", () => {
  it("reads ?window= on mount and writes to urlWindowParam", () => {
    mockQpGet.mockImplementation((key: string) => (key === "window" ? "24h" : null));
    const urlWindowParam = signal<TimePreset | null>(null);
    renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { urlWindowParam },
    });
    expect(urlWindowParam.value).toBe("24h");
  });

  it("does not write to timePreset when ?window= is present on load", () => {
    mockQpGet.mockImplementation((key: string) => (key === "window" ? "7d" : null));
    const preset = signal<TimePreset>("since-restart");
    renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { timePreset: preset },
    });
    // timePreset must remain unchanged — URL override is read-only
    expect(preset.value).toBe("since-restart");
  });

  it("does not modify urlWindowParam when no ?window= param", () => {
    mockQpGet.mockReturnValue(null);
    const urlWindowParam = signal<TimePreset | null>(null);
    renderWithAppState(<TimePresetSelector />, {
      stateOverrides: { urlWindowParam },
    });
    expect(urlWindowParam.value).toBeNull();
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

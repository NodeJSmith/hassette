import { fireEvent } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAppStore } from "../../state/store";
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
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { timePreset: "1h" },
    });
    const btn = getByText("1h");
    expect(btn.getAttribute("aria-pressed")).toBe("true");
  });

  it("does not mark other presets as active", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { timePreset: "1h" },
    });
    expect(getByText("Since restart").getAttribute("aria-pressed")).toBe("false");
    expect(getByText("24h").getAttribute("aria-pressed")).toBe("false");
    expect(getByText("7d").getAttribute("aria-pressed")).toBe("false");
  });

  it("sets aria-pressed=true on the active preset", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { timePreset: "24h" },
    });
    expect(getByText("24h").getAttribute("aria-pressed")).toBe("true");
  });

  it("sets aria-pressed=false on inactive presets", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { timePreset: "24h" },
    });
    expect(getByText("1h").getAttribute("aria-pressed")).toBe("false");
  });
});

describe("TimePresetSelector — interactions", () => {
  it("clicking a preset updates the store", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { timePreset: "since-restart" },
    });
    fireEvent.click(getByText("7d"));
    expect(useAppStore.getState().timePreset).toBe("7d");
  });

  it("clicking Since restart sets since-restart value", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { timePreset: "7d" },
    });
    fireEvent.click(getByText("Since restart"));
    expect(useAppStore.getState().timePreset).toBe("since-restart");
  });
});

describe("TimePresetSelector — URL sync on click", () => {
  it("clicking a preset calls qp.set with the new window value", () => {
    renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { timePreset: "since-restart" },
    });
    fireEvent.click(document.querySelector("button[aria-pressed='false']")!);
    expect(mockQpSet).toHaveBeenCalled();
    const callArg = mockQpSet.mock.calls[0][0] as Record<string, string>;
    expect(callArg).toHaveProperty("window");
  });

  it("clicking 7d calls qp.set({ window: '7d' })", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { timePreset: "since-restart" },
    });
    fireEvent.click(getByText("7d"));
    expect(mockQpSet).toHaveBeenCalledWith({ window: "7d" });
  });

  it("clicking a preset updates urlWindowParam", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { timePreset: "since-restart", urlWindowParam: null },
    });
    fireEvent.click(getByText("24h"));
    expect(useAppStore.getState().urlWindowParam).toBe("24h");
  });
});

describe("TimePresetSelector — URL window param on load", () => {
  it("reads ?window= on mount and writes to urlWindowParam", () => {
    mockQpGet.mockImplementation((key: string) => (key === "window" ? "24h" : null));
    renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { urlWindowParam: null },
    });
    expect(useAppStore.getState().urlWindowParam).toBe("24h");
  });

  it("does not write to timePreset when ?window= is present on load", () => {
    mockQpGet.mockImplementation((key: string) => (key === "window" ? "7d" : null));
    renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { timePreset: "since-restart" },
    });
    // timePreset must remain unchanged — URL override is read-only
    expect(useAppStore.getState().timePreset).toBe("since-restart");
  });

  it("does not modify urlWindowParam when no ?window= param", () => {
    mockQpGet.mockReturnValue(null);
    renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { urlWindowParam: null },
    });
    expect(useAppStore.getState().urlWindowParam).toBeNull();
  });
});

describe("TimePresetSelector — uptime display", () => {
  it("shows uptime when uptimeSeconds is a finite number", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      storeOverrides: {
        uptimeSeconds: 3661,
      },
    });
    // 3661s = 1h 1m
    expect(getByText(/up 1h 1m/)).toBeDefined();
  });

  it("does not show uptime when uptimeSeconds is null", () => {
    const { queryByText } = renderWithAppState(<TimePresetSelector />, {
      storeOverrides: {
        uptimeSeconds: null,
      },
    });
    expect(queryByText(/up /)).toBeNull();
  });

  it("formats seconds-only uptime correctly", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { uptimeSeconds: 45 },
    });
    expect(getByText("up 45s")).toBeDefined();
  });

  it("formats minutes uptime correctly", () => {
    const { getByText } = renderWithAppState(<TimePresetSelector />, {
      storeOverrides: { uptimeSeconds: 125 },
    });
    expect(getByText("up 2m")).toBeDefined();
  });
});

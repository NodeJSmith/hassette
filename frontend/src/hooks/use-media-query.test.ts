import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/preact";

describe("BREAKPOINT_MOBILE", () => {
  it("is exported as 768", async () => {
    const { BREAKPOINT_MOBILE } = await import("./use-media-query");
    expect(BREAKPOINT_MOBILE).toBe(768);
  });
});

describe("BREAKPOINT_TABLET", () => {
  it("is exported as 1024", async () => {
    const { BREAKPOINT_TABLET } = await import("./use-media-query");
    expect(BREAKPOINT_TABLET).toBe(1024);
  });
});

describe("useMediaQuery", () => {
  let listeners: Array<(e: { matches: boolean }) => void>;
  let currentMatches: boolean;
  let removeSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    listeners = [];
    currentMatches = false;
    removeSpy = vi.fn();

    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: currentMatches,
        media: query,
        addEventListener: vi.fn((_event: string, cb: (e: { matches: boolean }) => void) => {
          listeners.push(cb);
        }),
        removeEventListener: removeSpy,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns true when below breakpoint", async () => {
    currentMatches = true;
    const { useMediaQuery } = await import("./use-media-query");

    const { result } = renderHook(() => useMediaQuery(768));

    expect(result.current).toBe(true);
  });

  it("returns false when above breakpoint", async () => {
    currentMatches = false;
    const { useMediaQuery } = await import("./use-media-query");

    const { result } = renderHook(() => useMediaQuery(768));

    expect(result.current).toBe(false);
  });

  it("responds to change event", async () => {
    currentMatches = false;
    const { useMediaQuery } = await import("./use-media-query");

    const { result } = renderHook(() => useMediaQuery(768));
    expect(result.current).toBe(false);

    act(() => {
      for (const listener of listeners) {
        listener({ matches: true });
      }
    });

    expect(result.current).toBe(true);
  });

  it("cleans up listener on unmount", async () => {
    currentMatches = false;
    const { useMediaQuery } = await import("./use-media-query");

    const { unmount } = renderHook(() => useMediaQuery(768));
    unmount();

    expect(removeSpy).toHaveBeenCalledWith("change", expect.any(Function));
  });
});

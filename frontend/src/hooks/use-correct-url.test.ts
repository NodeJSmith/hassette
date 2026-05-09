import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/preact";
import { useCorrectUrl, correctionReasons } from "./use-correct-url";

const mockNavigate = vi.fn();

vi.mock("wouter", () => ({
  useLocation: () => ["/apps/foo/handlers/h-999", mockNavigate],
}));

beforeEach(() => {
  mockNavigate.mockReset();
  // Clear the module-level reasons array between tests
  correctionReasons.length = 0;
});

describe("useCorrectUrl", () => {
  it("navigates to corrected URL with replace:true", () => {
    const { result } = renderHook(() => useCorrectUrl());

    act(() => {
      result.current("/apps/foo/handlers", "handler h-999 not found");
    });

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [url, opts] = mockNavigate.mock.calls[0];
    expect(url).toBe("/apps/foo/handlers");
    expect(opts).toEqual({ replace: true });
  });

  it("records the reason string in correctionReasons", () => {
    const { result } = renderHook(() => useCorrectUrl());

    act(() => {
      result.current("/apps/foo/handlers", "handler h-999 not found");
    });

    expect(correctionReasons).toContain("handler h-999 not found");
  });

  it("accumulates multiple reasons", () => {
    const { result } = renderHook(() => useCorrectUrl());

    act(() => {
      result.current("/apps/foo/handlers", "handler h-1 not found");
      result.current("/apps/bar?instance=0", "instance 5 out of range");
    });

    expect(correctionReasons).toHaveLength(2);
    expect(correctionReasons[0]).toBe("handler h-1 not found");
    expect(correctionReasons[1]).toBe("instance 5 out of range");
  });

  it("does not navigate when correctUrl is not called", () => {
    renderHook(() => useCorrectUrl());
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});

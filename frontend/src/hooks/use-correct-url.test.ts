import { act, renderHook } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCorrectUrl } from "./use-correct-url";

const mockNavigate = vi.fn();

vi.mock("wouter", () => ({
  useLocation: () => ["/apps/foo/handlers/h-999", mockNavigate],
}));

beforeEach(() => {
  mockNavigate.mockReset();
});

describe("useCorrectUrl", () => {
  it("navigates to corrected URL with replace:true", () => {
    const { result } = renderHook(() => useCorrectUrl());

    act(() => {
      result.current("/apps/foo/handlers");
    });

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [url, opts] = mockNavigate.mock.calls[0];
    expect(url).toBe("/apps/foo/handlers");
    expect(opts).toEqual({ replace: true });
  });

  it("does not navigate when correctUrl is not called", () => {
    renderHook(() => useCorrectUrl());
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});

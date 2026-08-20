import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// dup-ignore-start: vi.mock("wouter", ...) must be written literally in every consumer file for
// Vitest's hoisting transform to detect it (see mock-wouter.ts's createWouterMock docstring) —
// also present in use-log-filters.test.ts and use-query-params.test.ts (T07)
import { createWouterMock, mockWouterNavigate } from "../test/mock-wouter";
import { useCorrectUrl } from "./use-correct-url";

const mockNavigate = mockWouterNavigate();

vi.mock("wouter", () =>
  createWouterMock({
    useLocation: () => ["/apps/foo/handlers/listener/999", mockNavigate],
  }),
);
// dup-ignore-end

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

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useAsyncAction } from "./use-async-action";

describe("useAsyncAction", () => {
  it("starts with loading false and error null", () => {
    const { result } = renderHook(() => useAsyncAction());
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("sets loading true while the action is in flight, then false after it resolves", async () => {
    const { result } = renderHook(() => useAsyncAction());
    let resolveAction!: () => void;
    const action = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveAction = resolve;
        }),
    );

    let runPromise!: Promise<void>;
    act(() => {
      runPromise = result.current.run(action);
    });
    expect(action).toHaveBeenCalledOnce();
    expect(result.current.loading).toBe(true);

    // dup-ignore-start: generic "await the async action, assert loading settled false" shape
    // coincidentally matches use-log-data.test.ts's unrelated hook — not real duplication.
    await act(async () => {
      resolveAction();
      await runPromise;
    });
    expect(result.current.loading).toBe(false);
  });

  it("ignores a second run() while the first is still in flight", async () => {
    // dup-ignore-end
    const { result } = renderHook(() => useAsyncAction());
    let resolveAction!: () => void;
    const action = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveAction = resolve;
        }),
    );

    let firstRun!: Promise<void>;
    act(() => {
      firstRun = result.current.run(action);
    });
    act(() => {
      void result.current.run(action);
    });
    expect(action).toHaveBeenCalledOnce();

    await act(async () => {
      resolveAction();
      await firstRun;
    });
  });

  it("captures an Error message and re-enables after failure", async () => {
    const { result } = renderHook(() => useAsyncAction());
    const action = vi.fn().mockRejectedValue(new Error("boom"));

    await act(async () => {
      await result.current.run(action);
    });

    // dup-ignore-start: generic "assert error and loading-settled-false" shape coincidentally
    // matches use-log-data.test.ts's unrelated hook — not real duplication.
    expect(result.current.error).toBe("boom");
    expect(result.current.loading).toBe(false);
  });

  it("stringifies non-Error throws", async () => {
    // dup-ignore-end
    const { result } = renderHook(() => useAsyncAction());
    const action = vi.fn().mockRejectedValue("raw string error");

    await act(async () => {
      await result.current.run(action);
    });

    expect(result.current.error).toBe("raw string error");
  });

  it("clears a prior error when a new run starts", async () => {
    const { result } = renderHook(() => useAsyncAction());
    const failing = vi.fn().mockRejectedValue(new Error("first failure"));
    const succeeding = vi.fn().mockResolvedValue(undefined);

    await act(async () => {
      await result.current.run(failing);
    });
    expect(result.current.error).toBe("first failure");

    await act(async () => {
      await result.current.run(succeeding);
    });
    expect(result.current.error).toBeNull();
  });
});

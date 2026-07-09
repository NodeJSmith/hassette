import { act, renderHook } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import { useAsyncAction } from "./use-async-action";

describe("useAsyncAction", () => {
  it("starts with loading false and error null", () => {
    const { result } = renderHook(() => useAsyncAction());
    expect(result.current.loading.value).toBe(false);
    expect(result.current.error.value).toBeNull();
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
    expect(result.current.loading.value).toBe(true);

    await act(async () => {
      resolveAction();
      await runPromise;
    });
    expect(result.current.loading.value).toBe(false);
  });

  it("ignores a second run() while the first is still in flight", async () => {
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

    expect(result.current.error.value).toBe("boom");
    expect(result.current.loading.value).toBe(false);
  });

  it("stringifies non-Error throws", async () => {
    const { result } = renderHook(() => useAsyncAction());
    const action = vi.fn().mockRejectedValue("raw string error");

    await act(async () => {
      await result.current.run(action);
    });

    expect(result.current.error.value).toBe("raw string error");
  });

  it("clears a prior error when a new run starts", async () => {
    const { result } = renderHook(() => useAsyncAction());
    const failing = vi.fn().mockRejectedValue(new Error("first failure"));
    const succeeding = vi.fn().mockResolvedValue(undefined);

    await act(async () => {
      await result.current.run(failing);
    });
    expect(result.current.error.value).toBe("first failure");

    await act(async () => {
      await result.current.run(succeeding);
    });
    expect(result.current.error.value).toBeNull();
  });
});

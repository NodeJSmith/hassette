import { act, renderHook } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { useRovingTabIndex } from "./use-roving-tab-index";

function keyEvent(key: string): KeyboardEvent {
  return new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
}

describe("useRovingTabIndex", () => {
  it("initially focuses the first item", () => {
    const { result } = renderHook(() => useRovingTabIndex(5));
    expect(result.current.getTabIndex(0)).toBe(0);
    expect(result.current.getTabIndex(1)).toBe(-1);
    expect(result.current.getTabIndex(4)).toBe(-1);
  });

  it("ArrowDown moves focus forward", () => {
    const { result } = renderHook(() => useRovingTabIndex(5));
    act(() => result.current.onContainerKeyDown(keyEvent("ArrowDown")));
    expect(result.current.getTabIndex(0)).toBe(-1);
    expect(result.current.getTabIndex(1)).toBe(0);
  });

  it("ArrowUp moves focus backward", () => {
    const { result } = renderHook(() => useRovingTabIndex(5));
    act(() => result.current.onContainerKeyDown(keyEvent("ArrowDown")));
    act(() => result.current.onContainerKeyDown(keyEvent("ArrowDown")));
    act(() => result.current.onContainerKeyDown(keyEvent("ArrowUp")));
    expect(result.current.getTabIndex(1)).toBe(0);
  });

  it("does not go below zero", () => {
    const { result } = renderHook(() => useRovingTabIndex(5));
    act(() => result.current.onContainerKeyDown(keyEvent("ArrowUp")));
    expect(result.current.getTabIndex(0)).toBe(0);
  });

  it("does not go above count - 1", () => {
    const { result } = renderHook(() => useRovingTabIndex(3));
    act(() => result.current.onContainerKeyDown(keyEvent("End")));
    act(() => result.current.onContainerKeyDown(keyEvent("ArrowDown")));
    expect(result.current.getTabIndex(2)).toBe(0);
  });

  it("Home jumps to first item", () => {
    const { result } = renderHook(() => useRovingTabIndex(5));
    act(() => result.current.onContainerKeyDown(keyEvent("End")));
    act(() => result.current.onContainerKeyDown(keyEvent("Home")));
    expect(result.current.getTabIndex(0)).toBe(0);
  });

  it("End jumps to last item", () => {
    const { result } = renderHook(() => useRovingTabIndex(5));
    act(() => result.current.onContainerKeyDown(keyEvent("End")));
    expect(result.current.getTabIndex(4)).toBe(0);
  });

  it("setActiveIndex updates the focused item", () => {
    const { result } = renderHook(() => useRovingTabIndex(5));
    act(() => result.current.setActiveIndex(3));
    expect(result.current.getTabIndex(3)).toBe(0);
  });

  it("clamps when count shrinks", () => {
    let count = 5;
    const { result, rerender } = renderHook(() => useRovingTabIndex(count));
    act(() => result.current.onContainerKeyDown(keyEvent("End")));
    expect(result.current.getTabIndex(4)).toBe(0);

    count = 3;
    rerender();
    expect(result.current.getTabIndex(2)).toBe(0);
  });

  it("ignores unrelated keys", () => {
    const { result } = renderHook(() => useRovingTabIndex(5));
    act(() => result.current.onContainerKeyDown(keyEvent("Tab")));
    expect(result.current.getTabIndex(0)).toBe(0);
  });

  it("does nothing when count is zero", () => {
    const { result } = renderHook(() => useRovingTabIndex(0));
    const event = keyEvent("ArrowDown");
    act(() => result.current.onContainerKeyDown(event));
    expect(event.defaultPrevented).toBe(false);
  });

  it("prevents default on handled keys", () => {
    const { result } = renderHook(() => useRovingTabIndex(5));
    const event = keyEvent("ArrowDown");
    act(() => result.current.onContainerKeyDown(event));
    expect(event.defaultPrevented).toBe(true);
  });

  it("does not prevent default on unhandled keys", () => {
    const { result } = renderHook(() => useRovingTabIndex(5));
    const event = keyEvent("Tab");
    act(() => result.current.onContainerKeyDown(event));
    expect(event.defaultPrevented).toBe(false);
  });

  describe("direction: both", () => {
    it("ArrowRight moves forward", () => {
      const { result } = renderHook(() => useRovingTabIndex(5, "both"));
      act(() => result.current.onContainerKeyDown(keyEvent("ArrowRight")));
      expect(result.current.getTabIndex(1)).toBe(0);
    });

    it("ArrowLeft moves backward", () => {
      const { result } = renderHook(() => useRovingTabIndex(5, "both"));
      act(() => result.current.onContainerKeyDown(keyEvent("ArrowRight")));
      act(() => result.current.onContainerKeyDown(keyEvent("ArrowLeft")));
      expect(result.current.getTabIndex(0)).toBe(0);
    });
  });

  describe("direction: vertical (default)", () => {
    it("ignores ArrowRight", () => {
      const { result } = renderHook(() => useRovingTabIndex(5));
      act(() => result.current.onContainerKeyDown(keyEvent("ArrowRight")));
      expect(result.current.getTabIndex(0)).toBe(0);
    });

    it("ignores ArrowLeft", () => {
      const { result } = renderHook(() => useRovingTabIndex(5));
      act(() => result.current.onContainerKeyDown(keyEvent("ArrowLeft")));
      expect(result.current.getTabIndex(0)).toBe(0);
    });
  });
});

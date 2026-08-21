import { act, renderHook } from "@testing-library/react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { describe, expect, it } from "vitest";

import { useRovingTabIndex } from "./use-roving-tab-index";

// The hook's onContainerKeyDown only reads `.key` and calls `.preventDefault()`, both of
// which exist on a native KeyboardEvent — cast to the React synthetic event type it expects.
function keyEvent(key: string): ReactKeyboardEvent {
  return new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }) as unknown as ReactKeyboardEvent;
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
    // dup-ignore-start: assert+closing-brace+next-it-declaration shape token-matches the
    // "ArrowUp moves focus backward" and "ArrowRight moves forward" test bodies elsewhere in this
    // file (PMD ignores literal key names/identifiers) despite testing a different key —
    // genuinely distinct test cases, not unresolved boilerplate.
    expect(result.current.getTabIndex(0)).toBe(-1);
    expect(result.current.getTabIndex(1)).toBe(0);
  });

  it("ArrowUp moves focus backward", () => {
    // dup-ignore-end
    const { result } = renderHook(() => useRovingTabIndex(5));
    act(() => result.current.onContainerKeyDown(keyEvent("ArrowDown")));
    act(() => result.current.onContainerKeyDown(keyEvent("ArrowDown")));
    // dup-ignore-start: act+assert+closing-brace+next-it-declaration shape token-matches the
    // "does not go below zero" and "does not go above count - 1" test bodies below (PMD ignores
    // literal key names/identifiers) despite testing a different key/scenario — genuinely
    // distinct test cases, not unresolved boilerplate.
    act(() => result.current.onContainerKeyDown(keyEvent("ArrowUp")));
    expect(result.current.getTabIndex(1)).toBe(0);
  });

  it("does not go below zero", () => {
    // dup-ignore-end
    const { result } = renderHook(() => useRovingTabIndex(5));
    // dup-ignore-start: act+assert+closing-brace+next-it-declaration shape token-matches the
    // "ArrowUp moves focus backward" test body above (PMD ignores literal key names/identifiers)
    // despite testing a different key — genuinely distinct test cases, not unresolved
    // boilerplate.
    act(() => result.current.onContainerKeyDown(keyEvent("ArrowUp")));
    expect(result.current.getTabIndex(0)).toBe(0);
  });

  it("does not go above count - 1", () => {
    // dup-ignore-end
    const { result } = renderHook(() => useRovingTabIndex(3));
    act(() => result.current.onContainerKeyDown(keyEvent("End")));
    act(() => result.current.onContainerKeyDown(keyEvent("ArrowDown")));
    expect(result.current.getTabIndex(2)).toBe(0);
  });

  it("Home jumps to first item", () => {
    const { result } = renderHook(() => useRovingTabIndex(5));
    act(() => result.current.onContainerKeyDown(keyEvent("End")));
    // dup-ignore-start: act+assert+closing-brace+next-it-declaration shape token-matches the
    // "ignores unrelated keys" test body below (PMD ignores literal key names/identifiers)
    // despite testing a different key — genuinely distinct test cases, not unresolved
    // boilerplate.
    act(() => result.current.onContainerKeyDown(keyEvent("Home")));
    expect(result.current.getTabIndex(0)).toBe(0);
  });

  it("End jumps to last item", () => {
    // dup-ignore-end
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
    // dup-ignore-start: act+assert+closing-brace+next-it-declaration shape token-matches the
    // "Home jumps to first item" test body above (PMD ignores literal key names/identifiers)
    // despite testing a different key — genuinely distinct test cases, not unresolved
    // boilerplate.
    act(() => result.current.onContainerKeyDown(keyEvent("Tab")));
    expect(result.current.getTabIndex(0)).toBe(0);
  });

  it("does nothing when count is zero", () => {
    // dup-ignore-end
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
      // dup-ignore-start: act+assert+closing-brace+next-it-declaration shape token-matches the
      // "ArrowDown moves focus forward" test body above and "ignores ArrowLeft" below (PMD
      // ignores literal key names/identifiers) despite testing a different key/direction —
      // genuinely distinct test cases, not unresolved boilerplate.
      act(() => result.current.onContainerKeyDown(keyEvent("ArrowRight")));
      expect(result.current.getTabIndex(1)).toBe(0);
    });

    it("ArrowLeft moves backward", () => {
      // dup-ignore-end
      const { result } = renderHook(() => useRovingTabIndex(5, "both"));
      act(() => result.current.onContainerKeyDown(keyEvent("ArrowRight")));
      act(() => result.current.onContainerKeyDown(keyEvent("ArrowLeft")));
      expect(result.current.getTabIndex(0)).toBe(0);
    });
  });

  describe("direction: vertical (default)", () => {
    it("ignores ArrowRight", () => {
      const { result } = renderHook(() => useRovingTabIndex(5));
      // dup-ignore-start: act+assert+closing-brace+next-it-declaration shape token-matches the
      // "ArrowRight moves forward" test body above (PMD ignores literal key names/identifiers)
      // despite testing a different key/direction — genuinely distinct test cases, not
      // unresolved boilerplate.
      act(() => result.current.onContainerKeyDown(keyEvent("ArrowRight")));
      expect(result.current.getTabIndex(0)).toBe(0);
    });

    it("ignores ArrowLeft", () => {
      // dup-ignore-end
      const { result } = renderHook(() => useRovingTabIndex(5));
      act(() => result.current.onContainerKeyDown(keyEvent("ArrowLeft")));
      expect(result.current.getTabIndex(0)).toBe(0);
    });
  });
});

import { useEffect, useRef, useState } from "preact/hooks";

// Items participating in roving tabindex must have the `data-roving-item` attribute.
const ROVING_SELECTOR = "[data-roving-item]";

type Direction = "vertical" | "both";

export function useRovingTabIndex<T extends HTMLElement = HTMLElement>(
  itemCount: number,
  direction: Direction = "vertical",
) {
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<T>(null);
  // Only move DOM focus after keyboard navigation, not on click or initial render.
  const focusViaKeyboard = useRef(false);

  const clampedIndex = itemCount > 0 ? Math.min(activeIndex, itemCount - 1) : 0;

  function onContainerKeyDown(e: KeyboardEvent) {
    if (itemCount === 0) return;

    let next: number;
    if (e.key === "ArrowDown" || (direction === "both" && e.key === "ArrowRight")) {
      next = Math.min(clampedIndex + 1, itemCount - 1);
    } else if (e.key === "ArrowUp" || (direction === "both" && e.key === "ArrowLeft")) {
      next = Math.max(clampedIndex - 1, 0);
    } else if (e.key === "Home") {
      next = 0;
    } else if (e.key === "End") {
      next = itemCount - 1;
    } else {
      return;
    }

    if (next === clampedIndex) return;
    e.preventDefault();
    focusViaKeyboard.current = true;
    setActiveIndex(next);
  }

  useEffect(() => {
    if (!focusViaKeyboard.current) return;
    focusViaKeyboard.current = false;
    const el = containerRef.current;
    if (!el) return;
    const items = el.querySelectorAll<HTMLElement>(ROVING_SELECTOR);
    items[clampedIndex]?.focus();
  }, [clampedIndex]);

  return {
    containerRef,
    onContainerKeyDown,
    getTabIndex: (i: number): 0 | -1 => (i === clampedIndex ? 0 : -1),
    setActiveIndex,
  };
}

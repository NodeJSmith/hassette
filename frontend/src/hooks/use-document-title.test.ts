import { renderHook } from "@testing-library/preact";
import { afterEach, describe, expect, it } from "vitest";

import { useDocumentTitle } from "./use-document-title";

describe("useDocumentTitle", () => {
  afterEach(() => {
    document.title = "";
  });

  it("sets document title with suffix", () => {
    renderHook(() => useDocumentTitle("Apps"));
    expect(document.title).toBe("Apps - Hassette");
  });

  it("updates when title changes", () => {
    const { rerender } = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: "Apps" },
    });
    expect(document.title).toBe("Apps - Hassette");

    rerender({ title: "My App" });
    expect(document.title).toBe("My App - Hassette");
  });

  it("resets to Hassette on unmount", () => {
    const { unmount } = renderHook(() => useDocumentTitle("Apps"));
    expect(document.title).toBe("Apps - Hassette");

    unmount();
    expect(document.title).toBe("Hassette");
  });
});

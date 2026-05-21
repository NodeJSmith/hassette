import { act, renderHook } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_COLUMNS_APP, DEFAULT_COLUMNS_EXECUTION, DEFAULT_COLUMNS_GLOBAL } from "./constants";
import type { ColumnId } from "./types";
import { useColumnVisibility } from "./use-column-visibility";

// keep in sync with log-table.test.tsx and hooks/use-media-query.ts
const mockUseMediaQuery = vi.fn((_maxWidth: number) => false);
vi.mock("../../../hooks/use-media-query", () => ({
  useMediaQuery: (maxWidth: number) => mockUseMediaQuery(maxWidth),
  BREAKPOINT_MOBILE: 768,
  BREAKPOINT_TABLET: 1024,
}));

beforeEach(() => {
  localStorage.clear();
  mockUseMediaQuery.mockReturnValue(false);
});

describe("useColumnVisibility", () => {
  describe("defaults", () => {
    it("returns global defaults for context=global", () => {
      const { result } = renderHook(() => useColumnVisibility("global"));
      expect(result.current.visibleColumns).toEqual(DEFAULT_COLUMNS_GLOBAL);
    });

    it("returns app defaults for context=app", () => {
      const { result } = renderHook(() => useColumnVisibility("app"));
      expect(result.current.visibleColumns).toEqual(DEFAULT_COLUMNS_APP);
    });

    it("returns execution defaults for context=execution", () => {
      const { result } = renderHook(() => useColumnVisibility("execution"));
      expect(result.current.visibleColumns).toEqual(DEFAULT_COLUMNS_EXECUTION);
    });
  });

  describe("toggle", () => {
    it("removes a visible column on toggle", () => {
      const { result } = renderHook(() => useColumnVisibility("global"));
      expect(result.current.visibleColumns).toContain("execution");

      act(() => result.current.toggle("execution"));
      expect(result.current.visibleColumns).not.toContain("execution");
    });

    it("adds a hidden column on toggle, maintaining column order", () => {
      const { result } = renderHook(() => useColumnVisibility("execution"));
      expect(result.current.visibleColumns).not.toContain("app");

      act(() => result.current.toggle("app"));
      const appIdx = result.current.visibleColumns.indexOf("app");
      const fnIdx = result.current.visibleColumns.indexOf("function");
      expect(appIdx).toBeGreaterThan(-1);
      expect(appIdx).toBeLessThan(fnIdx);
    });
  });

  describe("localStorage persistence", () => {
    it("persists toggled columns to localStorage", () => {
      const { result } = renderHook(() => useColumnVisibility("global"));
      act(() => result.current.toggle("module"));

      const stored = JSON.parse(localStorage.getItem("hassette-log-columns-global")!);
      expect(stored.version).toBe(1);
      expect(stored.columns).not.toContain("module");
    });

    it("reads persisted columns on mount", () => {
      const custom: ColumnId[] = ["level", "timestamp", "message"];
      localStorage.setItem("hassette-log-columns-global", JSON.stringify({ version: 1, columns: custom }));

      const { result } = renderHook(() => useColumnVisibility("global"));
      expect(result.current.visibleColumns).toEqual(custom);
    });

    it("uses separate storage keys per context", () => {
      localStorage.setItem(
        "hassette-log-columns-app",
        JSON.stringify({ version: 1, columns: ["level", "message"] as ColumnId[] }),
      );

      const { result: globalResult } = renderHook(() => useColumnVisibility("global"));
      const { result: appResult } = renderHook(() => useColumnVisibility("app"));

      expect(globalResult.current.visibleColumns).toEqual(DEFAULT_COLUMNS_GLOBAL);
      expect(appResult.current.visibleColumns).toEqual(["level", "message"]);
    });

    it("discards stored data with wrong version", () => {
      localStorage.setItem("hassette-log-columns-global", JSON.stringify({ version: 999, columns: ["level"] }));

      const { result } = renderHook(() => useColumnVisibility("global"));
      expect(result.current.visibleColumns).toEqual(DEFAULT_COLUMNS_GLOBAL);
      expect(localStorage.getItem("hassette-log-columns-global")).toBeNull();
    });

    it("discards corrupt stored data gracefully", () => {
      localStorage.setItem("hassette-log-columns-global", "not valid json{{{");

      const { result } = renderHook(() => useColumnVisibility("global"));
      expect(result.current.visibleColumns).toEqual(DEFAULT_COLUMNS_GLOBAL);
    });
  });

  describe("reset", () => {
    it("restores defaults and clears localStorage", () => {
      const { result } = renderHook(() => useColumnVisibility("global"));

      act(() => result.current.toggle("module"));
      expect(result.current.visibleColumns).not.toContain("module");
      expect(localStorage.getItem("hassette-log-columns-global")).not.toBeNull();

      act(() => result.current.reset());
      expect(result.current.visibleColumns).toEqual(DEFAULT_COLUMNS_GLOBAL);
      expect(localStorage.getItem("hassette-log-columns-global")).toBeNull();
    });
  });

  describe("viewport-responsive hiding", () => {
    it("hides mobile-excluded columns on mobile viewport", () => {
      mockUseMediaQuery.mockImplementation((maxWidth: number) => maxWidth >= 768);

      const { result } = renderHook(() => useColumnVisibility("global"));
      const hidden: ColumnId[] = ["app", "instance", "execution", "function", "module"];
      for (const col of hidden) {
        expect(result.current.visibleColumns).not.toContain(col);
      }
      expect(result.current.visibleColumns).toContain("level");
      expect(result.current.visibleColumns).toContain("timestamp");
      expect(result.current.visibleColumns).toContain("message");
    });

    it("hides tablet-excluded columns on tablet viewport", () => {
      mockUseMediaQuery.mockImplementation((maxWidth: number) => maxWidth >= 1024);

      const { result } = renderHook(() => useColumnVisibility("global"));
      expect(result.current.visibleColumns).not.toContain("module");
      expect(result.current.visibleColumns).toContain("app");
      expect(result.current.visibleColumns).toContain("function");
    });

    it("shows all user-selected columns on desktop", () => {
      mockUseMediaQuery.mockReturnValue(false);

      const { result } = renderHook(() => useColumnVisibility("global"));
      expect(result.current.visibleColumns).toEqual(DEFAULT_COLUMNS_GLOBAL);
    });
  });
});

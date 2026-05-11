import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/preact";
import { useQueryParams } from "./use-query-params";

// Mutable state for the wouter mock
let mockSearch = "";
const mockNavigate = vi.fn();

vi.mock("wouter", () => ({
  useSearch: () => mockSearch,
  useLocation: () => ["/", mockNavigate],
}));

beforeEach(() => {
  mockSearch = "";
  mockNavigate.mockReset();
});

describe("useQueryParams.get", () => {
  it("returns null when param is absent", () => {
    mockSearch = "";
    const { result } = renderHook(() => useQueryParams());
    expect(result.current.get("filter")).toBeNull();
  });

  it("returns the param value when present", () => {
    mockSearch = "filter=running";
    const { result } = renderHook(() => useQueryParams());
    expect(result.current.get("filter")).toBe("running");
  });

  it("returns null for empty string param", () => {
    mockSearch = "filter=";
    const { result } = renderHook(() => useQueryParams());
    expect(result.current.get("filter")).toBeNull();
  });

  it("decodes percent-encoded values on read", () => {
    mockSearch = "search=hello%20world";
    const { result } = renderHook(() => useQueryParams());
    expect(result.current.get("search")).toBe("hello world");
  });
});

describe("useQueryParams.set", () => {
  it("navigates with new param via replace (default push=false)", () => {
    mockSearch = "";
    const { result } = renderHook(() => useQueryParams());

    act(() => {
      result.current.set({ filter: "running" });
    });

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [url, opts] = mockNavigate.mock.calls[0];
    expect(url).toContain("filter=running");
    expect(opts).toEqual({ replace: true });
  });

  it("navigates with push: true when specified", () => {
    mockSearch = "";
    const { result } = renderHook(() => useQueryParams());

    act(() => {
      result.current.set({ tab: "logs" }, { push: true });
    });

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [, opts] = mockNavigate.mock.calls[0];
    expect(opts).toEqual({ replace: false });
  });

  it("removes param when value is null", () => {
    mockSearch = "filter=running&sort=name";
    const { result } = renderHook(() => useQueryParams());

    act(() => {
      result.current.set({ filter: null });
    });

    const [url] = mockNavigate.mock.calls[0];
    expect(url).not.toContain("filter");
    expect(url).toContain("sort=name");
  });

  it("removes param when value is empty string", () => {
    mockSearch = "search=hello";
    const { result } = renderHook(() => useQueryParams());

    act(() => {
      result.current.set({ search: "" });
    });

    const [url] = mockNavigate.mock.calls[0];
    expect(url).not.toContain("search");
  });

  it("sets multiple params at once", () => {
    mockSearch = "";
    const { result } = renderHook(() => useQueryParams());

    act(() => {
      result.current.set({ filter: "all", sort: "name", dir: "asc" });
    });

    const [url] = mockNavigate.mock.calls[0];
    expect(url).toContain("filter=all");
    expect(url).toContain("sort=name");
    expect(url).toContain("dir=asc");
  });

  it("encodes special characters on write", () => {
    mockSearch = "";
    const { result } = renderHook(() => useQueryParams());

    act(() => {
      result.current.set({ search: "hello world" });
    });

    const [url] = mockNavigate.mock.calls[0];
    expect(url).toContain("search=hello%20world");
    expect(url).not.toContain("search=hello world");
  });

  it("no-ops when new params equal current params (spurious navigation guard)", () => {
    mockSearch = "filter=running";
    const { result } = renderHook(() => useQueryParams());

    act(() => {
      result.current.set({ filter: "running" });
    });

    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("no-ops when removing absent params results in no change", () => {
    mockSearch = "";
    const { result } = renderHook(() => useQueryParams());

    act(() => {
      result.current.set({ filter: null });
    });

    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("produces clean URL with no query string when all params removed", () => {
    mockSearch = "filter=all";
    const { result } = renderHook(() => useQueryParams());

    act(() => {
      result.current.set({ filter: null });
    });

    const [url] = mockNavigate.mock.calls[0];
    expect(url).toBe("/");
  });
});

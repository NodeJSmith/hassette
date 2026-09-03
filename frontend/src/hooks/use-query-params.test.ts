import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createWouterMock } from "../test/mock-wouter";
import { renderAndSet } from "../test/query-params-test-utils";
import { useQueryParams } from "./use-query-params";

// dup-ignore-start: vi.mock("wouter", ...) must be written literally in every consumer file for
// Vitest's hoisting transform to detect it (see mock-wouter.ts's createWouterMock docstring) —
// also present in use-log-filters.test.ts and use-correct-url.test.ts (T07)
let mockSearch = "";
const mockNavigate = vi.fn();

vi.mock("wouter", () =>
  createWouterMock({
    useSearch: () => mockSearch,
    useLocation: () => ["/", mockNavigate],
  }),
);
// dup-ignore-end

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

  it("returns null for a bare key with no equals sign", () => {
    mockSearch = "filter";
    const { result } = renderHook(() => useQueryParams());
    expect(result.current.get("filter")).toBeNull();
  });

  it("parses normal params alongside empty forms", () => {
    mockSearch = "bare&empty=&filter=running";
    const { result } = renderHook(() => useQueryParams());
    expect(result.current.get("bare")).toBeNull();
    expect(result.current.get("empty")).toBeNull();
    expect(result.current.get("filter")).toBe("running");
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
    renderAndSet({ filter: "running" });

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [url, opts] = mockNavigate.mock.calls[0];
    expect(url).toContain("filter=running");
    expect(opts).toEqual({ replace: true });
  });

  it("navigates with push: true when specified", () => {
    mockSearch = "";
    renderAndSet({ tab: "logs" }, { push: true });

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [, opts] = mockNavigate.mock.calls[0];
    expect(opts).toEqual({ replace: false });
  });

  it("removes param when value is null", () => {
    mockSearch = "filter=running&sort=name";
    renderAndSet({ filter: null });

    const [url] = mockNavigate.mock.calls[0];
    expect(url).not.toContain("filter");
    expect(url).toContain("sort=name");
  });

  it("removes param when value is empty string", () => {
    mockSearch = "search=hello";
    renderAndSet({ search: "" });

    const [url] = mockNavigate.mock.calls[0];
    expect(url).not.toContain("search");
  });

  it("sets multiple params at once", () => {
    mockSearch = "";
    renderAndSet({ filter: "all", sort: "name", dir: "asc" });

    const [url] = mockNavigate.mock.calls[0];
    expect(url).toContain("filter=all");
    expect(url).toContain("sort=name");
    expect(url).toContain("dir=asc");
  });

  it("encodes special characters on write", () => {
    mockSearch = "";
    renderAndSet({ search: "hello world" });

    const [url] = mockNavigate.mock.calls[0];
    expect(url).toContain("search=hello%20world");
    expect(url).not.toContain("search=hello world");
  });

  it("no-ops when new params equal current params (spurious navigation guard)", () => {
    mockSearch = "filter=running";
    renderAndSet({ filter: "running" });

    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("no-ops when removing absent params results in no change", () => {
    mockSearch = "";
    renderAndSet({ filter: null });

    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("produces clean URL with no query string when all params removed", () => {
    mockSearch = "filter=all";
    renderAndSet({ filter: null });

    const [url] = mockNavigate.mock.calls[0];
    expect(url).toBe("/");
  });
});

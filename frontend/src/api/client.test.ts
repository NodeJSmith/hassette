import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { ApiError, apiFetch } from "./client";

describe("apiFetch", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("extracts detail from JSON error response", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: () => Promise.resolve({ detail: "Invalid app key" }),
    });

    await expect(apiFetch("/apps/bad")).rejects.toThrow(ApiError);

    try {
      await apiFetch("/apps/bad");
    } catch (err) {
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(422);
      expect(apiErr.message).toBe("Invalid app key");
    }
  });

  it("extracts message field when detail is absent", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: () => Promise.resolve({ message: "Something broke" }),
    });

    try {
      await apiFetch("/broken");
    } catch (err) {
      const apiErr = err as ApiError;
      expect(apiErr.message).toBe("Something broke");
    }
  });

  it("falls back to status text when body is not JSON", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.reject(new Error("not json")),
    });

    try {
      await apiFetch("/upstream");
    } catch (err) {
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(502);
      expect(apiErr.message).toBe("API error: 502 Bad Gateway");
    }
  });

  it("returns parsed JSON on success", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ data: "hello" }),
    });

    const result = await apiFetch<{ data: string }>("/ok");
    expect(result).toEqual({ data: "hello" });
  });
});

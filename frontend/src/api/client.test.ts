import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, postSession } from "./client";

/** Builds a mock non-ok `fetch` response whose `json()` resolves to `body`. */
function mockErrorResponse(status: number, statusText: string, body: unknown) {
  return { ok: false, status, statusText, json: () => Promise.resolve(body) };
}

/** Builds a mock non-ok `fetch` response whose `json()` rejects, as if the body were not JSON. */
function mockNonJsonErrorResponse(status: number, statusText: string) {
  return { ok: false, status, statusText, json: () => Promise.reject(new Error("not json")) };
}

/** Builds a mock ok `fetch` response whose `json()` resolves to `body`. */
function mockOkResponse(body: unknown) {
  return { ok: true, json: () => Promise.resolve(body) };
}

describe("apiFetch", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("extracts detail from JSON error response", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(mockErrorResponse(422, "Unprocessable Entity", { detail: "Invalid app key" }));

    const err = await apiFetch("/apps/bad").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(422);
    expect(apiErr.message).toBe("Invalid app key");
  });

  it("extracts message field when detail is absent", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(mockErrorResponse(500, "Internal Server Error", { message: "Something broke" }));

    const err = await apiFetch("/broken").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe("Something broke");
  });

  it("falls back to status text when body is not JSON", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(mockNonJsonErrorResponse(502, "Bad Gateway"));

    const err = await apiFetch("/upstream").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(502);
    expect(apiErr.message).toBe("API error: 502 Bad Gateway");
  });

  it("returns parsed JSON on success", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(mockOkResponse({ data: "hello" }));

    const result = await apiFetch<{ data: string }>("/ok");
    expect(result).toEqual({ data: "hello" });
  });

  it("sends credentials: same-origin", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });
    globalThis.fetch = fetchSpy;

    await apiFetch("/ok");

    expect(fetchSpy).toHaveBeenCalledWith("/api/ok", expect.objectContaining({ credentials: "same-origin" }));
  });

  it("does not navigate anywhere on a 401 — it only throws ApiError", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: () => Promise.resolve({ detail: "Not authenticated" }),
    });

    await expect(apiFetch("/protected")).rejects.toThrow(ApiError);
    await expect(apiFetch("/protected")).rejects.toMatchObject({ status: 401 });
  });
});

describe("postSession", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("posts the token as JSON to /api/auth/session with credentials", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
    globalThis.fetch = fetchSpy;

    const result = await postSession("my-token");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/auth/session",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        body: JSON.stringify({ token: "my-token" }),
      }),
    );
    expect(result).toEqual({ ok: true });
  });

  it("returns ok: false with the detail message on a rejected token, without throwing", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: () => Promise.resolve({ detail: "Invalid token" }),
    });

    const result = await postSession("wrong-token");

    expect(result).toEqual({ ok: false, message: "Invalid token" });
  });

  it("falls back to status text when the error body is not JSON", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: () => Promise.reject(new Error("not json")),
    });

    const result = await postSession("whatever");

    expect(result).toEqual({ ok: false, message: "API error: 500 Internal Server Error" });
  });

  it("returns ok: false with a network-error message when fetch itself throws, without throwing", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    const result = await postSession("whatever");

    expect(result).toEqual({ ok: false, message: "Could not reach the server. Check your connection and try again." });
  });
});

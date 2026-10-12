import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resolveAppUrl } from "../lib/base-path";
import { useAppStore } from "../state/store";
import { LOGIN_PATH } from "../utils/app-routes";
import { ApiError, apiFetch, apiPost, postSession, unauthorizedOutcome } from "./client";

/** Builds a mock non-ok `fetch` response whose `json()` resolves to `body`. */
function mockErrorResponse(status: number, statusText: string, body: unknown) {
  return { ok: false, status, statusText, json: () => Promise.resolve(body) };
}

/** Builds a mock non-ok `fetch` response whose `json()` rejects, as if the body were not JSON. */
function mockNonJsonErrorResponse(status: number, statusText: string, error: Error = new Error("not json")) {
  return { ok: false, status, statusText, json: () => Promise.reject(error) };
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

    expect(fetchSpy).toHaveBeenCalledWith(
      `${location.origin}/api/ok`,
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("does not navigate anywhere on a 401 — it only throws ApiError", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(mockErrorResponse(401, "Unauthorized", { detail: "Not authenticated" }));

    await expect(apiFetch("/protected")).rejects.toThrow(ApiError);
    await expect(apiFetch("/protected")).rejects.toMatchObject({ status: 401 });
    expect(useAppStore.getState().sessionExpired).toBe(false);
  });

  it("carries the problem body's code, which tells Hassette's own 401 from anyone else's", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        mockErrorResponse(401, "Unauthorized", { detail: "Not authenticated", code: "not_authenticated" }),
      );

    const err = await apiFetch("/protected").catch((e: unknown) => e);
    expect(err).toMatchObject({ status: 401, code: "not_authenticated" });
    expect(unauthorizedOutcome(err)).toBe("login");
  });

  it("classifies only 401s", () => {
    expect(unauthorizedOutcome(new ApiError(403, "Forbidden", undefined, "not_authenticated"))).toBeNull();
    expect(unauthorizedOutcome(new Error("network"))).toBeNull();
  });

  it("leaves code undefined for a 401 without a problem body (Supervisor's)", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(mockNonJsonErrorResponse(401, "Unauthorized"));

    const err = await apiFetch("/protected").catch((e: unknown) => e);
    expect(err).toMatchObject({ status: 401, code: undefined });
    expect(unauthorizedOutcome(err)).toBe("session-expired");
  });

  it("treats Hassette's 401 with a body a proxy truncated as session-expired, like any foreign 401", async () => {
    // The session-expired view offers Hassette's login at root base for exactly this case.
    const truncated = new SyntaxError('Unterminated string in JSON: {"detail":"Not authent');
    globalThis.fetch = vi.fn().mockResolvedValue(mockNonJsonErrorResponse(401, "Unauthorized", truncated));

    const err = await apiFetch("/protected").catch((e: unknown) => e);
    expect(unauthorizedOutcome(err)).toBe("session-expired");
  });
});

describe("401 handling", () => {
  const originalFetch = globalThis.fetch;
  const assign = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useAppStore.setState({ sessionExpired: false });
    vi.stubGlobal("location", { origin: window.location.origin, pathname: "/", assign });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.unstubAllGlobals();
  });

  function mockFetchError(status: number, statusText: string, body: unknown) {
    globalThis.fetch = vi.fn().mockResolvedValue(mockErrorResponse(status, statusText, body));
  }

  it("apiPost redirects to login on Hassette's own 401", async () => {
    mockFetchError(401, "Unauthorized", { detail: "Not authenticated", code: "not_authenticated" });

    await expect(apiPost("/apps/x/start")).rejects.toMatchObject({ status: 401, code: "not_authenticated" });

    expect(assign).toHaveBeenCalledWith(resolveAppUrl(LOGIN_PATH));
    expect(useAppStore.getState().sessionExpired).toBe(false);
  });

  it("apiPost marks the session expired on a foreign 401", async () => {
    mockFetchError(401, "Unauthorized", {});

    await expect(apiPost("/apps/x/start")).rejects.toBeInstanceOf(ApiError);

    expect(useAppStore.getState().sessionExpired).toBe(true);
    expect(assign).not.toHaveBeenCalled();
  });

  it("apiPost does nothing extra on a non-401 error", async () => {
    mockFetchError(500, "Internal Server Error", { detail: "boom" });

    await expect(apiPost("/apps/x/start")).rejects.toMatchObject({ status: 500 });

    expect(useAppStore.getState().sessionExpired).toBe(false);
    expect(assign).not.toHaveBeenCalled();
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
      `${location.origin}/api/auth/session`,
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        body: JSON.stringify({ token: "my-token" }),
      }),
    );
    expect(result).toEqual({ ok: true });
  });

  it("returns ok: false with the detail message on a rejected token, without throwing", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(mockErrorResponse(401, "Unauthorized", { detail: "Invalid token" }));

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

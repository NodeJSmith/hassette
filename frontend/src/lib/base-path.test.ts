import { afterEach, describe, expect, it, vi } from "vitest";

/** Insert a `<base href>`, then load a fresh copy of the module, which reads `document.baseURI` once at load. */
async function loadWithBase(href: string) {
  const base = document.createElement("base");
  base.href = href;
  document.head.prepend(base);
  vi.resetModules();
  return import("./base-path");
}

afterEach(() => {
  document.querySelectorAll("base").forEach((b) => b.remove());
});

describe("base-path", () => {
  it("is empty at the root", async () => {
    const { ROUTER_BASE, resolveAppUrl, resolveWsUrl } = await loadWithBase("/");
    expect(ROUTER_BASE).toBe("");
    expect(resolveAppUrl("api/apps")).toBe(`${location.origin}/api/apps`);
    expect(resolveWsUrl("api/ws")).toBe(`ws://${location.host}/api/ws`);
  });

  describe("under an ingress prefix", () => {
    const prefix = "/api/hassio_ingress/tok_123";

    it("derives the router base without the trailing slash", async () => {
      const { ROUTER_BASE } = await loadWithBase(`${prefix}/`);
      expect(ROUTER_BASE).toBe(prefix);
    });

    it("resolves REST paths under the prefix", async () => {
      const { resolveAppUrl } = await loadWithBase(`${prefix}/`);
      expect(resolveAppUrl("api/auth/session")).toBe(`${location.origin}${prefix}/api/auth/session`);
    });

    it("treats a leading slash as the app root, not the origin root", async () => {
      const { resolveAppUrl } = await loadWithBase(`${prefix}/`);
      expect(resolveAppUrl("/login")).toBe(`${location.origin}${prefix}/login`);
    });

    it("resolves the WebSocket under the prefix with a ws scheme", async () => {
      const { resolveWsUrl } = await loadWithBase(`${prefix}/`);
      expect(resolveWsUrl("api/ws")).toBe(`ws://${location.host}${prefix}/api/ws`);
    });

    it("maps https to wss", async () => {
      const { resolveWsUrl } = await loadWithBase(`https://example.test${prefix}/`);
      expect(resolveWsUrl("api/ws")).toBe(`wss://example.test${prefix}/api/ws`);
    });

    it("masks the ingress token for display", async () => {
      const { redactIngressToken, resolveWsUrl } = await loadWithBase(`${prefix}/`);
      expect(redactIngressToken(resolveWsUrl("api/ws"))).toBe(
        `ws://${location.host}/api/hassio_ingress/<token>/api/ws`,
      );
    });
  });

  it("leaves URLs without an ingress prefix unchanged when redacting", async () => {
    const { redactIngressToken, resolveWsUrl } = await loadWithBase("/");
    expect(redactIngressToken(resolveWsUrl("api/ws"))).toBe(`ws://${location.host}/api/ws`);
  });
});

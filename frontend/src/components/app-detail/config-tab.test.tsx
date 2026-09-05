import { render, screen, waitFor } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "../../test/server";
import { getShikiHighlighter } from "../../utils/shiki";
import { ConfigTab } from "./config-tab";

/** Mocked at the getShikiHighlighter boundary (not the "shiki" package) so each test controls
 *  resolution/rejection directly — the real module caches per-language, which would make a
 *  once-resolved "toml" highlighter unrejectable for a later test in this same file. */
vi.mock("../../utils/shiki", () => ({
  getShikiHighlighter: vi.fn().mockResolvedValue({
    codeToHtml: vi.fn().mockImplementation((code: string) => {
      const escaped = code.replace(/</g, "&lt;").replace(/>/g, "&gt;");
      return `<pre class="shiki"><code>${escaped}</code></pre>`;
    }),
  }),
  SHIKI_THEMES: { light: "github-light", dark: "github-dark" },
}));

const APP_KEY = "test_app";
const MASK_SENTINEL = "••••••••";
const HOST = "192.168.1.1";
const PORT = 8080;

/** Long enough to keep the request in flight while the component unmounts mid-request. */
const MOCK_RESPONSE_DELAY_MS = 100;

/** App config response with a schema that marks 'token' as a secret via anyOf. */
const defaultConfig = {
  app_key: APP_KEY,
  filename: "test_app.py",
  class_name: "TestApp",
  enabled: true,
  autostart: true,
  app_config: {
    token: MASK_SENTINEL,
    host: HOST,
    port: PORT,
  },
  config_toml: `[hassette.apps.${APP_KEY}.config]\ntoken = "${MASK_SENTINEL}"\nhost = "${HOST}"\nport = ${PORT}\n`,
  config_schema: {
    type: "object",
    properties: {
      token: {
        anyOf: [{ type: "string", writeOnly: true, format: "password" }, { type: "null" }],
        title: "Token",
      },
      host: { type: "string", title: "Host" },
      port: { type: "integer", title: "Port" },
    },
  },
  framework_fields: [],
};

/** App config response without a schema — falls back to SimpleConfigTable. */
const noSchemaConfig = {
  app_key: APP_KEY,
  filename: "test_app.py",
  class_name: "TestApp",
  enabled: true,
  autostart: true,
  app_config: {
    api_key: "some-value",
  },
  config_toml: `[hassette.apps.${APP_KEY}.config]\napi_key = "some-value"\n`,
};

function renderConfigTab() {
  return render(<ConfigTab appKey={APP_KEY} />);
}

function waitForTestId(testId: string) {
  return waitFor(() => {
    expect(screen.getByTestId(testId)).toBeDefined();
  });
}

describe("ConfigTab", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/apps/:app_key/config", () => {
        return HttpResponse.json(defaultConfig);
      }),
    );
  });

  it("shows loading state initially", () => {
    renderConfigTab();
    expect(screen.getByRole("status")).toBeDefined();
  });

  it("does not duplicate the file/class meta bar (shown above the tab bar instead)", async () => {
    renderConfigTab();
    await waitForTestId("config-tab-content");
    expect(screen.queryByTestId("config-meta")).toBeNull();
  });

  it("renders config through the shared schema renderer when schema is present", async () => {
    renderConfigTab();
    await waitForTestId("config-tab-content");
    expect(screen.getByTestId("config-schema-view")).toBeDefined();
  });

  it("masks the token field — shows the mask sentinel, not plaintext", async () => {
    renderConfigTab();
    await waitForTestId("config-schema-view");
    const tokenCell = screen.getByTestId("config-value-token");
    expect(tokenCell.textContent).toContain(MASK_SENTINEL);
  });

  it("renders non-secret values plainly — host and port are visible", async () => {
    renderConfigTab();
    await waitForTestId("config-schema-view");
    expect(screen.getByTestId("config-value-host").textContent).toContain(HOST);
    expect(screen.getByTestId("config-value-port").textContent).toContain(String(PORT));
  });

  it("renders empty config message when schema has no properties", async () => {
    server.use(
      http.get("/api/apps/:app_key/config", () => {
        return HttpResponse.json({
          ...defaultConfig,
          app_config: {},
          config_schema: { type: "object", properties: {} },
        });
      }),
    );
    renderConfigTab();
    await waitForTestId("config-tab-content");
    expect(screen.getByText(/no configuration/i)).toBeDefined();
  });

  it("falls back to SimpleConfigTable when no schema is provided", async () => {
    server.use(
      http.get("/api/apps/:app_key/config", () => {
        return HttpResponse.json(noSchemaConfig);
      }),
    );
    renderConfigTab();
    await waitForTestId("config-values-table");
    expect(screen.getByTestId("config-value-api_key").textContent).toContain("some-value");
  });

  it("shows an error card when fetching the config fails", async () => {
    server.use(http.get("/api/apps/:app_key/config", () => HttpResponse.json(null, { status: 500 })));
    renderConfigTab();
    await waitForTestId("config-tab-error");
  });

  it("falls back to a plain <pre> block when syntax highlighting fails", async () => {
    vi.mocked(getShikiHighlighter).mockRejectedValueOnce(new Error("highlight failed"));
    renderConfigTab();
    const rawBlock = await screen.findByTestId("raw-config-toml");
    expect(rawBlock.tagName).toBe("PRE");
    expect(rawBlock.innerHTML).not.toContain("shiki");
    expect(rawBlock.textContent).toContain(`host = "${HOST}"`);
  });

  it("aborts in-flight request on unmount", async () => {
    let requestSignal: AbortSignal | undefined;

    server.use(
      http.get("/api/apps/:app_key/config", async ({ request }) => {
        requestSignal = request.signal;
        await delay(MOCK_RESPONSE_DELAY_MS);
        return HttpResponse.json(defaultConfig);
      }),
    );

    const { unmount } = renderConfigTab();
    expect(screen.getByRole("status")).toBeDefined();

    await waitFor(() => expect(requestSignal).toBeDefined());
    unmount();

    expect(requestSignal!.aborted).toBe(true);
  });

  it("handles multi-instance list config by rendering per-instance blocks", async () => {
    server.use(
      http.get("/api/apps/:app_key/config", () => {
        return HttpResponse.json({
          ...defaultConfig,
          app_config: [
            { instance: 0, room: "kitchen" },
            { instance: 1, room: "bedroom" },
          ],
          config_toml: `[[hassette.apps.${APP_KEY}.config]]\ninstance = 0\nroom = "kitchen"\n\n[[hassette.apps.${APP_KEY}.config]]\ninstance = 1\nroom = "bedroom"\n`,
        });
      }),
    );
    renderConfigTab();
    await waitForTestId("config-instance-0");
    expect(screen.getByTestId("config-instance-1")).toBeDefined();
  });

  it("renders raw config as TOML with syntax highlighting", async () => {
    renderConfigTab();
    await waitForTestId("raw-config-toml");
    const rawBlock = screen.getByTestId("raw-config-toml");
    expect(rawBlock.innerHTML).toContain("shiki");
    expect(rawBlock.textContent).toContain(`hassette.apps.${APP_KEY}.config`);
    expect(rawBlock.textContent).toContain(`host = "${HOST}"`);
    expect(rawBlock.textContent).toContain(`port = ${PORT}`);
  });

  it("includes Shiki token color utilities for light and dark themes", async () => {
    renderConfigTab();
    const rawBlock = await screen.findByTestId("raw-config-toml");
    expect(rawBlock.className).toContain("[&_.shiki_span:not(.line)]:text-[var(--shiki-light,var(--ink-1))]");
    expect(rawBlock.className).toContain("dark:[&_.shiki_span:not(.line)]:text-[var(--shiki-dark,var(--ink-1))]");
  });
});

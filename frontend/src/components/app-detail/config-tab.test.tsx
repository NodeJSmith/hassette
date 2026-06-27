import { render, screen, waitFor } from "@testing-library/preact";
import { delay, http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { server } from "../../test/server";
import { ConfigTab } from "./config-tab";

const MASK_SENTINEL = "••••••••";

/** App config response with a schema that marks 'token' as a secret via anyOf. */
const defaultConfig = {
  app_key: "test_app",
  filename: "test_app.py",
  class_name: "TestApp",
  enabled: true,
  app_config: {
    token: MASK_SENTINEL,
    host: "192.168.1.1",
    port: 8080,
  },
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
};

/** App config response without a schema — falls back to SimpleConfigTable. */
const noSchemaConfig = {
  app_key: "test_app",
  filename: "test_app.py",
  class_name: "TestApp",
  enabled: true,
  app_config: {
    api_key: "some-value",
  },
};

describe("ConfigTab", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/apps/:app_key/config", () => {
        return HttpResponse.json(defaultConfig);
      }),
    );
  });

  it("shows loading state initially", () => {
    render(<ConfigTab appKey="test_app" />);
    expect(screen.getByRole("status")).toBeDefined();
  });

  it("does not duplicate the file/class meta bar (shown above the tab bar instead)", async () => {
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-tab-content")).toBeDefined();
    });
    expect(screen.queryByTestId("config-meta")).toBeNull();
  });

  it("renders config through the shared schema renderer when schema is present", async () => {
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-tab-content")).toBeDefined();
    });
    expect(screen.getByTestId("config-schema-view")).toBeDefined();
  });

  it("masks the token field — shows the mask sentinel, not plaintext", async () => {
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-schema-view")).toBeDefined();
    });
    const tokenCell = screen.getByTestId("config-value-token");
    expect(tokenCell.textContent).toContain(MASK_SENTINEL);
    expect(tokenCell.textContent).not.toContain("supersecret123");
  });

  it("renders non-secret values plainly — host and port are visible", async () => {
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-schema-view")).toBeDefined();
    });
    expect(screen.getByTestId("config-value-host").textContent).toContain("192.168.1.1");
    expect(screen.getByTestId("config-value-port").textContent).toContain("8080");
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
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-tab-content")).toBeDefined();
    });
    expect(screen.getByText(/no configuration/i)).toBeDefined();
  });

  it("falls back to SimpleConfigTable when no schema is provided", async () => {
    server.use(
      http.get("/api/apps/:app_key/config", () => {
        return HttpResponse.json(noSchemaConfig);
      }),
    );
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-values-table")).toBeDefined();
    });
    expect(screen.getByTestId("config-value-api_key").textContent).toContain("some-value");
  });

  it("aborts in-flight request on unmount", async () => {
    let requestSignal: AbortSignal | undefined;

    server.use(
      http.get("/api/apps/:app_key/config", async ({ request }) => {
        requestSignal = request.signal;
        await delay(100);
        return HttpResponse.json(defaultConfig);
      }),
    );

    const { unmount } = render(<ConfigTab appKey="test_app" />);
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
        });
      }),
    );
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-instance-0")).toBeDefined();
    });
    expect(screen.getByTestId("config-instance-1")).toBeDefined();
  });
});

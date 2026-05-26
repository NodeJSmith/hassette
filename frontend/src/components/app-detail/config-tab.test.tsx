import { render, screen, waitFor } from "@testing-library/preact";
import { delay, http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { server } from "../../test/server";
import { ConfigTab } from "./config-tab";

const defaultConfig = {
  app_key: "test_app",
  filename: "test_app.py",
  class_name: "TestApp",
  enabled: true,
  app_config: {
    token: "supersecret123",
    host: "192.168.1.1",
    port: 8080,
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

  it("renders config metadata after loading", async () => {
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-meta")).toBeDefined();
    });
    expect(screen.getByTestId("config-meta").textContent).toContain("test_app.py");
    expect(screen.getByTestId("config-meta").textContent).toContain("TestApp");
  });

  it("shows config values directly", async () => {
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-values-table")).toBeDefined();
    });
    expect(screen.getByTestId("config-value-token").textContent).toContain("supersecret123");
    expect(screen.getByTestId("config-value-host").textContent).toContain("192.168.1.1");
    expect(screen.getByTestId("config-value-port").textContent).toContain("8080");
  });

  it("renders empty config message when app_config is empty object", async () => {
    server.use(
      http.get("/api/apps/:app_key/config", () => {
        return HttpResponse.json({ ...defaultConfig, app_config: {} });
      }),
    );
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-tab-content")).toBeDefined();
    });
    expect(screen.getByText(/no configuration/i)).toBeDefined();
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

    // Wait for the request to be initiated
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

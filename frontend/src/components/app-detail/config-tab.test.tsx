import { describe, expect, it, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
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

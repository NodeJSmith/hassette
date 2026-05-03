import { describe, expect, it, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/preact";
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
    expect(screen.getByTestId("config-tab-loading")).toBeDefined();
  });

  it("renders config metadata after loading", async () => {
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-meta")).toBeDefined();
    });
    expect(screen.getByTestId("config-meta").textContent).toContain("test_app.py");
    expect(screen.getByTestId("config-meta").textContent).toContain("TestApp");
  });

  it("values are redacted by default", async () => {
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-values-table")).toBeDefined();
    });
    // All values should be masked
    const cells = screen.getAllByTestId(/^config-value-/);
    for (const cell of cells) {
      expect(cell.textContent).toContain("••••••");
    }
    // Original values must NOT appear
    expect(screen.queryByText("supersecret123")).toBeNull();
    expect(screen.queryByText("192.168.1.1")).toBeNull();
  });

  it("reveals a value when its Reveal button is clicked", async () => {
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-values-table")).toBeDefined();
    });

    // Click reveal for the 'token' key
    const revealBtn = screen.getByTestId("reveal-btn-token");
    fireEvent.click(revealBtn);

    // Token value now visible
    expect(screen.getByTestId("config-value-token").textContent).not.toContain("••••••");
    expect(screen.getByTestId("config-value-token").textContent).toContain("supersecret123");

    // Other values still redacted
    expect(screen.getByTestId("config-value-host").textContent).toContain("••••••");
  });

  it("hides value again when Redact button is clicked", async () => {
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-values-table")).toBeDefined();
    });

    // Reveal then redact
    fireEvent.click(screen.getByTestId("reveal-btn-token"));
    expect(screen.getByTestId("config-value-token").textContent).toContain("supersecret123");

    fireEvent.click(screen.getByTestId("reveal-btn-token"));
    expect(screen.getByTestId("config-value-token").textContent).toContain("••••••");
  });

  it("renders empty config message when app_config is empty object", async () => {
    server.use(
      http.get("/api/apps/:app_key/config", () => {
        return HttpResponse.json({ ...defaultConfig, app_config: {} });
      }),
    );
    render(<ConfigTab appKey="test_app" />);
    await waitFor(() => {
      expect(screen.getByTestId("config-empty")).toBeDefined();
    });
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

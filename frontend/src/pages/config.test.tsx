import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { createSystemConfig } from "../test/factories";
import { renderWithAppState } from "../test/render-helpers";
import { server } from "../test/server";
import { ConfigPage } from "./config";

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

describe("ConfigPage", () => {
  it("renders 'config' heading", async () => {
    const { findByRole } = renderWithAppState(<ConfigPage />);
    expect(await findByRole("heading", { name: /config/i })).toBeDefined();
  });

  it("renders a table of config key-value pairs", async () => {
    const { findByText, container } = renderWithAppState(<ConfigPage />);
    // Wait for a config section label to confirm data loaded
    await findByText("general");
    expect(container.querySelector("table")).not.toBeNull();
  });

  it("shows loading state while fetching", () => {
    // Override to never resolve so the spinner stays visible synchronously
    server.use(http.get("/api/config", () => new Promise(() => {})));
    const { container } = renderWithAppState(<ConfigPage />);
    expect(container.querySelector("[data-testid='spinner']")).not.toBeNull();
  });

  it("shows error state on fetch failure", async () => {
    server.use(http.get("/api/config", () => HttpResponse.json(null, { status: 500 })));
    const { findByRole } = renderWithAppState(<ConfigPage />);
    const alert = await findByRole("alert");
    expect(alert.textContent).toBeTruthy();
  });

  it("renders path fields in a Paths group", async () => {
    server.use(
      http.get("/api/config", () =>
        HttpResponse.json(
          createSystemConfig({
            apps: { autodetect: true, directory: "/my/apps" },
            data_dir: "/my/data",
            config_dir: "/my/config",
          }),
        ),
      ),
    );
    const { findByText } = renderWithAppState(<ConfigPage />);
    expect(await findByText("paths")).toBeDefined();
    expect(await findByText("app_dir")).toBeDefined();
    expect(await findByText("data_dir")).toBeDefined();
    expect(await findByText("config_dir")).toBeDefined();
    expect(await findByText("/my/apps")).toBeDefined();
    expect(await findByText("/my/data")).toBeDefined();
    expect(await findByText("/my/config")).toBeDefined();
  });

  it("renders connection settings group", async () => {
    const { findByText } = renderWithAppState(<ConfigPage />);
    expect(await findByText("connection")).toBeDefined();
    expect(await findByText("host")).toBeDefined();
    expect(await findByText("port")).toBeDefined();
  });

  it("renders general settings group", async () => {
    const { findByText } = renderWithAppState(<ConfigPage />);
    expect(await findByText("general")).toBeDefined();
    expect(await findByText("log_level")).toBeDefined();
    expect(await findByText("dev_mode")).toBeDefined();
  });

  it("renders timeouts group", async () => {
    const { findByText } = renderWithAppState(<ConfigPage />);
    expect(await findByText("timeouts")).toBeDefined();
    expect(await findByText("startup_timeout_seconds")).toBeDefined();
  });

  it("displays numeric config values as text", async () => {
    server.use(
      http.get("/api/config", () =>
        HttpResponse.json(
          createSystemConfig({
            web_api: {
              run: true,
              run_ui: true,
              ui_hot_reload: false,
              host: "0.0.0.0",
              port: 9000,
              cors_origins: [],
              event_buffer_size: 500,
              log_buffer_size: 2000,
              job_history_size: 1000,
            },
          }),
        ),
      ),
    );
    const { findByText } = renderWithAppState(<ConfigPage />);
    expect(await findByText("9000")).toBeDefined();
  });

  it("displays boolean config values as text", async () => {
    server.use(
      http.get("/api/config", () =>
        HttpResponse.json(createSystemConfig({ dev_mode: true, asyncio_debug_mode: false })),
      ),
    );
    const { findByText, container } = renderWithAppState(<ConfigPage />);
    // Wait for a config section label to confirm data loaded
    await findByText("general");
    const rows = Array.from(container.querySelectorAll("tr"));
    const devModeRow = rows.find((r) => r.textContent?.includes("dev_mode"));
    expect(devModeRow).toBeDefined();
    expect(devModeRow!.textContent).toContain("true");
  });
});

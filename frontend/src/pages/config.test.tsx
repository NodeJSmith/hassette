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

  it("shows loading state while fetching", () => {
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

  it("renders the schema-driven view after loading", async () => {
    const { findByTestId } = renderWithAppState(<ConfigPage />);
    expect(await findByTestId("config-schema-view")).toBeDefined();
  });

  it("renders a 'general' section for flat top-level fields", async () => {
    const { findByTestId } = renderWithAppState(<ConfigPage />);
    expect(await findByTestId("config-section-general")).toBeDefined();
  });

  it("renders the web_api group using its ui.group_label", async () => {
    const { findByTestId } = renderWithAppState(<ConfigPage />);
    expect(await findByTestId("config-section-web-api")).toBeDefined();
  });

  it("renders all expected group sections", async () => {
    const { findByTestId } = renderWithAppState(<ConfigPage />);
    await findByTestId("config-schema-view");
    for (const section of ["general", "web-api", "logging", "lifecycle", "apps", "scheduler", "file-watcher"]) {
      expect(await findByTestId(`config-section-${section}`)).toBeDefined();
    }
  });

  it("applies ui.label override — 'Base URL' instead of 'Base Url'", async () => {
    const { findByText } = renderWithAppState(<ConfigPage />);
    expect(await findByText("Base URL")).toBeDefined();
  });

  it("applies ui.group_label override — section heading reads 'Web API' not 'Web Api'", async () => {
    const { findByRole } = renderWithAppState(<ConfigPage />);
    // The web_api group heading should use ui.group_label "Web API" (not humanized "Web Api").
    // Use heading role to disambiguate from field labels that also read "Web API" (logging.web_api).
    expect(await findByRole("heading", { name: "Web API" })).toBeDefined();
  });

  it("shows humanized label for un-annotated field — 'Dev Mode'", async () => {
    const { findByText } = renderWithAppState(<ConfigPage />);
    expect(await findByText("Dev Mode")).toBeDefined();
  });

  it("renders a boolean value as a true/false badge", async () => {
    server.use(http.get("/api/config", () => HttpResponse.json(createSystemConfig({ dev_mode: true }))));
    const { findByTestId } = renderWithAppState(<ConfigPage />);
    const cell = await findByTestId("config-value-dev_mode");
    expect(cell.textContent).toContain("true");
  });

  it("renders a path value as code-styled text", async () => {
    server.use(http.get("/api/config", () => HttpResponse.json(createSystemConfig({ data_dir: "/my/data" }))));
    const { findByText } = renderWithAppState(<ConfigPage />);
    expect(await findByText("/my/data")).toBeDefined();
  });

  it("renders a nested group field value", async () => {
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
    const { findByTestId } = renderWithAppState(<ConfigPage />);
    const portCell = await findByTestId("config-value-port");
    expect(portCell.textContent).toContain("9000");
  });

  it("masks a secret field — shows mask sentinel, not plaintext", async () => {
    server.use(http.get("/api/config", () => HttpResponse.json(createSystemConfig({ token: "••••••••" }))));
    const { findByTestId } = renderWithAppState(<ConfigPage />);
    const cell = await findByTestId("config-value-token");
    // Shows the mask placeholder, not a real token value.
    expect(cell.textContent).toContain("••••••••");
    // Plaintext should not appear.
    expect(cell.textContent).not.toContain("realtoken");
  });

  it("shows 'not set' for an unset secret field", async () => {
    server.use(http.get("/api/config", () => HttpResponse.json(createSystemConfig({ token: null }))));
    const { findByTestId } = renderWithAppState(<ConfigPage />);
    const cell = await findByTestId("config-value-token");
    expect(cell.textContent).toContain("not set");
  });

  it("renders directory field under the apps group", async () => {
    server.use(
      http.get("/api/config", () =>
        HttpResponse.json(createSystemConfig({ apps: { autodetect: true, directory: "/my/apps" } })),
      ),
    );
    const { findByTestId } = renderWithAppState(<ConfigPage />);
    const dirCell = await findByTestId("config-value-directory");
    expect(dirCell.textContent).toContain("/my/apps");
  });

  it("renders startup_timeout_seconds under lifecycle group", async () => {
    const { findByTestId } = renderWithAppState(<ConfigPage />);
    await findByTestId("config-section-lifecycle");
    const cell = await findByTestId("config-value-startup_timeout_seconds");
    expect(cell.textContent).toContain("30");
  });
});

import { describe, expect, it, vi, beforeEach } from "vitest";
import { signal } from "@preact/signals";
import { ConfigPage } from "./config";
import { renderWithAppState } from "../test/render-helpers";
import { createSystemConfig } from "../test/factories";

vi.mock("../hooks/use-api", () => ({
  useApi: vi.fn(),
}));

const useApiMod = await import("../hooks/use-api");
const useApi = useApiMod.useApi as unknown as ReturnType<typeof vi.fn>;

function fakeApiResult<T>(data: T | null, loading = false, error: string | null = null) {
  return {
    data: signal(data),
    loading: signal(loading),
    error: signal(error),
    refetch: vi.fn(),
  };
}

describe("ConfigPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders 'config' heading", () => {
    useApi.mockReturnValue(fakeApiResult(createSystemConfig()));
    const { getByRole } = renderWithAppState(<ConfigPage />);
    expect(getByRole("heading", { name: /config/i })).toBeDefined();
  });

  it("renders a table of config key-value pairs", () => {
    useApi.mockReturnValue(fakeApiResult(createSystemConfig()));
    const { container } = renderWithAppState(<ConfigPage />);
    expect(container.querySelector("table")).not.toBeNull();
  });

  it("shows loading state while fetching", () => {
    useApi.mockReturnValue(fakeApiResult(null, true));
    const { container } = renderWithAppState(<ConfigPage />);
    expect(container.querySelector("[data-testid='spinner']")).not.toBeNull();
  });

  it("shows error state on fetch failure", () => {
    useApi.mockReturnValue(fakeApiResult(null, false, "Network error"));
    const { getByText } = renderWithAppState(<ConfigPage />);
    expect(getByText(/network error/i)).toBeDefined();
  });

  it("renders path fields in a Paths group", () => {
    useApi.mockReturnValue(fakeApiResult(createSystemConfig({
      app: { autodetect: true, directory: "/my/apps" },
      data_dir: "/my/data",
      config_dir: "/my/config",
    })));
    const { getByText } = renderWithAppState(<ConfigPage />);
    expect(getByText("paths")).toBeDefined();
    expect(getByText("app_dir")).toBeDefined();
    expect(getByText("data_dir")).toBeDefined();
    expect(getByText("config_dir")).toBeDefined();
    expect(getByText("/my/apps")).toBeDefined();
    expect(getByText("/my/data")).toBeDefined();
    expect(getByText("/my/config")).toBeDefined();
  });

  it("renders connection settings group", () => {
    useApi.mockReturnValue(fakeApiResult(createSystemConfig()));
    const { getByText } = renderWithAppState(<ConfigPage />);
    expect(getByText("connection")).toBeDefined();
    expect(getByText("host")).toBeDefined();
    expect(getByText("port")).toBeDefined();
  });

  it("renders general settings group", () => {
    useApi.mockReturnValue(fakeApiResult(createSystemConfig()));
    const { getByText } = renderWithAppState(<ConfigPage />);
    expect(getByText("general")).toBeDefined();
    expect(getByText("log_level")).toBeDefined();
    expect(getByText("dev_mode")).toBeDefined();
  });

  it("renders timeouts group", () => {
    useApi.mockReturnValue(fakeApiResult(createSystemConfig()));
    const { getByText } = renderWithAppState(<ConfigPage />);
    expect(getByText("timeouts")).toBeDefined();
    expect(getByText("startup_timeout_seconds")).toBeDefined();
  });

  it("displays numeric config values as text", () => {
    useApi.mockReturnValue(fakeApiResult(createSystemConfig({
      web_api: {
        run: true, run_ui: true, ui_hot_reload: false,
        host: "0.0.0.0", port: 9000, cors_origins: [],
        event_buffer_size: 500, log_buffer_size: 2000, job_history_size: 1000,
      },
    })));
    const { getByText } = renderWithAppState(<ConfigPage />);
    expect(getByText("9000")).toBeDefined();
  });

  it("displays boolean config values as text", () => {
    useApi.mockReturnValue(fakeApiResult(createSystemConfig({ dev_mode: true, asyncio_debug_mode: false })));
    const { container } = renderWithAppState(<ConfigPage />);
    // Find the dev_mode row and verify its value cell shows "true"
    const rows = Array.from(container.querySelectorAll("tr"));
    const devModeRow = rows.find((r) => r.textContent?.includes("dev_mode"));
    expect(devModeRow).toBeDefined();
    expect(devModeRow!.textContent).toContain("true");
  });
});

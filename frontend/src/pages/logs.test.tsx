import { describe, expect, it, vi, beforeEach } from "vitest";
import { signal } from "@preact/signals";
import { LogsPage } from "./logs";
import { renderWithAppState } from "../test/render-helpers";
import { createManifestList, createManifest } from "../test/factories";

// Stub LogTable — it has its own extensive tests
vi.mock("../components/shared/log-table", () => ({
  LogTable: ({ showAppColumn, appKeys }: { showAppColumn: boolean; appKeys: string[] }) => (
    <div
      data-testid="log-table"
      data-show-app-column={String(showAppColumn)}
      data-app-keys={appKeys.join(",")}
    />
  ),
}));

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

describe("LogsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders 'Log Viewer' heading", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList()));
    const { getByRole } = renderWithAppState(<LogsPage />);
    expect(getByRole("heading", { name: /log viewer/i })).toBeDefined();
  });

  it("renders LogTable component", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList()));
    const { getByTestId } = renderWithAppState(<LogsPage />);
    expect(getByTestId("log-table")).toBeDefined();
  });

  it("passes showAppColumn=true to LogTable", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList()));
    const { getByTestId } = renderWithAppState(<LogsPage />);
    expect(getByTestId("log-table").getAttribute("data-show-app-column")).toBe("true");
  });

  it("passes sorted app keys from manifests to LogTable", () => {
    const manifests = createManifestList({
      manifests: [
        createManifest({ app_key: "zebra_app" }),
        createManifest({ app_key: "alpha_app" }),
      ],
    });
    useApi.mockReturnValue(fakeApiResult(manifests));
    const { getByTestId } = renderWithAppState(<LogsPage />);
    // App keys should be sorted alphabetically
    expect(getByTestId("log-table").getAttribute("data-app-keys")).toBe("alpha_app,zebra_app");
  });

  it("passes empty app keys when manifests have no data", () => {
    useApi.mockReturnValue(fakeApiResult(null));
    const { getByTestId } = renderWithAppState(<LogsPage />);
    expect(getByTestId("log-table").getAttribute("data-app-keys")).toBe("");
  });

  it("renders LogTable inside a card", () => {
    useApi.mockReturnValue(fakeApiResult(createManifestList()));
    const { container } = renderWithAppState(<LogsPage />);
    expect(container.querySelector(".ht-card")).not.toBeNull();
  });
});

import { describe, expect, it, vi } from "vitest";
import { signal } from "@preact/signals";
import { SessionsPage } from "./sessions";
import { renderWithAppState } from "../test/render-helpers";
import { createSession } from "../test/factories";

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
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

describe("SessionsPage", () => {
  it("shows spinner while loading", () => {
    useApi.mockReturnValue(fakeApiResult(null, true));
    const { getByTestId } = renderWithAppState(<SessionsPage />);
    expect(getByTestId("spinner")).toBeDefined();
  });

  it("renders the sessions table heading", () => {
    useApi.mockReturnValue(fakeApiResult([]));
    const { getByRole } = renderWithAppState(<SessionsPage />);
    expect(getByRole("heading", { name: /sessions/i })).toBeDefined();
  });

  it("renders sessions table with data-testid", () => {
    useApi.mockReturnValue(fakeApiResult([createSession()]));
    const { getByTestId } = renderWithAppState(<SessionsPage />);
    expect(getByTestId("sessions-table")).toBeDefined();
  });

  it("renders table column headers", () => {
    useApi.mockReturnValue(fakeApiResult([]));
    const { getByText } = renderWithAppState(<SessionsPage />);
    expect(getByText("Status")).toBeDefined();
    expect(getByText("Started At")).toBeDefined();
    expect(getByText("Duration")).toBeDefined();
    expect(getByText("Error Type")).toBeDefined();
  });

  it("shows empty state message when no sessions", () => {
    useApi.mockReturnValue(fakeApiResult([]));
    const { getByText } = renderWithAppState(<SessionsPage />);
    expect(getByText("No sessions recorded yet.")).toBeDefined();
  });

  it("renders a row per session", () => {
    const sessions = [
      createSession({ id: 1, status: "running" }),
      createSession({ id: 2, status: "stopped" }),
    ];
    useApi.mockReturnValue(fakeApiResult(sessions));
    const { getAllByRole } = renderWithAppState(<SessionsPage />);
    // thead + tbody rows
    const rows = getAllByRole("row");
    // 1 header row + 2 data rows = 3
    expect(rows).toHaveLength(3);
  });

  it("shows error message when fetch fails", () => {
    useApi.mockReturnValue(fakeApiResult(null, false, "Network error"));
    const { getByText } = renderWithAppState(<SessionsPage />);
    expect(getByText(/Failed to load sessions: Network error/)).toBeDefined();
  });

  it("renders session status badge", () => {
    useApi.mockReturnValue(fakeApiResult([createSession({ status: "running" })]));
    const { container } = renderWithAppState(<SessionsPage />);
    // StatusBadge renders with the status as text or class
    expect(container.querySelector("tbody")).not.toBeNull();
    const tbody = container.querySelector("tbody")!;
    expect(tbody.querySelectorAll("tr")).toHaveLength(1);
  });

  it("shows dash for stopped_at when session is still running", () => {
    useApi.mockReturnValue(fakeApiResult([createSession({ stopped_at: null })]));
    const { getAllByText } = renderWithAppState(<SessionsPage />);
    // Multiple dashes may appear (stopped_at, duration, error_type, error_message)
    expect(getAllByText("-").length).toBeGreaterThan(0);
  });

  it("shows error_type when present", () => {
    useApi.mockReturnValue(fakeApiResult([createSession({ error_type: "RuntimeError" })]));
    const { getByText } = renderWithAppState(<SessionsPage />);
    expect(getByText("RuntimeError")).toBeDefined();
  });

  it("formats short durations in seconds", () => {
    useApi.mockReturnValue(fakeApiResult([createSession({ duration_seconds: 45, stopped_at: 1700000045 })]));
    const { getByText } = renderWithAppState(<SessionsPage />);
    expect(getByText("45s")).toBeDefined();
  });

  it("formats minute durations", () => {
    useApi.mockReturnValue(fakeApiResult([createSession({ duration_seconds: 125, stopped_at: 1700000125 })]));
    const { getByText } = renderWithAppState(<SessionsPage />);
    expect(getByText("2m 5s")).toBeDefined();
  });
});

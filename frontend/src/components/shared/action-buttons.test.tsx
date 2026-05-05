import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/preact";
import { ActionButtons } from "./action-buttons";

// Mock the API endpoints — we test the component logic, not the network.
vi.mock("../../api/endpoints", () => ({
  startApp: vi.fn(),
  stopApp: vi.fn(),
  reloadApp: vi.fn(),
}));

const endpoints = await import("../../api/endpoints");
const startApp = endpoints.startApp as unknown as ReturnType<typeof vi.fn>;
const stopApp = endpoints.stopApp as unknown as ReturnType<typeof vi.fn>;
const reloadApp = endpoints.reloadApp as unknown as ReturnType<typeof vi.fn>;

describe("ActionButtons", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // -- Button visibility by status --

  it("shows Start when status is stopped", () => {
    const { getByTestId, queryByTestId } = render(
      <ActionButtons appKey="my_app" status="stopped" />,
    );
    expect(getByTestId("btn-start-my_app")).toBeDefined();
    expect(queryByTestId("btn-stop-my_app")).toBeNull();
    expect(queryByTestId("btn-reload-my_app")).toBeNull();
  });

  it("shows Start when status is failed", () => {
    const { getByTestId, queryByTestId } = render(
      <ActionButtons appKey="my_app" status="failed" />,
    );
    expect(getByTestId("btn-start-my_app")).toBeDefined();
    expect(queryByTestId("btn-stop-my_app")).toBeNull();
  });

  it("shows Start when status is disabled", () => {
    const { getByTestId } = render(
      <ActionButtons appKey="my_app" status="disabled" />,
    );
    expect(getByTestId("btn-start-my_app")).toBeDefined();
  });

  it("shows Stop and Reload when status is running", () => {
    const { getByTestId, queryByTestId } = render(
      <ActionButtons appKey="my_app" status="running" />,
    );
    expect(queryByTestId("btn-start-my_app")).toBeNull();
    expect(getByTestId("btn-stop-my_app")).toBeDefined();
    expect(getByTestId("btn-reload-my_app")).toBeDefined();
  });

  it("shows no buttons for unknown statuses like starting", () => {
    const { queryByTestId } = render(
      <ActionButtons appKey="my_app" status="starting" />,
    );
    expect(queryByTestId("btn-start-my_app")).toBeNull();
    expect(queryByTestId("btn-stop-my_app")).toBeNull();
    expect(queryByTestId("btn-reload-my_app")).toBeNull();
  });

  // -- Action execution --

  it("calls startApp and disables button during loading", async () => {
    startApp.mockResolvedValue({ status: "accepted" });

    const { getByTestId } = render(
      <ActionButtons appKey="my_app" status="stopped" />,
    );

    const btn = getByTestId("btn-start-my_app") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);

    fireEvent.click(btn);
    expect(startApp).toHaveBeenCalledWith("my_app");

    // Button is disabled while loading
    expect(btn.disabled).toBe(true);

    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    });
  });

  it("calls stopApp when Stop is clicked", async () => {
    stopApp.mockResolvedValue({ status: "accepted" });

    const { getByTestId } = render(
      <ActionButtons appKey="my_app" status="running" />,
    );

    fireEvent.click(getByTestId("btn-stop-my_app"));
    expect(stopApp).toHaveBeenCalledWith("my_app");

    await waitFor(() => {
      expect((getByTestId("btn-stop-my_app") as HTMLButtonElement).disabled).toBe(false);
    });
  });

  it("calls reloadApp when Reload is clicked", async () => {
    reloadApp.mockResolvedValue({ status: "accepted" });

    const { getByTestId } = render(
      <ActionButtons appKey="my_app" status="running" />,
    );

    fireEvent.click(getByTestId("btn-reload-my_app"));
    expect(reloadApp).toHaveBeenCalledWith("my_app");

    await waitFor(() => {
      expect((getByTestId("btn-reload-my_app") as HTMLButtonElement).disabled).toBe(false);
    });
  });

  // -- Error handling --

  it("shows error message when action fails and re-enables button", async () => {
    startApp.mockRejectedValue(new Error("Connection refused"));

    const { getByTestId, getByText } = render(
      <ActionButtons appKey="my_app" status="stopped" />,
    );

    const btn = getByTestId("btn-start-my_app") as HTMLButtonElement;
    fireEvent.click(btn);

    await waitFor(() => {
      expect(getByText("Connection refused")).toBeDefined();
    });

    // Button must re-enable after error (finally block)
    expect(btn.disabled).toBe(false);
  });

  it("shows stringified error for non-Error throws", async () => {
    startApp.mockRejectedValue("raw string error");

    const { getByTestId, getByText } = render(
      <ActionButtons appKey="my_app" status="stopped" />,
    );

    const btn = getByTestId("btn-start-my_app") as HTMLButtonElement;
    fireEvent.click(btn);

    await waitFor(() => {
      expect(getByText("raw string error")).toBeDefined();
    });

    expect(btn.disabled).toBe(false);
  });

  it("ignores second click while first action is in-flight", async () => {
    let resolveAction!: (value: unknown) => void;
    startApp.mockImplementation(
      () => new Promise((resolve) => { resolveAction = resolve; }),
    );

    const { getByTestId } = render(
      <ActionButtons appKey="my_app" status="stopped" />,
    );

    const btn = getByTestId("btn-start-my_app") as HTMLButtonElement;

    // First click — starts the action
    fireEvent.click(btn);
    expect(startApp).toHaveBeenCalledTimes(1);

    // Second click while first is still in-flight — should be ignored
    fireEvent.click(btn);
    expect(startApp).toHaveBeenCalledTimes(1);

    // Resolve the pending action to clean up
    resolveAction({ status: "accepted" });
    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    });
  });

  it("clears error when status changes", async () => {
    startApp.mockRejectedValue(new Error("fail"));

    const { getByTestId, getByText, queryByText, rerender } = render(
      <ActionButtons appKey="my_app" status="stopped" />,
    );

    fireEvent.click(getByTestId("btn-start-my_app"));

    await waitFor(() => {
      expect(getByText("fail")).toBeDefined();
    });

    // Status changes (e.g., WS event arrives) — error should clear
    rerender(<ActionButtons appKey="my_app" status="running" />);

    expect(queryByText("fail")).toBeNull();
  });
});

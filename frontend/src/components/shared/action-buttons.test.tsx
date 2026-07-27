import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ActionResponse } from "../../api/endpoints";
import { ActionButtons } from "./action-buttons";

// Mock the API endpoints — we test the component logic, not the network.
vi.mock("../../api/endpoints", () => ({
  startApp: vi.fn(),
  stopApp: vi.fn(),
  reloadApp: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const endpoints = await import("../../api/endpoints");
const startApp = vi.mocked(endpoints.startApp);
const stopApp = vi.mocked(endpoints.stopApp);
const reloadApp = vi.mocked(endpoints.reloadApp);

// Import after mock so the spy reference is captured.
const { toast } = await import("sonner");

describe("ActionButtons", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // -- Button visibility by status --

  it("shows Start when status is stopped", () => {
    const { getByTestId, queryByTestId } = render(<ActionButtons appKey="my_app" status="stopped" />);
    expect(getByTestId("btn-start-my_app")).toBeDefined();
    expect(queryByTestId("btn-stop-my_app")).toBeNull();
    expect(queryByTestId("btn-reload-my_app")).toBeNull();
  });

  it("shows Start when status is failed", () => {
    const { getByTestId, queryByTestId } = render(<ActionButtons appKey="my_app" status="failed" />);
    expect(getByTestId("btn-start-my_app")).toBeDefined();
    expect(queryByTestId("btn-stop-my_app")).toBeNull();
  });

  it("shows Start when status is disabled", () => {
    const { getByTestId } = render(<ActionButtons appKey="my_app" status="disabled" />);
    expect(getByTestId("btn-start-my_app")).toBeDefined();
  });

  it("shows Stop and Reload when status is running", () => {
    const { getByTestId, queryByTestId } = render(<ActionButtons appKey="my_app" status="running" />);
    expect(queryByTestId("btn-start-my_app")).toBeNull();
    expect(getByTestId("btn-stop-my_app")).toBeDefined();
    expect(getByTestId("btn-reload-my_app")).toBeDefined();
  });

  it("shows no buttons for unknown statuses like starting", () => {
    const { queryByTestId } = render(<ActionButtons appKey="my_app" status="starting" />);
    expect(queryByTestId("btn-start-my_app")).toBeNull();
    expect(queryByTestId("btn-stop-my_app")).toBeNull();
    expect(queryByTestId("btn-reload-my_app")).toBeNull();
  });

  // -- Action execution --

  it("calls startApp and disables button during loading", async () => {
    startApp.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "start" });

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="stopped" />);

    const btn = getByTestId("btn-start-my_app") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);

    fireEvent.click(btn);
    expect(startApp).toHaveBeenCalledWith("my_app");

    // Button is disabled while loading
    expect(btn.disabled).toBe(true);

    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    });

    expect(toast.success).toHaveBeenCalledWith('App "my_app" started');
  });

  it("calls stopApp when Stop is clicked", async () => {
    stopApp.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "stop" });

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="running" />);

    fireEvent.click(getByTestId("btn-stop-my_app"));
    expect(stopApp).toHaveBeenCalledWith("my_app");

    await waitFor(() => {
      expect((getByTestId("btn-stop-my_app") as HTMLButtonElement).disabled).toBe(false);
    });

    expect(toast.success).toHaveBeenCalledWith('App "my_app" stopped');
  });

  it("calls reloadApp when Reload is clicked", async () => {
    reloadApp.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "reload" });

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="running" />);

    fireEvent.click(getByTestId("btn-reload-my_app"));
    expect(reloadApp).toHaveBeenCalledWith("my_app");

    await waitFor(() => {
      expect((getByTestId("btn-reload-my_app") as HTMLButtonElement).disabled).toBe(false);
    });

    expect(toast.success).toHaveBeenCalledWith('App "my_app" reloaded');
  });

  // -- Error handling --

  it("toasts error and re-enables button when action fails", async () => {
    startApp.mockRejectedValue(new Error("Connection refused"));

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="stopped" />);

    const btn = getByTestId("btn-start-my_app") as HTMLButtonElement;
    fireEvent.click(btn);

    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    });

    expect(toast.error).toHaveBeenCalledWith('Failed to start "my_app": Connection refused');
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("toasts stringified error for non-Error throws", async () => {
    startApp.mockRejectedValue("raw string error");

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="stopped" />);

    const btn = getByTestId("btn-start-my_app") as HTMLButtonElement;
    fireEvent.click(btn);

    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    });

    expect(toast.error).toHaveBeenCalledWith('Failed to start "my_app": raw string error');
  });

  it("ignores second click while first action is in-flight", async () => {
    let resolveAction!: (value: ActionResponse) => void;
    startApp.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveAction = resolve;
        }),
    );

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="stopped" />);

    const btn = getByTestId("btn-start-my_app") as HTMLButtonElement;

    // First click — starts the action
    fireEvent.click(btn);
    expect(startApp).toHaveBeenCalledTimes(1);

    // Second click while first is still in-flight — should be ignored
    fireEvent.click(btn);
    expect(startApp).toHaveBeenCalledTimes(1);

    // Resolve the pending action to clean up
    resolveAction({ status: "accepted", app_key: "my_app", action: "start" });
    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    });

    // Only the action that actually ran toasts
    expect(toast.success).toHaveBeenCalledTimes(1);
  });

  // -- Stop confirmation dialog --

  it("opens a confirm dialog instead of stopping immediately when confirmStop is set", () => {
    render(<ActionButtons appKey="my_app" status="running" confirmStop />);

    fireEvent.click(screen.getByTestId("btn-stop-my_app"));

    expect(screen.getByRole("alertdialog")).toBeDefined();
    expect(screen.getByText('Stop "my_app"? It will stop processing events until restarted.')).toBeDefined();
    expect(stopApp).not.toHaveBeenCalled();
  });

  it("calls stopApp when the confirm dialog's Stop action is confirmed", async () => {
    stopApp.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "stop" });

    render(<ActionButtons appKey="my_app" status="running" confirmStop />);

    fireEvent.click(screen.getByTestId("btn-stop-my_app"));
    fireEvent.click(screen.getByTestId("confirm-btn-danger"));

    expect(stopApp).toHaveBeenCalledWith("my_app");
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull();
    });
    expect(toast.success).toHaveBeenCalledWith('App "my_app" stopped');
  });

  it("does not call stopApp when the confirm dialog is cancelled", async () => {
    render(<ActionButtons appKey="my_app" status="running" confirmStop />);

    fireEvent.click(screen.getByTestId("btn-stop-my_app"));
    fireEvent.click(screen.getByText("Cancel"));

    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull();
    });
    expect(stopApp).not.toHaveBeenCalled();
  });
});

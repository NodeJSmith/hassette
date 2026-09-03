import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ActionResponse } from "../../api/endpoints";
import { ActionButtons, getStableInstanceRef } from "./action-buttons";

// Mock the API endpoints — we test the component logic, not the network.
vi.mock("../../api/endpoints", () => ({
  startApp: vi.fn(),
  stopApp: vi.fn(),
  reloadApp: vi.fn(),
  startInstance: vi.fn(),
  stopInstance: vi.fn(),
  reloadInstance: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const endpoints = await import("../../api/endpoints");
const startApp = vi.mocked(endpoints.startApp);
const stopApp = vi.mocked(endpoints.stopApp);
const reloadApp = vi.mocked(endpoints.reloadApp);
const startInstance = vi.mocked(endpoints.startInstance);
const stopInstance = vi.mocked(endpoints.stopInstance);
const reloadInstance = vi.mocked(endpoints.reloadInstance);

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

  it("shows Stop and Reload (not Start) when status is degraded", () => {
    const { getByTestId, queryByTestId } = render(<ActionButtons appKey="my_app" status="degraded" />);
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
    const user = userEvent.setup();
    // A controlled promise, rather than mockResolvedValue's already-settled promise, is needed
    // here: userEvent.click() internally awaits several microtask turns, so by the time it
    // resolves an already-settled mock promise would have flipped `loading` back to false
    // already, making the mid-flight "disabled while loading" state unobservable.
    let resolveStart: (value: {
      status: "accepted";
      app_key: string;
      action: string;
      instance_index: number | null;
    }) => void;
    startApp.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveStart = resolve;
        }),
    );

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="stopped" />);

    const btn = getByTestId("btn-start-my_app") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);

    const clickPromise = user.click(btn);
    await waitFor(() => expect(btn.disabled).toBe(true));
    expect(startApp).toHaveBeenCalledWith("my_app");

    resolveStart!({ status: "accepted", app_key: "my_app", action: "start", instance_index: null });
    await clickPromise;

    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    });

    expect(toast.success).toHaveBeenCalledWith("App 'my_app' started");
  });

  it("calls stopApp when Stop is clicked", async () => {
    const user = userEvent.setup();
    stopApp.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "stop", instance_index: null });

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="running" />);

    await user.click(getByTestId("btn-stop-my_app"));
    expect(stopApp).toHaveBeenCalledWith("my_app");

    await waitFor(() => {
      expect((getByTestId("btn-stop-my_app") as HTMLButtonElement).disabled).toBe(false);
    });

    expect(toast.success).toHaveBeenCalledWith("App 'my_app' stopped");
  });

  it("calls reloadApp when Reload is clicked", async () => {
    const user = userEvent.setup();
    reloadApp.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "reload", instance_index: null });

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="running" />);

    await user.click(getByTestId("btn-reload-my_app"));
    expect(reloadApp).toHaveBeenCalledWith("my_app");

    await waitFor(() => {
      expect((getByTestId("btn-reload-my_app") as HTMLButtonElement).disabled).toBe(false);
    });

    expect(toast.success).toHaveBeenCalledWith("App 'my_app' reloaded");
  });

  // -- Error handling --

  it("toasts error and re-enables button when action fails", async () => {
    const user = userEvent.setup();
    startApp.mockRejectedValue(new Error("Connection refused"));

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="stopped" />);

    const btn = getByTestId("btn-start-my_app") as HTMLButtonElement;
    await user.click(btn);

    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    });

    expect(toast.error).toHaveBeenCalledWith("Failed to start 'my_app': Connection refused");
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("toasts stringified error for non-Error throws", async () => {
    const user = userEvent.setup();
    startApp.mockRejectedValue("raw string error");

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="stopped" />);

    const btn = getByTestId("btn-start-my_app") as HTMLButtonElement;
    await user.click(btn);

    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    });

    expect(toast.error).toHaveBeenCalledWith("Failed to start 'my_app': raw string error");
  });

  it("ignores second click while first action is in-flight", async () => {
    const user = userEvent.setup();
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
    await user.click(btn);
    expect(startApp).toHaveBeenCalledTimes(1);

    // Second click while first is still in-flight — should be ignored
    await user.click(btn);
    expect(startApp).toHaveBeenCalledTimes(1);

    // Resolve the pending action to clean up
    resolveAction({ status: "accepted", app_key: "my_app", action: "start", instance_index: null });
    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    });

    // Only the action that actually ran toasts
    expect(toast.success).toHaveBeenCalledTimes(1);
  });

  // -- Stop confirmation dialog --

  it("opens a confirm dialog instead of stopping immediately when confirmStop is set", async () => {
    const user = userEvent.setup();
    render(<ActionButtons appKey="my_app" status="running" confirmStop />);

    await user.click(screen.getByTestId("btn-stop-my_app"));

    expect(screen.getByRole("alertdialog")).toBeDefined();
    expect(screen.getByText("Stop 'my_app'? It will stop processing events until restarted.")).toBeDefined();
    expect(stopApp).not.toHaveBeenCalled();
  });

  it("calls stopApp when the confirm dialog's Stop action is confirmed", async () => {
    const user = userEvent.setup();
    stopApp.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "stop", instance_index: null });

    render(<ActionButtons appKey="my_app" status="running" confirmStop />);

    await user.click(screen.getByTestId("btn-stop-my_app"));
    await user.click(screen.getByTestId("confirm-btn-danger"));

    expect(stopApp).toHaveBeenCalledWith("my_app");
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull();
    });
    expect(toast.success).toHaveBeenCalledWith("App 'my_app' stopped");
  });

  it("does not call stopApp when the confirm dialog is cancelled", async () => {
    const user = userEvent.setup();
    render(<ActionButtons appKey="my_app" status="running" confirmStop />);

    await user.click(screen.getByTestId("btn-stop-my_app"));
    await user.click(screen.getByText("Cancel"));

    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull();
    });
    expect(stopApp).not.toHaveBeenCalled();
  });

  // -- Instance-level routing --

  const instance = { index: 1, name: "office" };

  it("calls startInstance (not startApp) when instance prop is provided", async () => {
    const user = userEvent.setup();
    startInstance.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "start", instance_index: 1 });

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="stopped" instance={instance} />);

    await user.click(getByTestId("btn-start-my_app-1"));

    expect(startInstance).toHaveBeenCalledWith("my_app", 1);
    expect(startApp).not.toHaveBeenCalled();
  });

  it("calls stopInstance (not stopApp) when instance prop is provided", async () => {
    const user = userEvent.setup();
    stopInstance.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "stop", instance_index: 1 });

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="running" instance={instance} />);

    await user.click(getByTestId("btn-stop-my_app-1"));

    expect(stopInstance).toHaveBeenCalledWith("my_app", 1);
    expect(stopApp).not.toHaveBeenCalled();
  });

  it("calls reloadInstance (not reloadApp) when instance prop is provided", async () => {
    const user = userEvent.setup();
    reloadInstance.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "reload", instance_index: 1 });

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="running" instance={instance} />);

    await user.click(getByTestId("btn-reload-my_app-1"));

    expect(reloadInstance).toHaveBeenCalledWith("my_app", 1);
    expect(reloadApp).not.toHaveBeenCalled();
  });

  it("uses instance-aware testid and aria-label when instance prop is provided", () => {
    const { getByTestId } = render(<ActionButtons appKey="my_app" status="stopped" instance={instance} />);

    const btn = getByTestId("btn-start-my_app-1");
    expect(btn).toBeDefined();
    expect(btn.getAttribute("aria-label")).toBe("Start instance 'office'");
    // Icon-button tooltip must match the accessible name, not a static per-action label.
    expect(btn.getAttribute("title")).toBe("Start instance 'office'");
  });

  it("uses instance-aware toast text when instance prop is provided", async () => {
    const user = userEvent.setup();
    reloadInstance.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "reload", instance_index: 1 });

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="running" instance={instance} />);

    await user.click(getByTestId("btn-reload-my_app-1"));

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Instance 'office' of 'my_app' reloaded");
    });
  });

  it("shows instance-aware error toast when instance prop is provided and action fails", async () => {
    const user = userEvent.setup();
    startInstance.mockRejectedValue(new Error("Connection refused"));

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="stopped" instance={instance} />);

    await user.click(getByTestId("btn-start-my_app-1"));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Failed to start instance 'office' of 'my_app': Connection refused");
    });
  });

  it("warns when the server-confirmed instance_index disagrees with the requested one", async () => {
    const user = userEvent.setup();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    startInstance.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "start", instance_index: 2 });

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="stopped" instance={instance} />);

    await user.click(getByTestId("btn-start-my_app-1"));

    await waitFor(() => {
      expect(warnSpy).toHaveBeenCalledWith("Requested instance 1 of 'my_app' but server confirmed instance 2");
    });

    warnSpy.mockRestore();
  });

  it("does not warn when the server-confirmed instance_index matches the requested one", async () => {
    const user = userEvent.setup();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    startInstance.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "start", instance_index: 1 });

    const { getByTestId } = render(<ActionButtons appKey="my_app" status="stopped" instance={instance} />);

    await user.click(getByTestId("btn-start-my_app-1"));

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalled();
    });
    expect(warnSpy).not.toHaveBeenCalled();

    warnSpy.mockRestore();
  });

  it("shows instance name in stop confirm dialog title and description when instance prop is provided", async () => {
    const user = userEvent.setup();
    render(<ActionButtons appKey="my_app" status="running" confirmStop instance={instance} />);

    await user.click(screen.getByTestId("btn-stop-my_app-1"));

    expect(screen.getByText("Stop instance 'office'?")).toBeDefined();
    expect(
      screen.getByText("Stop instance 'office' of 'my_app'? It will stop processing events until restarted."),
    ).toBeDefined();
    expect(stopInstance).not.toHaveBeenCalled();
  });

  it("calls stopInstance when the confirm dialog's Stop action is confirmed with instance prop", async () => {
    const user = userEvent.setup();
    stopInstance.mockResolvedValue({ status: "accepted", app_key: "my_app", action: "stop", instance_index: 1 });

    render(<ActionButtons appKey="my_app" status="running" confirmStop instance={instance} />);

    await user.click(screen.getByTestId("btn-stop-my_app-1"));
    await user.click(screen.getByTestId("confirm-btn-danger"));

    expect(stopInstance).toHaveBeenCalledWith("my_app", 1);
  });
});

describe("getStableInstanceRef", () => {
  it("returns the same object reference for the same index and name", () => {
    const first = getStableInstanceRef(1, "office");
    const second = getStableInstanceRef(1, "office");
    expect(first).toBe(second);
  });

  it("returns distinct references for different index or name", () => {
    const office = getStableInstanceRef(1, "office");
    const otherIndex = getStableInstanceRef(2, "office");
    const otherName = getStableInstanceRef(1, "warehouse");
    expect(office).not.toBe(otherIndex);
    expect(office).not.toBe(otherName);
  });
});

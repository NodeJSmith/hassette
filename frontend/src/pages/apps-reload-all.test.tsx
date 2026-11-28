import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { ReloadAllResponse } from "../api/endpoints";
import { ReloadAllButton, reloadAllSummary } from "./apps-reload-all";

vi.mock(import("../api/endpoints"), async (importOriginal) => ({
  ...(await importOriginal()),
  reloadAllApps: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const endpoints = await import("../api/endpoints");
const reloadAllApps = vi.mocked(endpoints.reloadAllApps);
const { toast } = await import("sonner");

function response(apps: ReloadAllResponse["apps"]): ReloadAllResponse {
  const count = (result: string) => apps.filter((app) => app.result === result).length;
  return { apps, counts: { succeeded: count("succeeded"), failed: count("failed"), refused: count("refused") } };
}

type AppResult = ReloadAllResponse["apps"][number];

const LIGHTS: AppResult = { app_key: "lights", action: "reload", result: "succeeded", outcomes: [] };
const DOOR: AppResult = { app_key: "door", action: "reload", result: "failed", outcomes: [] };
const OLD: AppResult = { app_key: "old", action: "stop", result: "succeeded", outcomes: [] };
const NEW: AppResult = { app_key: "new", action: "start", result: "succeeded", outcomes: [] };

async function confirmReloadAll() {
  const user = userEvent.setup();
  render(<ReloadAllButton />);
  await user.click(screen.getByTestId("btn-reload-all"));
  await user.click(await screen.findByTestId("confirm-reload-all"));
}

describe("reloadAllSummary", () => {
  it("gives the counts when every app succeeded", () => {
    expect(reloadAllSummary(response([LIGHTS]))).toBe("Reload all: 1 app reloaded; 1 succeeded, 0 failed, 0 refused");
  });

  it("names each app that didn't succeed", () => {
    expect(reloadAllSummary(response([DOOR, LIGHTS]))).toBe(
      "Reload all: 2 apps reloaded; 1 succeeded, 1 failed, 0 refused. door (failed)",
    );
  });

  it("says which apps it stopped and started, not only reloaded", () => {
    expect(reloadAllSummary(response([LIGHTS, OLD, NEW]))).toBe(
      "Reload all: 1 app reloaded, 1 app stopped, 1 app started; 3 succeeded, 0 failed, 0 refused",
    );
  });

  it("says when no app was affected", () => {
    expect(reloadAllSummary(response([]))).toBe("Reload all: no apps affected; 0 succeeded, 0 failed, 0 refused");
  });
});

describe("ReloadAllButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("asks before reloading and sends nothing on cancel", async () => {
    const user = userEvent.setup();
    render(<ReloadAllButton />);

    await user.click(screen.getByTestId("btn-reload-all"));
    await user.click(await screen.findByText("Cancel"));

    expect(reloadAllApps).not.toHaveBeenCalled();
  });

  it("toasts success when every app reloaded", async () => {
    reloadAllApps.mockResolvedValue(response([LIGHTS]));

    await confirmReloadAll();

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Reload all: 1 app reloaded; 1 succeeded, 0 failed, 0 refused"),
    );
    expect(reloadAllApps).toHaveBeenCalledOnce();
  });

  it("toasts an error naming the failed apps", async () => {
    reloadAllApps.mockResolvedValue(response([DOOR, LIGHTS]));

    await confirmReloadAll();

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("door (failed)")));
  });

  it("toasts a refusal's detail verbatim", async () => {
    reloadAllApps.mockRejectedValue(
      new ApiError(409, "Conflict", "helpers/notify.py:12: invalid syntax", "reload_syntax_error"),
    );

    await confirmReloadAll();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Reload all refused: helpers/notify.py:12: invalid syntax"),
    );
  });

  it("says the outcome is unknown for an error that isn't a refusal", async () => {
    reloadAllApps.mockRejectedValue(new ApiError(504, "Gateway Timeout"));

    await confirmReloadAll();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Reload all may not have finished: API error: 504 Gateway Timeout. Check the app list for each app's status.",
      ),
    );
  });

  it("says the outcome is unknown for a network error", async () => {
    reloadAllApps.mockRejectedValue(new TypeError("Failed to fetch"));

    await confirmReloadAll();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("Reload all may not have finished: Failed to fetch"),
      ),
    );
  });
});

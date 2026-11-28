import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { ReloadAllResponse } from "../api/endpoints";
import { ReloadAllButton, reloadAllSummary } from "./apps-reload-all";

vi.mock("../api/endpoints", () => ({ reloadAllApps: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const endpoints = await import("../api/endpoints");
const reloadAllApps = vi.mocked(endpoints.reloadAllApps);
const { toast } = await import("sonner");

function response(apps: ReloadAllResponse["apps"]): ReloadAllResponse {
  const count = (result: string) => apps.filter((app) => app.result === result).length;
  return { apps, counts: { succeeded: count("succeeded"), failed: count("failed"), refused: count("refused") } };
}

type AppResult = ReloadAllResponse["apps"][number];

const LIGHTS: AppResult = { app_key: "lights", result: "succeeded", outcomes: [] };
const DOOR: AppResult = { app_key: "door", result: "failed", outcomes: [] };

async function confirmReloadAll() {
  const user = userEvent.setup();
  render(<ReloadAllButton />);
  await user.click(screen.getByTestId("btn-reload-all"));
  await user.click(await screen.findByTestId("confirm-reload-all"));
}

describe("reloadAllSummary", () => {
  it("gives the counts when every app succeeded", () => {
    expect(reloadAllSummary(response([LIGHTS]))).toBe("Reloaded 1 app: 1 succeeded, 0 failed, 0 refused");
  });

  it("names each app that didn't succeed", () => {
    expect(reloadAllSummary(response([DOOR, LIGHTS]))).toBe(
      "Reloaded 2 apps: 1 succeeded, 1 failed, 0 refused. door (failed)",
    );
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

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Reloaded 1 app: 1 succeeded, 0 failed, 0 refused"));
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
});

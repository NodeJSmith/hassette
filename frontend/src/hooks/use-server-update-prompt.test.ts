import { renderHook } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initialState, useAppStore } from "../state/store";
import { SERVER_UPDATED_TOAST_ID, useServerUpdatePrompt } from "./use-server-update-prompt";

vi.mock("sonner", () => ({
  toast: { info: vi.fn() },
}));

describe("useServerUpdatePrompt", () => {
  beforeEach(() => {
    vi.mocked(toast.info).mockClear();
    useAppStore.setState(initialState());
  });

  it("shows nothing while the server version is unchanged", () => {
    renderHook(() => useServerUpdatePrompt());

    expect(toast.info).not.toHaveBeenCalled();
  });

  it("shows a persistent reload prompt once the server is updated", () => {
    useAppStore.setState({ serverUpdated: true });

    renderHook(() => useServerUpdatePrompt());

    expect(toast.info).toHaveBeenCalledWith(
      "Hassette was updated",
      expect.objectContaining({
        id: SERVER_UPDATED_TOAST_ID,
        duration: Number.POSITIVE_INFINITY,
        action: expect.objectContaining({ label: "Reload" }),
      }),
    );
  });
});

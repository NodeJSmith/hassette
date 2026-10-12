import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resolveAppUrl } from "../lib/base-path";
import { LOGIN_PATH } from "../utils/app-routes";
import { reloadTop, SessionExpiredPage } from "./session-expired";

const originalLocation = window.location;

/** A `Location` stand-in whose `reload` and `assign` can be asserted. */
function fakeLocation(): Location {
  return { ...originalLocation, reload: vi.fn(), assign: vi.fn() };
}

beforeEach(() => {
  Object.defineProperty(window, "location", { value: fakeLocation(), writable: true, configurable: true });
});

afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(window, "location", { value: originalLocation, writable: true, configurable: true });
});

describe("reloadTop", () => {
  it("reloads a same-origin top frame, not this one", () => {
    const topFrame = { location: fakeLocation() } as unknown as Window;
    vi.spyOn(window, "top", "get").mockReturnValue(topFrame);

    reloadTop();

    expect(topFrame.location.reload).toHaveBeenCalledOnce();
    expect(window.location.reload).not.toHaveBeenCalled();
  });

  it("falls back to this window when the top frame is cross-origin", () => {
    const topFrame = {
      get location(): Location {
        throw new DOMException("Blocked a frame with origin", "SecurityError");
      },
    } as unknown as Window;
    vi.spyOn(window, "top", "get").mockReturnValue(topFrame);

    reloadTop();

    expect(window.location.reload).toHaveBeenCalledOnce();
  });

  it("falls back to this window when there is no top frame", () => {
    vi.spyOn(window, "top", "get").mockReturnValue(null);

    reloadTop();

    expect(window.location.reload).toHaveBeenCalledOnce();
  });
});

describe("SessionExpiredPage", () => {
  it("offers Hassette's login when asked to, and it navigates to the login view", () => {
    render(<SessionExpiredPage offerLogin />);

    fireEvent.click(screen.getByRole("button", { name: "Log in to Hassette" }));

    expect(window.location.assign).toHaveBeenCalledWith(resolveAppUrl(LOGIN_PATH));
  });

  it("offers only Reload when login can't help", () => {
    render(<SessionExpiredPage offerLogin={false} />);

    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Log in to Hassette" })).toBeNull();
  });

  it("offers login by default at root base", () => {
    render(<SessionExpiredPage />);

    expect(screen.getByRole("button", { name: "Log in to Hassette" })).toBeTruthy();
  });
});

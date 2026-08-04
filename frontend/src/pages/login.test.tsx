import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createWouterMock } from "../test/mock-wouter";
import { server } from "../test/server";
import { LoginPage } from "./login";

const mockNavigate = vi.hoisted(() => vi.fn());

vi.mock("wouter", () => createWouterMock({ useLocation: vi.fn().mockReturnValue(["/login", mockNavigate]) }));

describe("LoginPage", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it("renders a token input and a submit button", () => {
    render(<LoginPage />);
    expect(screen.getByTestId("login-token-input")).toBeDefined();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeDefined();
  });

  it("submits the pasted token to POST /api/auth/session and navigates home on success", async () => {
    const user = userEvent.setup();
    let receivedBody: unknown;
    server.use(
      http.post("/api/auth/session", async ({ request }) => {
        receivedBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );

    render(<LoginPage />);
    await user.type(screen.getByTestId("login-token-input"), "correct-token");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(receivedBody).toEqual({ token: "correct-token" });
    expect(mockNavigate).toHaveBeenCalledWith("/apps");
  });

  it("renders a visible error and stays on the login view when the token is rejected", async () => {
    const user = userEvent.setup();
    server.use(http.post("/api/auth/session", () => HttpResponse.json({ detail: "Invalid token" }, { status: 401 })));

    render(<LoginPage />);
    await user.type(screen.getByTestId("login-token-input"), "wrong-token");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect((await screen.findByTestId("login-error")).textContent).toBe("Invalid token");
    expect(mockNavigate).not.toHaveBeenCalled();
    // Still on the login view — the input is still rendered and usable.
    expect(screen.getByTestId("login-token-input")).toBeDefined();
  });

  it("shows an error and re-enables the form when the network request fails outright", async () => {
    const user = userEvent.setup();
    server.use(http.post("/api/auth/session", () => HttpResponse.error()));

    render(<LoginPage />);
    await user.type(screen.getByTestId("login-token-input"), "some-token");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect((await screen.findByTestId("login-error")).textContent).toBe(
      "Could not reach the server. Check your connection and try again.",
    );
    expect(mockNavigate).not.toHaveBeenCalled();
    // Submit button is re-enabled, not stuck on "Signing in…" forever.
    const submitButton = screen.getByRole("button", { name: /sign in/i }) as HTMLButtonElement;
    expect(submitButton.disabled).toBe(false);
  });
});

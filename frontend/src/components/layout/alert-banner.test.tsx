import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { AlertBanner } from "./alert-banner";

describe("AlertBanner", () => {
  it("renders nothing when no failed apps", () => {
    const { container } = render(<AlertBanner failedApps={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders alert when one app has failed", () => {
    const { container, getByText } = render(
      <AlertBanner failedApps={[{ app_key: "my_app", error_message: "crash" }]} />,
    );
    expect(container.querySelector(".ht-alert--danger")).not.toBeNull();
    expect(getByText("1 app failed")).toBeDefined();
  });

  it("renders plural heading when multiple apps fail", () => {
    const { getByText } = render(
      <AlertBanner
        failedApps={[
          { app_key: "app_a", error_message: null },
          { app_key: "app_b", error_message: null },
        ]}
      />,
    );
    expect(getByText("2 apps failed")).toBeDefined();
  });

  it("renders app_key as link", () => {
    const { container } = render(
      <AlertBanner failedApps={[{ app_key: "my_app", error_message: null }]} />,
    );
    const link = container.querySelector("a[href='/apps/my_app']");
    expect(link).not.toBeNull();
    expect(link!.textContent).toBe("my_app");
  });

  it("renders error_message when provided", () => {
    const { getByText } = render(
      <AlertBanner failedApps={[{ app_key: "my_app", error_message: "NullPointerError" }]} />,
    );
    expect(getByText(/NullPointerError/)).toBeDefined();
  });

  it("does not render error span when error_message is null", () => {
    const { container } = render(
      <AlertBanner failedApps={[{ app_key: "my_app", error_message: null }]} />,
    );
    // ht-text-secondary wraps the error message; should not exist when null
    expect(container.querySelector(".ht-text-secondary")).toBeNull();
  });

  it("renders all failed apps in the list", () => {
    const { getAllByRole } = render(
      <AlertBanner
        failedApps={[
          { app_key: "app_a", error_message: "err1" },
          { app_key: "app_b", error_message: "err2" },
          { app_key: "app_c", error_message: "err3" },
        ]}
      />,
    );
    const links = getAllByRole("link");
    expect(links).toHaveLength(3);
    expect(links[0].getAttribute("href")).toBe("/apps/app_a");
    expect(links[1].getAttribute("href")).toBe("/apps/app_b");
    expect(links[2].getAttribute("href")).toBe("/apps/app_c");
  });
});

import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createWouterMock } from "../../test/mock-wouter";
import { Breadcrumbs, SIDEBAR_VISIBLE_CRUMBS } from "./breadcrumbs";

vi.mock("wouter", () => createWouterMock());

describe("Breadcrumbs", () => {
  it("renders nothing when the trail is empty", () => {
    const { container } = render(<Breadcrumbs items={[]} />);
    expect(container.querySelector("nav")).toBeNull();
  });

  it("links every crumb except the current page", () => {
    const { getByTestId } = render(
      <Breadcrumbs
        items={[{ label: "apps", href: "/apps" }, { label: "demo_app", href: "/apps/demo_app" }, { label: "handlers" }]}
      />,
    );
    const links = getByTestId("breadcrumbs").querySelectorAll("a");
    expect(Array.from(links).map((a) => a.textContent)).toEqual(["apps", "demo_app"]);
  });

  it("marks the current page for assistive tech", () => {
    const { getByTestId } = render(<Breadcrumbs items={[{ label: "apps", href: "/apps" }, { label: "demo_app" }]} />);
    const current = getByTestId("breadcrumbs").querySelector("[aria-current='page']");
    expect(current?.textContent).toBe("demo_app");
  });

  it("labels the nav landmark", () => {
    const { getByLabelText } = render(<Breadcrumbs items={[{ label: "apps" }]} />);
    expect(getByLabelText("Breadcrumb")).toBeDefined();
  });

  it("keeps the full trail in the DOM so narrow viewports stay accessible", () => {
    // The ellipsis and the hidden ancestors are a CSS concern; nothing is dropped from
    // the markup, so screen readers get the whole path at every width.
    const { getByTestId } = render(
      <Breadcrumbs
        items={[
          { label: "apps", href: "/apps" },
          { label: "demo_app", href: "/apps/demo_app" },
          { label: "handlers", href: "/apps/demo_app/handlers" },
          { label: "on_light" },
        ]}
      />,
    );
    const trail = getByTestId("breadcrumbs");
    expect(trail.textContent).toContain("apps");
    expect(trail.textContent).toContain("on_light");
  });

  it("omits the ellipsis stand-in when nothing would be hidden", () => {
    const { getByTestId } = render(<Breadcrumbs items={[{ label: "apps", href: "/apps" }, { label: "demo_app" }]} />);
    expect(getByTestId("breadcrumbs").textContent).not.toContain("…");
  });

  it("adds an ellipsis stand-in once ancestors can be hidden", () => {
    const { getByTestId } = render(
      <Breadcrumbs
        items={[{ label: "apps", href: "/apps" }, { label: "demo_app", href: "/apps/demo_app" }, { label: "handlers" }]}
      />,
    );
    expect(getByTestId("breadcrumbs").textContent).toContain("…");
  });

  it("keeps the hard-coded nth-last-child selectors in step with SIDEBAR_VISIBLE_CRUMBS", () => {
    // Tailwind cannot interpolate the constant into class names, so the selectors carry their
    // own literals. Changing one without the other moves the ellipsis threshold while the
    // clipping and separator-hiding stay put.
    const { getByTestId } = render(
      <Breadcrumbs
        items={[{ label: "apps", href: "/apps" }, { label: "demo_app", href: "/apps/demo_app" }, { label: "handlers" }]}
      />,
    );
    const crumb = getByTestId("breadcrumbs").querySelector("[aria-current='page']")?.closest("li");
    expect(crumb?.className).toContain(`nth-last-child(-n+${SIDEBAR_VISIBLE_CRUMBS})`);
    expect(crumb?.className).toContain(`nth-last-child(${SIDEBAR_VISIBLE_CRUMBS})`);
  });
});

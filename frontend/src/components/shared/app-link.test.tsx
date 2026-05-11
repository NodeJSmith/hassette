import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";

vi.mock("wouter", () => ({
  Link: ({ href, children, class: cls }: Record<string, unknown>) =>
    <a href={href as string} class={cls as string}>{children as never}</a>,
}));

import { AppLink } from "./app-link";

describe("AppLink — basic href", () => {
  it("renders a link to /apps/:key with no extras", () => {
    const { container } = render(<AppLink appKey="my_app" />);
    const a = container.querySelector("a");
    expect(a?.getAttribute("href")).toBe("/apps/my_app");
  });

  it("renders appKey as children when no children given", () => {
    const { container } = render(<AppLink appKey="my_app" />);
    expect(container.querySelector("a")?.textContent).toBe("my_app");
  });

  it("renders provided children", () => {
    const { container } = render(<AppLink appKey="my_app">My App</AppLink>);
    expect(container.querySelector("a")?.textContent).toBe("My App");
  });
});

describe("AppLink — instanceIndex as query param", () => {
  it("appends ?instance=N when instanceIndex is provided", () => {
    const { container } = render(<AppLink appKey="my_app" instanceIndex={2} />);
    const href = container.querySelector("a")?.getAttribute("href");
    expect(href).toBe("/apps/my_app?instance=2");
  });

  it("appends ?instance=0 when instanceIndex is 0", () => {
    const { container } = render(<AppLink appKey="my_app" instanceIndex={0} />);
    const href = container.querySelector("a")?.getAttribute("href");
    expect(href).toBe("/apps/my_app?instance=0");
  });

  it("does not append instance param when instanceIndex is undefined", () => {
    const { container } = render(<AppLink appKey="my_app" />);
    const href = container.querySelector("a")?.getAttribute("href");
    expect(href).toBe("/apps/my_app");
    expect(href).not.toContain("instance");
  });
});

describe("AppLink — handlerId prop", () => {
  it("appends /handlers/:handlerId to the path when handlerId is set", () => {
    const { container } = render(<AppLink appKey="my_app" handlerId="h-42" />);
    const href = container.querySelector("a")?.getAttribute("href");
    expect(href).toBe("/apps/my_app/handlers/h-42");
  });

  it("combines handlerId path and instance query param", () => {
    const { container } = render(<AppLink appKey="my_app" handlerId="h-42" instanceIndex={1} />);
    const href = container.querySelector("a")?.getAttribute("href");
    expect(href).toBe("/apps/my_app/handlers/h-42?instance=1");
  });

  it("does not append handlers segment when handlerId is undefined", () => {
    const { container } = render(<AppLink appKey="my_app" />);
    const href = container.querySelector("a")?.getAttribute("href");
    expect(href).not.toContain("handlers");
  });
});

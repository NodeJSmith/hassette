import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createWouterMock } from "../../test/mock-wouter";
import { AppLink } from "./app-link";

vi.mock("wouter", () => createWouterMock());

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

describe("AppLink — instanceName as query param", () => {
  it("appends ?instance=<name> when instanceName is provided", () => {
    const { container } = render(<AppLink appKey="my_app" instanceName="office" />);
    const href = container.querySelector("a")?.getAttribute("href");
    expect(href).toBe("/apps/my_app?instance=office");
  });

  it("does not append instance param when instanceName is undefined", () => {
    const { container } = render(<AppLink appKey="my_app" />);
    const href = container.querySelector("a")?.getAttribute("href");
    expect(href).toBe("/apps/my_app");
    expect(href).not.toContain("instance");
  });
});

describe("AppLink — handler props", () => {
  it("builds handler path when handlerKind and handlerId are set", () => {
    const { container } = render(<AppLink appKey="my_app" handlerKind="listener" handlerId={42} />);
    const href = container.querySelector("a")?.getAttribute("href");
    expect(href).toBe("/apps/my_app/handlers/listener/42");
  });

  it("combines handler path and instance query param", () => {
    const { container } = render(
      <AppLink appKey="my_app" handlerKind="listener" handlerId={42} instanceName="office" />,
    );
    const href = container.querySelector("a")?.getAttribute("href");
    expect(href).toBe("/apps/my_app/handlers/listener/42?instance=office");
  });

  it("does not append handlers segment when handler props are undefined", () => {
    const { container } = render(<AppLink appKey="my_app" />);
    const href = container.querySelector("a")?.getAttribute("href");
    expect(href).not.toContain("handlers");
  });
});

import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/button";

describe("Button", () => {
  describe("type attribute", () => {
    it("always renders type='button'", () => {
      const { getByRole } = render(<Button>click me</Button>);
      expect(getByRole("button").getAttribute("type")).toBe("button");
    });
  });

  describe("variant prop", () => {
    it("applies no semantic variant class when variant is 'default'", () => {
      const { getByRole } = render(<Button variant="default">btn</Button>);
      expect(getByRole("button").getAttribute("data-variant")).toBe("default");
    });

    it("applies success styling when variant='success'", () => {
      const { getByRole } = render(<Button variant="success">btn</Button>);
      expect(getByRole("button").getAttribute("data-variant")).toBe("success");
    });

    it("applies warning styling when variant='warning'", () => {
      const { getByRole } = render(<Button variant="warning">btn</Button>);
      expect(getByRole("button").getAttribute("data-variant")).toBe("warning");
    });

    it("applies info styling when variant='info'", () => {
      const { getByRole } = render(<Button variant="info">btn</Button>);
      expect(getByRole("button").getAttribute("data-variant")).toBe("info");
    });

    it("applies danger styling when variant='danger'", () => {
      const { getByRole } = render(<Button variant="danger">btn</Button>);
      expect(getByRole("button").getAttribute("data-variant")).toBe("danger");
    });

    it("applies ghost styling when variant='ghost'", () => {
      const { getByRole } = render(<Button variant="ghost">btn</Button>);
      const el = getByRole("button");
      expect(el.getAttribute("data-variant")).toBe("ghost");
      expect(el.className).not.toMatch(/\bborder-\[var\(--ok\)\]/);
    });

    it("supports the success-ghost compound variant", () => {
      const { getByRole } = render(<Button variant="success-ghost">btn</Button>);
      expect(getByRole("button").getAttribute("data-variant")).toBe("success-ghost");
    });

    it("supports the warning-ghost compound variant", () => {
      const { getByRole } = render(<Button variant="warning-ghost">btn</Button>);
      expect(getByRole("button").getAttribute("data-variant")).toBe("warning-ghost");
    });

    it("supports the info-ghost compound variant", () => {
      const { getByRole } = render(<Button variant="info-ghost">btn</Button>);
      expect(getByRole("button").getAttribute("data-variant")).toBe("info-ghost");
    });
  });

  describe("size prop", () => {
    it("applies xs size", () => {
      const { getByRole } = render(<Button size="xs">btn</Button>);
      expect(getByRole("button").getAttribute("data-size")).toBe("xs");
    });

    it("applies sm size", () => {
      const { getByRole } = render(<Button size="sm">btn</Button>);
      expect(getByRole("button").getAttribute("data-size")).toBe("sm");
    });

    it("applies icon size", () => {
      const { getByRole } = render(<Button size="icon">btn</Button>);
      expect(getByRole("button").getAttribute("data-size")).toBe("icon");
    });

    it("applies icon-xs size", () => {
      const { getByRole } = render(<Button size="icon-xs">btn</Button>);
      expect(getByRole("button").getAttribute("data-size")).toBe("icon-xs");
    });
  });

  describe("class prop", () => {
    it("merges additional class into button className", () => {
      const { getByRole } = render(<Button className="my-custom-class">btn</Button>);
      expect(getByRole("button").className).toMatch(/my-custom-class/);
    });
  });

  describe("disabled prop", () => {
    it("sets disabled attribute when disabled=true", () => {
      const { getByRole } = render(<Button disabled>btn</Button>);
      expect((getByRole("button") as HTMLButtonElement).disabled).toBe(true);
    });
  });

  describe("ref", () => {
    it("forwards ref to the underlying button element", () => {
      const ref = createRef<HTMLButtonElement>();
      const { getByRole } = render(<Button ref={ref}>btn</Button>);
      expect(ref.current).toBe(getByRole("button"));
    });
  });

  describe("pass-through attributes", () => {
    it("passes aria-label through to button element", () => {
      const { getByRole } = render(<Button aria-label="close dialog">btn</Button>);
      expect(getByRole("button").getAttribute("aria-label")).toBe("close dialog");
    });

    it("calls onClick handler when clicked", async () => {
      const user = userEvent.setup();
      const onClick = vi.fn();
      const { getByRole } = render(<Button onClick={onClick}>btn</Button>);
      await user.click(getByRole("button"));
      expect(onClick).toHaveBeenCalledOnce();
    });
  });

  describe("defaults", () => {
    it("renders children", () => {
      const { getByRole } = render(<Button>hello world</Button>);
      expect(getByRole("button").textContent).toBe("hello world");
    });

    it("uses default variant and size when none provided", () => {
      const { getByRole } = render(<Button>btn</Button>);
      const el = getByRole("button");
      expect(el.getAttribute("data-variant")).toBe("default");
      expect(el.getAttribute("data-size")).toBe("default");
    });
  });
});

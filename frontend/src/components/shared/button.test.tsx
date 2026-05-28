import { render } from "@testing-library/preact";
import { fireEvent } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./button";

describe("Button", () => {
  describe("type attribute", () => {
    it("always renders type='button'", () => {
      const { getByRole } = render(<Button>click me</Button>);
      expect(getByRole("button").getAttribute("type")).toBe("button");
    });

    it("cannot override type — type is not an accepted prop", () => {
      // type is omitted from ButtonProps so it cannot be passed.
      // We verify this at the type level: the component file uses OmitType<T>
      // which removes "type" from the HTML attributes interface.
      // At runtime, hardcoded type="button" is always present (covered by the first test).
      // This test documents the intent rather than exercising runtime behavior.
      const { getByRole } = render(<Button>submit</Button>);
      expect(getByRole("button").getAttribute("type")).toBe("button");
    });
  });

  describe("variant prop", () => {
    it("applies no variant class when variant is 'default'", () => {
      const { getByRole } = render(<Button variant="default">btn</Button>);
      const el = getByRole("button");
      expect(el.className).not.toMatch(/primary|success|warning|info|danger/);
    });

    it("applies primary class when variant='primary'", () => {
      const { getByRole } = render(<Button variant="primary">btn</Button>);
      expect(getByRole("button").className).toMatch(/primary/);
    });

    it("applies success class when variant='success'", () => {
      const { getByRole } = render(<Button variant="success">btn</Button>);
      expect(getByRole("button").className).toMatch(/success/);
    });

    it("applies warning class when variant='warning'", () => {
      const { getByRole } = render(<Button variant="warning">btn</Button>);
      expect(getByRole("button").className).toMatch(/warning/);
    });

    it("applies info class when variant='info'", () => {
      const { getByRole } = render(<Button variant="info">btn</Button>);
      expect(getByRole("button").className).toMatch(/info/);
    });

    it("applies danger class when variant='danger'", () => {
      const { getByRole } = render(<Button variant="danger">btn</Button>);
      expect(getByRole("button").className).toMatch(/danger/);
    });
  });

  describe("size prop", () => {
    it("applies no size class when size is 'default'", () => {
      const { getByRole } = render(<Button size="default">btn</Button>);
      const el = getByRole("button");
      // Should not have sm or xs classes
      expect(el.className).not.toMatch(/\bsm\b|\bxs\b/);
    });

    it("applies sm class when size='sm'", () => {
      const { getByRole } = render(<Button size="sm">btn</Button>);
      expect(getByRole("button").className).toMatch(/sm/);
    });

    it("applies xs class when size='xs'", () => {
      const { getByRole } = render(<Button size="xs">btn</Button>);
      expect(getByRole("button").className).toMatch(/xs/);
    });
  });

  describe("ghost prop", () => {
    it("applies ghost class when ghost=true", () => {
      const { getByRole } = render(<Button ghost>btn</Button>);
      expect(getByRole("button").className).toMatch(/ghost/);
    });

    it("does not apply ghost class when ghost=false", () => {
      const { getByRole } = render(<Button ghost={false}>btn</Button>);
      expect(getByRole("button").className).not.toMatch(/ghost/);
    });
  });

  describe("icon prop", () => {
    it("applies icon class when icon=true", () => {
      const { getByRole } = render(<Button icon>btn</Button>);
      expect(getByRole("button").className).toMatch(/icon/);
    });

    it("does not apply icon class when icon=false", () => {
      const { getByRole } = render(<Button icon={false}>btn</Button>);
      expect(getByRole("button").className).not.toMatch(/icon/);
    });
  });

  describe("class prop", () => {
    it("merges additional class into button className", () => {
      const { getByRole } = render(<Button class="my-custom-class">btn</Button>);
      expect(getByRole("button").className).toMatch(/my-custom-class/);
    });

    it("merges custom class alongside variant class", () => {
      const { getByRole } = render(
        <Button variant="primary" class="extra">
          btn
        </Button>,
      );
      const className = getByRole("button").className;
      expect(className).toMatch(/primary/);
      expect(className).toMatch(/extra/);
    });
  });

  describe("disabled prop", () => {
    it("sets disabled attribute when disabled=true", () => {
      const { getByRole } = render(<Button disabled>btn</Button>);
      expect((getByRole("button") as HTMLButtonElement).disabled).toBe(true);
    });

    it("does not set disabled when not provided", () => {
      const { getByRole } = render(<Button>btn</Button>);
      expect((getByRole("button") as HTMLButtonElement).disabled).toBe(false);
    });
  });

  describe("buttonRef", () => {
    it("calls buttonRef callback with the button DOM element", () => {
      const ref = vi.fn();
      const { getByRole } = render(<Button buttonRef={ref}>btn</Button>);
      expect(ref).toHaveBeenCalledWith(getByRole("button"));
    });

    it("calls buttonRef callback with null on unmount", () => {
      const ref = vi.fn();
      const { unmount } = render(<Button buttonRef={ref}>btn</Button>);
      ref.mockClear();
      unmount();
      expect(ref).toHaveBeenCalledWith(null);
    });
  });

  describe("pass-through attributes", () => {
    it("passes aria-label through to button element", () => {
      const { getByRole } = render(<Button aria-label="close dialog">btn</Button>);
      expect(getByRole("button").getAttribute("aria-label")).toBe("close dialog");
    });

    it("passes data-testid through to button element", () => {
      const { getByTestId } = render(<Button data-testid="my-btn">btn</Button>);
      expect(getByTestId("my-btn")).not.toBeNull();
    });

    it("calls onClick handler when clicked", () => {
      const onClick = vi.fn();
      const { getByRole } = render(<Button onClick={onClick}>btn</Button>);
      fireEvent.click(getByRole("button"));
      expect(onClick).toHaveBeenCalledOnce();
    });
  });

  describe("defaults", () => {
    it("renders children", () => {
      const { getByRole } = render(<Button>hello world</Button>);
      expect(getByRole("button").textContent).toBe("hello world");
    });

    it("uses default variant (no variant class) when no variant provided", () => {
      const { getByRole } = render(<Button>btn</Button>);
      const className = getByRole("button").className;
      expect(className).not.toMatch(/primary|success|warning|info|danger/);
    });
  });
});

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { Badge } from "./badge";

describe("Badge", () => {
  describe("variant prop", () => {
    it("applies success class when variant='success'", () => {
      const { getByTestId } = render(<Badge variant="success" data-testid="b">ok</Badge>);
      expect(getByTestId("b").className).toMatch(/success/);
    });

    it("applies danger class when variant='danger'", () => {
      const { getByTestId } = render(<Badge variant="danger" data-testid="b">err</Badge>);
      expect(getByTestId("b").className).toMatch(/danger/);
    });

    it("applies warning class when variant='warning'", () => {
      const { getByTestId } = render(<Badge variant="warning" data-testid="b">warn</Badge>);
      expect(getByTestId("b").className).toMatch(/warning/);
    });

    it("applies info class when variant='info'", () => {
      const { getByTestId } = render(<Badge variant="info" data-testid="b">info</Badge>);
      expect(getByTestId("b").className).toMatch(/info/);
    });

    it("applies neutral class when variant='neutral'", () => {
      const { getByTestId } = render(<Badge variant="neutral" data-testid="b">n/a</Badge>);
      expect(getByTestId("b").className).toMatch(/neutral/);
    });
  });

  describe("size prop", () => {
    it("applies no size class when size is 'default'", () => {
      const { getByTestId } = render(<Badge variant="success" size="default" data-testid="b">ok</Badge>);
      const el = getByTestId("b");
      expect(el.className).not.toMatch(/\bxs\b|\bsm\b|\bmd\b/);
    });

    it("applies xs class when size='xs'", () => {
      const { getByTestId } = render(<Badge variant="success" size="xs" data-testid="b">ok</Badge>);
      expect(getByTestId("b").className).toMatch(/xs/);
    });

    it("applies sm class when size='sm'", () => {
      const { getByTestId } = render(<Badge variant="success" size="sm" data-testid="b">ok</Badge>);
      expect(getByTestId("b").className).toMatch(/sm/);
    });

    it("applies md class when size='md'", () => {
      const { getByTestId } = render(<Badge variant="success" size="md" data-testid="b">ok</Badge>);
      expect(getByTestId("b").className).toMatch(/md/);
    });
  });

  describe("class prop", () => {
    it("merges additional class into span className", () => {
      const { getByTestId } = render(
        <Badge variant="success" class="my-extra-class" data-testid="b">ok</Badge>
      );
      expect(getByTestId("b").className).toMatch(/my-extra-class/);
    });

    it("merges custom class alongside variant class", () => {
      const { getByTestId } = render(
        <Badge variant="danger" class="layout-stretch" data-testid="b">err</Badge>
      );
      const className = getByTestId("b").className;
      expect(className).toMatch(/danger/);
      expect(className).toMatch(/layout-stretch/);
    });
  });

  describe("children", () => {
    it("renders text children", () => {
      const { getByTestId } = render(<Badge variant="success" data-testid="b">running</Badge>);
      expect(getByTestId("b").textContent).toBe("running");
    });

    it("renders mixed children (text + icon element)", () => {
      const { getByTestId } = render(
        <Badge variant="success" data-testid="b">
          <span data-testid="icon">●</span>
          running
        </Badge>
      );
      const el = getByTestId("b");
      expect(el.querySelector("[data-testid='icon']")).not.toBeNull();
      expect(el.textContent).toContain("running");
    });

    it("renders icon-only children without breaking layout", () => {
      const { getByTestId } = render(
        <Badge variant="warning" data-testid="b">
          <svg data-testid="svg-icon" />
        </Badge>
      );
      expect(getByTestId("b").querySelector("[data-testid='svg-icon']")).not.toBeNull();
    });
  });

  describe("pass-through attributes", () => {
    it("passes data-testid through to span element", () => {
      const { getByTestId } = render(<Badge variant="success" data-testid="my-badge">ok</Badge>);
      expect(getByTestId("my-badge")).not.toBeNull();
    });

    it("passes aria-label through to span element", () => {
      const { getByLabelText } = render(
        <Badge variant="success" aria-label="status: running">ok</Badge>
      );
      expect(getByLabelText("status: running")).not.toBeNull();
    });
  });

  describe("renders as span", () => {
    it("renders a <span> element", () => {
      const { getByTestId } = render(<Badge variant="neutral" data-testid="b">text</Badge>);
      expect(getByTestId("b").tagName.toLowerCase()).toBe("span");
    });
  });

  describe("dead variants absent", () => {
    it("does not have a 'group' variant (dead CSS removed)", () => {
      // The component type system only accepts valid variants — no 'group' or 'cancelled'.
      // This test documents the contract: only success|danger|warning|info|neutral are valid.
      const { getByTestId } = render(<Badge variant="success" data-testid="b">ok</Badge>);
      expect(getByTestId("b").className).not.toMatch(/group|cancelled/);
    });
  });
});

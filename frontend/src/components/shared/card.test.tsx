import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { useRef } from "preact/hooks";
import { Card } from "./card";

describe("Card", () => {
  describe("renders as div", () => {
    it("renders a <div> element", () => {
      const { getByTestId } = render(
        <Card data-testid="c">content</Card>
      );
      expect(getByTestId("c").tagName.toLowerCase()).toBe("div");
    });
  });

  describe("variant prop", () => {
    it("applies base card class when variant='default'", () => {
      const { getByTestId } = render(
        <Card variant="default" data-testid="c">content</Card>
      );
      // Should have a class (the base .card module class)
      expect(getByTestId("c").className).toBeTruthy();
    });

    it("applies compact modifier class when variant='compact'", () => {
      const { getByTestId } = render(
        <Card variant="compact" data-testid="c">content</Card>
      );
      expect(getByTestId("c").className).toMatch(/compact/);
    });

    it("applies config modifier class when variant='config'", () => {
      const { getByTestId } = render(
        <Card variant="config" data-testid="c">content</Card>
      );
      expect(getByTestId("c").className).toMatch(/config/);
    });

    it("applies error class when variant='error'", () => {
      const { getByTestId } = render(
        <Card variant="error" data-testid="c">content</Card>
      );
      expect(getByTestId("c").className).toMatch(/error/);
    });

    it("uses default variant when no variant is provided", () => {
      const { getByTestId } = render(
        <Card data-testid="c">content</Card>
      );
      // Has a class (base) but no compact/config/error specific class
      const className = getByTestId("c").className;
      expect(className).not.toMatch(/compact|config|error/);
    });
  });

  describe("error variant absorbs base styles", () => {
    it("error variant applies only the error class (base styles merged in)", () => {
      const { getByTestId } = render(
        <Card variant="error" data-testid="c">content</Card>
      );
      // The error class contains both base card styles and error overrides.
      // It should NOT separately apply .card alongside .error —
      // i.e., there is exactly ONE module class on the element (the .error class).
      const classNames = getByTestId("c").className.trim().split(/\s+/);
      // Filter out any extra classes added via clsx (like custom class prop)
      // The element should have just one meaningful module class for error variant.
      expect(classNames.length).toBe(1);
    });

    it("other variants (compact) apply both base card and modifier class", () => {
      const { getByTestId } = render(
        <Card variant="compact" data-testid="c">content</Card>
      );
      // compact variant should have 2 module classes: .card + .compact
      const classNames = getByTestId("c").className.trim().split(/\s+/);
      expect(classNames.length).toBe(2);
    });
  });

  describe("class prop", () => {
    it("merges additional class into div className", () => {
      const { getByTestId } = render(
        <Card class="my-layout-class" data-testid="c">content</Card>
      );
      expect(getByTestId("c").className).toMatch(/my-layout-class/);
    });

    it("merges custom class alongside variant class", () => {
      const { getByTestId } = render(
        <Card variant="compact" class="stretch" data-testid="c">content</Card>
      );
      const className = getByTestId("c").className;
      expect(className).toMatch(/compact/);
      expect(className).toMatch(/stretch/);
    });
  });

  describe("containerRef prop", () => {
    it("applies containerRef to the root div element", () => {
      let capturedRef: preact.RefObject<HTMLDivElement> | null = null;

      function TestWrapper() {
        const ref = useRef<HTMLDivElement>(null);
        capturedRef = ref;
        return (
          <Card containerRef={ref} data-testid="c">content</Card>
        );
      }

      const { getByTestId } = render(<TestWrapper />);
      const el = getByTestId("c");
      // The ref should point to the rendered div
      expect(capturedRef!.current).toBe(el);
    });

    it("containerRef is optional and omitting it does not throw", () => {
      expect(() => {
        render(<Card data-testid="c">content</Card>);
      }).not.toThrow();
    });
  });

  describe("pass-through attributes", () => {
    it("passes data-testid through to the div element", () => {
      const { getByTestId } = render(
        <Card data-testid="my-card">content</Card>
      );
      expect(getByTestId("my-card")).not.toBeNull();
    });

    it("passes style through to the div element", () => {
      const { getByTestId } = render(
        <Card style="color: red;" data-testid="c">content</Card>
      );
      expect(getByTestId("c").getAttribute("style")).toBe("color: red;");
    });
  });

  describe("children", () => {
    it("renders children inside the div", () => {
      const { getByTestId } = render(
        <Card data-testid="c">
          <span data-testid="child">hello</span>
        </Card>
      );
      expect(getByTestId("c").querySelector("[data-testid='child']")).not.toBeNull();
    });
  });
});

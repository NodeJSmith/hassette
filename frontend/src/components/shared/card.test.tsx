import { render } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it } from "vitest";

import { Card } from "@/components/ui/card";

describe("Card", () => {
  describe("renders as div", () => {
    it("renders a <div> element", () => {
      const { getByTestId } = render(<Card data-testid="c">content</Card>);
      expect(getByTestId("c").tagName.toLowerCase()).toBe("div");
    });
  });

  describe("variant prop", () => {
    it("applies base card styling when variant='default'", () => {
      const { getByTestId } = render(
        <Card variant="default" data-testid="c">
          content
        </Card>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("default");
    });

    it("applies compact styling when variant='compact'", () => {
      const { getByTestId } = render(
        <Card variant="compact" data-testid="c">
          content
        </Card>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("compact");
      expect(getByTestId("c").className).toMatch(/p-3/);
    });

    it("applies config styling when variant='config'", () => {
      const { getByTestId } = render(
        <Card variant="config" data-testid="c">
          content
        </Card>,
      );
      expect(getByTestId("c").className).toMatch(/overflow-hidden/);
      expect(getByTestId("c").className).toMatch(/p-0/);
    });

    it("applies error styling when variant='error'", () => {
      const { getByTestId } = render(
        <Card variant="error" data-testid="c">
          content
        </Card>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("error");
      expect(getByTestId("c").className).toMatch(/text-center/);
    });

    it("uses default variant when no variant is provided", () => {
      const { getByTestId } = render(<Card data-testid="c">content</Card>);
      expect(getByTestId("c").getAttribute("data-variant")).toBe("default");
    });
  });

  describe("class prop", () => {
    it("merges additional class into div className", () => {
      const { getByTestId } = render(
        <Card className="my-layout-class" data-testid="c">
          content
        </Card>,
      );
      expect(getByTestId("c").className).toMatch(/my-layout-class/);
    });
  });

  describe("ref", () => {
    it("forwards ref to the root div element", () => {
      const ref = createRef<HTMLDivElement>();
      const { getByTestId } = render(
        <Card ref={ref} data-testid="c">
          content
        </Card>,
      );
      expect(ref.current).toBe(getByTestId("c"));
    });
  });

  describe("pass-through attributes", () => {
    it("passes data-testid through to the div element", () => {
      const { getByTestId } = render(<Card data-testid="my-card">content</Card>);
      expect(getByTestId("my-card")).not.toBeNull();
    });

    it("passes style through to the div element", () => {
      const { getByTestId } = render(
        <Card style={{ color: "red" }} data-testid="c">
          content
        </Card>,
      );
      expect(getByTestId("c").getAttribute("style")).toBe("color: red;");
    });
  });

  describe("children", () => {
    it("renders children inside the div", () => {
      const { getByTestId } = render(
        <Card data-testid="c">
          <span data-testid="child">hello</span>
        </Card>,
      );
      expect(getByTestId("c").querySelector("[data-testid='child']")).not.toBeNull();
    });
  });
});

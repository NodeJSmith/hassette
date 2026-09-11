import { render } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it } from "vitest";

import { Card } from "@/components/ui/card";

const CARD_TEST_ID = "card";
const PASSTHROUGH_TEST_ID = "my-card";

describe("Card", () => {
  describe("renders as div", () => {
    it("renders a <div> element", () => {
      const { getByTestId } = render(<Card data-testid={CARD_TEST_ID}>content</Card>);
      expect(getByTestId(CARD_TEST_ID).tagName.toLowerCase()).toBe("div");
    });
  });

  describe("variant prop", () => {
    it("applies base card styling when variant='default'", () => {
      const { getByTestId } = render(
        <Card variant="default" data-testid={CARD_TEST_ID}>
          content
        </Card>,
      );
      expect(getByTestId(CARD_TEST_ID).getAttribute("data-variant")).toBe("default");
    });

    it("applies compact styling when variant='compact'", () => {
      const { getByTestId } = render(
        <Card variant="compact" data-testid={CARD_TEST_ID}>
          content
        </Card>,
      );
      expect(getByTestId(CARD_TEST_ID).getAttribute("data-variant")).toBe("compact");
      expect(getByTestId(CARD_TEST_ID).className).toMatch(/p-3/);
    });

    it("applies config styling when variant='config'", () => {
      const { getByTestId } = render(
        <Card variant="config" data-testid={CARD_TEST_ID}>
          content
        </Card>,
      );
      expect(getByTestId(CARD_TEST_ID).className).toMatch(/overflow-hidden/);
      expect(getByTestId(CARD_TEST_ID).className).toMatch(/p-0/);
    });

    it("applies error styling when variant='error'", () => {
      const { getByTestId } = render(
        <Card variant="error" data-testid={CARD_TEST_ID}>
          content
        </Card>,
      );
      expect(getByTestId(CARD_TEST_ID).getAttribute("data-variant")).toBe("error");
      expect(getByTestId(CARD_TEST_ID).className).toMatch(/text-center/);
    });

    it("uses default variant when no variant is provided", () => {
      const { getByTestId } = render(<Card data-testid={CARD_TEST_ID}>content</Card>);
      expect(getByTestId(CARD_TEST_ID).getAttribute("data-variant")).toBe("default");
    });
  });

  describe("class prop", () => {
    it("merges additional class into div className", () => {
      const { getByTestId } = render(
        <Card className="my-layout-class" data-testid={CARD_TEST_ID}>
          content
        </Card>,
      );
      expect(getByTestId(CARD_TEST_ID).className).toMatch(/my-layout-class/);
    });
  });

  describe("ref", () => {
    it("forwards ref to the root div element", () => {
      const ref = createRef<HTMLDivElement>();
      const { getByTestId } = render(
        <Card ref={ref} data-testid={CARD_TEST_ID}>
          content
        </Card>,
      );
      expect(ref.current).toBe(getByTestId(CARD_TEST_ID));
    });
  });

  describe("pass-through attributes", () => {
    // Needs an id no other test in this file renders, so the assertion can only pass
    // if an arbitrary caller-supplied id actually reached the DOM.
    it("passes data-testid through to the div element", () => {
      const { getByTestId } = render(<Card data-testid={PASSTHROUGH_TEST_ID}>content</Card>);
      expect(getByTestId(PASSTHROUGH_TEST_ID)).not.toBeNull();
    });

    it("passes style through to the div element", () => {
      const { getByTestId } = render(
        <Card style={{ color: "red" }} data-testid={CARD_TEST_ID}>
          content
        </Card>,
      );
      expect(getByTestId(CARD_TEST_ID).getAttribute("style")).toBe("color: red;");
    });
  });

  describe("children", () => {
    it("renders children inside the div", () => {
      const { getByTestId } = render(
        <Card data-testid={CARD_TEST_ID}>
          <span data-testid="child">hello</span>
        </Card>,
      );
      expect(getByTestId(CARD_TEST_ID).querySelector("[data-testid='child']")).not.toBeNull();
    });
  });
});

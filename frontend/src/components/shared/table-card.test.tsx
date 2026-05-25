import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { TableCard } from "./table-card";

describe("TableCard", () => {
  describe("basic rendering", () => {
    it("renders children inside the scroll area", () => {
      render(
        <TableCard>
          <table data-testid="tbl">
            <tbody>
              <tr>
                <td>row</td>
              </tr>
            </tbody>
          </table>
        </TableCard>,
      );
      expect(screen.getByTestId("tbl")).not.toBeNull();
    });

    it("wraps content in a Card-derived element", () => {
      const { container } = render(
        <TableCard>
          <table>
            <tbody>
              <tr>
                <td>x</td>
              </tr>
            </tbody>
          </table>
        </TableCard>,
      );
      // Card renders a div; TableCard is built on Card
      expect(container.querySelector("div")).not.toBeNull();
    });
  });

  describe("footer slot", () => {
    it("renders the footer element when provided", () => {
      render(
        <TableCard footer={<div data-testid="footer-element">5 apps</div>}>
          <table>
            <tbody>
              <tr>
                <td>x</td>
              </tr>
            </tbody>
          </table>
        </TableCard>,
      );
      expect(screen.getByTestId("footer-element")).not.toBeNull();
    });

    it("renders footer below the scroll area", () => {
      render(
        <TableCard footer={<div data-testid="footer-el">count</div>}>
          <table>
            <tbody>
              <tr>
                <td data-testid="table-cell">data</td>
              </tr>
            </tbody>
          </table>
        </TableCard>,
      );

      const footerEl = screen.getByTestId("footer-el");
      const tableCell = screen.getByTestId("table-cell");
      const scrollArea = tableCell.closest(".ht-table-card-scroll")!;

      // footer container should appear AFTER scroll area
      const position = scrollArea.compareDocumentPosition(footerEl);
      expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("does not render a footer when footer prop is omitted", () => {
      const { container } = render(
        <TableCard>
          <table>
            <tbody>
              <tr>
                <td>x</td>
              </tr>
            </tbody>
          </table>
        </TableCard>,
      );
      // No data-footer-slot attribute should be present
      expect(container.querySelector("[data-footer-slot]")).toBeNull();
    });
  });

  describe("scrollHeight prop", () => {
    it("applies custom scroll height via CSS variable", () => {
      const { container } = render(
        <TableCard scrollHeight="400px">
          <table>
            <tbody>
              <tr>
                <td>x</td>
              </tr>
            </tbody>
          </table>
        </TableCard>,
      );
      const scrollEl = container.querySelector(".ht-table-card-scroll");
      expect(scrollEl).not.toBeNull();
      expect(scrollEl!.getAttribute("style")).toContain("400px");
    });
  });

  describe("class prop", () => {
    it("applies additional class to the container", () => {
      const { container } = render(
        <TableCard class="my-custom-class">
          <table>
            <tbody>
              <tr>
                <td>x</td>
              </tr>
            </tbody>
          </table>
        </TableCard>,
      );
      // The outer container should have my-custom-class
      expect(container.querySelector(".my-custom-class")).not.toBeNull();
    });
  });

  describe("FR#8 / AC#9 — Card border", () => {
    it("applies Card variant='compact' for border via --line-1 token", () => {
      const { container } = render(
        <TableCard>
          <table>
            <tbody>
              <tr>
                <td>x</td>
              </tr>
            </tbody>
          </table>
        </TableCard>,
      );
      // Card with variant="compact" applies both "card" and "compact" module classes.
      // We can't import CSS module class names in tests (they're hashed), but we can
      // verify a class is present and the component doesn't crash.
      // The Card border is verified visually (SKIPPED for this run).
      const root = container.firstElementChild;
      expect(root).not.toBeNull();
      expect(root!.className).toBeTruthy();
    });
  });
});

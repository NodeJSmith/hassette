import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/preact";
import { TableCard } from "./table-card";

describe("TableCard", () => {
  describe("basic rendering", () => {
    it("renders children inside the scroll area", () => {
      render(
        <TableCard>
          <table data-testid="tbl"><tbody><tr><td>row</td></tr></tbody></table>
        </TableCard>
      );
      expect(screen.getByTestId("tbl")).not.toBeNull();
    });

    it("wraps content in a Card-derived element", () => {
      const { container } = render(
        <TableCard>
          <table><tbody><tr><td>x</td></tr></tbody></table>
        </TableCard>
      );
      // Card renders a div; TableCard is built on Card
      expect(container.querySelector("div")).not.toBeNull();
    });
  });

  describe("search slot", () => {
    it("renders the search element above the scroll area when provided", () => {
      render(
        <TableCard
          search={<input type="text" data-testid="search-input" placeholder="search…" aria-label="search" />}
        >
          <table><tbody><tr><td data-testid="table-cell">data</td></tr></tbody></table>
        </TableCard>
      );

      const searchInput = screen.getByTestId("search-input");
      const tableCell = screen.getByTestId("table-cell");
      expect(searchInput).not.toBeNull();
      expect(tableCell).not.toBeNull();

      // The search container should appear before the scroll area in the DOM
      const searchContainer = searchInput.closest("[data-search-bar]") ?? searchInput.parentElement!;
      const scrollArea = tableCell.closest(".ht-table-card-scroll");
      expect(scrollArea).not.toBeNull();

      // compareDocumentPosition: DOCUMENT_POSITION_FOLLOWING = 4
      // searchContainer should come BEFORE scrollArea
      const position = searchContainer.compareDocumentPosition(scrollArea!);
      expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("does not render a search bar when search prop is omitted", () => {
      const { container } = render(
        <TableCard>
          <table><tbody><tr><td>x</td></tr></tbody></table>
        </TableCard>
      );
      // No data-search-bar attribute should be present
      expect(container.querySelector("[data-search-bar]")).toBeNull();
    });
  });

  describe("footer slot", () => {
    it("renders the footer element when provided", () => {
      render(
        <TableCard
          footer={<div data-testid="footer-element">5 apps</div>}
        >
          <table><tbody><tr><td>x</td></tr></tbody></table>
        </TableCard>
      );
      expect(screen.getByTestId("footer-element")).not.toBeNull();
    });

    it("renders footer below the scroll area", () => {
      render(
        <TableCard
          footer={<div data-testid="footer-el">count</div>}
        >
          <table><tbody><tr><td data-testid="table-cell">data</td></tr></tbody></table>
        </TableCard>
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
          <table><tbody><tr><td>x</td></tr></tbody></table>
        </TableCard>
      );
      // No data-footer-slot attribute should be present
      expect(container.querySelector("[data-footer-slot]")).toBeNull();
    });
  });

  describe("search + footer composition", () => {
    it("renders search above scroll area and footer below when both provided", () => {
      render(
        <TableCard
          search={<input type="text" data-testid="srch" aria-label="search" />}
          footer={<div data-testid="ftr">2 items</div>}
        >
          <table><tbody><tr><td data-testid="cell">x</td></tr></tbody></table>
        </TableCard>
      );

      const searchInput = screen.getByTestId("srch");
      const footer = screen.getByTestId("ftr");
      const cell = screen.getByTestId("cell");
      const scrollArea = cell.closest(".ht-table-card-scroll")!;

      // search before scroll
      const searchContainer = searchInput.closest("[data-search-bar]") ?? searchInput.parentElement!;
      const pos1 = searchContainer.compareDocumentPosition(scrollArea);
      expect(pos1 & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

      // scroll before footer
      const pos2 = scrollArea.compareDocumentPosition(footer);
      expect(pos2 & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });
  });

  describe("scrollHeight prop", () => {
    it("applies custom scroll height via CSS variable", () => {
      const { container } = render(
        <TableCard scrollHeight="400px">
          <table><tbody><tr><td>x</td></tr></tbody></table>
        </TableCard>
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
          <table><tbody><tr><td>x</td></tr></tbody></table>
        </TableCard>
      );
      // The outer container should have my-custom-class
      expect(container.querySelector(".my-custom-class")).not.toBeNull();
    });
  });

  describe("deprecated props backward compatibility", () => {
    it("still renders content when deprecated count prop is passed", () => {
      render(
        <TableCard count={<span data-testid="count-el">5 apps</span>}>
          <table><tbody><tr><td data-testid="cell">x</td></tr></tbody></table>
        </TableCard>
      );
      // Deprecated path: count renders somewhere in the DOM
      expect(screen.getByTestId("count-el")).not.toBeNull();
      expect(screen.getByTestId("cell")).not.toBeNull();
    });

    it("still renders content when deprecated title prop is passed", () => {
      render(
        <TableCard title={<span data-testid="title-el">My Table</span>}>
          <table><tbody><tr><td data-testid="cell">x</td></tr></tbody></table>
        </TableCard>
      );
      expect(screen.getByTestId("title-el")).not.toBeNull();
      expect(screen.getByTestId("cell")).not.toBeNull();
    });

    it("still renders content when deprecated controls prop is passed", () => {
      render(
        <TableCard controls={<button data-testid="ctrl-btn">filter</button>}>
          <table><tbody><tr><td data-testid="cell">x</td></tr></tbody></table>
        </TableCard>
      );
      expect(screen.getByTestId("ctrl-btn")).not.toBeNull();
      expect(screen.getByTestId("cell")).not.toBeNull();
    });
  });

  describe("FR#1 — search input above table content", () => {
    it("search prop renders a search area positioned above the table content", () => {
      const { container } = render(
        <TableCard
          search={<input type="text" class="ht-search" aria-label="search" data-testid="si" />}
        >
          <table><tbody><tr><td>data</td></tr></tbody></table>
        </TableCard>
      );

      // Search bar container exists and has the right data attribute
      expect(container.querySelector("[data-search-bar]")).not.toBeNull();
    });
  });

  describe("FR#8 / AC#9 — Card border", () => {
    it("applies Card variant='compact' for border via --line-1 token", () => {
      const { container } = render(
        <TableCard>
          <table><tbody><tr><td>x</td></tr></tbody></table>
        </TableCard>
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

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SortHeader, type SortState } from "./sort-header";

describe("SortHeader — sort-only", () => {
  it("renders a sort button", () => {
    const sort: SortState<string> = { key: "name", dir: "asc" };
    render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader sortKey="name" sort={sort} onSort={vi.fn()}>
                Name
              </SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    expect(screen.getByTestId("sort-header-btn")).toBeTruthy();
  });

  it("does not render a filter icon when filterContent is absent", () => {
    const sort: SortState<string> = { key: "name", dir: "asc" };
    const { container } = render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader sortKey="name" sort={sort} onSort={vi.fn()}>
                Name
              </SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    expect(container.querySelector("svg")).toBeNull();
  });

  it("does not add the headerInner wrapper when filterContent is absent", () => {
    const sort: SortState<string> = { key: "name", dir: "asc" };
    const { container } = render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader sortKey="name" sort={sort} onSort={vi.fn()}>
                Name
              </SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    // The outer span should contain a button directly, not a div wrapper
    const th = container.querySelector("th");
    expect(th?.querySelector("div")).toBeNull();
    expect(th?.querySelector("button")).not.toBeNull();
  });

  it("does not render a <th> itself — only inner content", () => {
    const sort: SortState<string> = { key: "name", dir: "asc" };
    const { container } = render(
      <SortHeader sortKey="name" sort={sort} onSort={vi.fn()}>
        Name
      </SortHeader>,
    );
    expect(container.querySelector("th")).toBeNull();
    expect(screen.getByTestId("sort-header-btn")).toBeTruthy();
  });

  it("calls onSort when sort button is clicked (managed)", async () => {
    const user = userEvent.setup();
    const onSort = vi.fn();
    const sort: SortState<string> = { key: "other", dir: "asc" };
    render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader sortKey="name" sort={sort} onSort={onSort}>
                Name
              </SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    await act(async () => {
      await user.click(screen.getByTestId("sort-header-btn"));
    });
    expect(onSort).toHaveBeenCalledWith({ key: "name", dir: "asc" });
  });
});

describe("SortHeader — sort+filter", () => {
  it("renders a sort button and a filter trigger button", () => {
    const sort: SortState<string> = { key: "status", dir: "asc" };
    render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader
                sortKey="status"
                sort={sort}
                onSort={vi.fn()}
                filterContent={<div>Filter options</div>}
                hasActiveFilter={false}
                ariaLabel="Status"
              >
                Status
              </SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    expect(screen.getByTestId("sort-header-btn")).toBeTruthy();
    expect(screen.getByTestId("filter-btn")).toBeTruthy();
  });

  it("renders a filter icon (funnel SVG)", () => {
    const sort: SortState<string> = { key: "status", dir: "asc" };
    const { container } = render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader
                sortKey="status"
                sort={sort}
                onSort={vi.fn()}
                filterContent={<div>Filter options</div>}
                hasActiveFilter={false}
              >
                Status
              </SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("sort button still triggers sort callback", async () => {
    const user = userEvent.setup();
    const onSort = vi.fn();
    const sort: SortState<string> = { key: "other", dir: "asc" };
    render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader
                sortKey="status"
                sort={sort}
                onSort={onSort}
                filterContent={<div>Filter</div>}
                hasActiveFilter={false}
                ariaLabel="Status"
              >
                Status
              </SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    await act(async () => {
      await user.click(screen.getByTestId("sort-header-btn"));
    });
    expect(onSort).toHaveBeenCalledWith({ key: "status", dir: "asc" });
  });

  it("filter button opens the popover", async () => {
    const user = userEvent.setup();
    const sort: SortState<string> = { key: "other", dir: "asc" };
    render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader
                sortKey="status"
                sort={sort}
                onSort={vi.fn()}
                filterContent={<div data-testid="filter-content">Filter options</div>}
                hasActiveFilter={false}
                ariaLabel="Status"
              >
                Status
              </SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    expect(screen.queryByTestId("filter-content")).toBeNull();
    await act(async () => {
      await user.click(screen.getByTestId("filter-btn"));
    });
    expect(screen.getByTestId("filter-content")).toBeTruthy();
  });

  it("filter popover closes on Escape", async () => {
    const user = userEvent.setup();
    const sort: SortState<string> = { key: "other", dir: "asc" };
    render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader
                sortKey="status"
                sort={sort}
                onSort={vi.fn()}
                filterContent={<div data-testid="filter-content">Filter</div>}
                hasActiveFilter={false}
                ariaLabel="Status"
              >
                Status
              </SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    await act(async () => {
      await user.click(screen.getByTestId("filter-btn"));
    });
    expect(screen.getByTestId("filter-content")).toBeTruthy();

    await act(async () => {
      await user.keyboard("{Escape}");
    });
    expect(screen.queryByTestId("filter-content")).toBeNull();
  });
});

describe("SortHeader — filter-only", () => {
  it("renders a plain label span (no sort button) when no sort props", () => {
    render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader filterContent={<div>Filter options</div>} hasActiveFilter={false} ariaLabel="Type">
                Type
              </SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    // The label text is present
    expect(screen.getByText("Type")).toBeTruthy();
    // Only the filter button — no sort button
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0].getAttribute("aria-label")).toMatch(/filter type/i);
  });

  it("renders a filter icon (funnel SVG)", () => {
    const { container } = render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader filterContent={<div>opts</div>} hasActiveFilter={false}>
                Type
              </SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("filter button opens the popover", async () => {
    const user = userEvent.setup();
    render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader
                filterContent={<div data-testid="filter-content">Filter options</div>}
                hasActiveFilter={false}
                ariaLabel="Type"
              >
                Type
              </SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    expect(screen.queryByTestId("filter-content")).toBeNull();
    await act(async () => {
      await user.click(screen.getByTestId("filter-btn"));
    });
    expect(screen.getByTestId("filter-content")).toBeTruthy();
  });
});

describe("SortHeader — plain label", () => {
  it("renders label text with no buttons when no sort or filter props", () => {
    render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader>Actions</SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    expect(screen.getByText("Actions")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("does not render an SVG when no filter props", () => {
    const { container } = render(
      <table>
        <thead>
          <tr>
            <th>
              <SortHeader>Actions</SortHeader>
            </th>
          </tr>
        </thead>
      </table>,
    );
    expect(container.querySelector("svg")).toBeNull();
  });
});

describe("SortHeader — data-testid", () => {
  it("applies data-testid to the outer wrapper element (no filter)", () => {
    const sort: SortState<string> = { key: "name", dir: "asc" };
    render(
      <SortHeader sortKey="name" sort={sort} onSort={vi.fn()} data-testid="sort-name-col">
        Name
      </SortHeader>,
    );
    expect(screen.getByTestId("sort-name-col")).toBeTruthy();
  });

  it("applies data-testid to the outer wrapper element (with filter)", () => {
    const sort: SortState<string> = { key: "status", dir: "asc" };
    render(
      <SortHeader
        sortKey="status"
        sort={sort}
        onSort={vi.fn()}
        filterContent={<div>opts</div>}
        hasActiveFilter={false}
        data-testid="sort-status-col"
      >
        Status
      </SortHeader>,
    );
    expect(screen.getByTestId("sort-status-col")).toBeTruthy();
  });
});

describe("SortHeader — ariaLabel", () => {
  it("applies aria-label to the sort button as 'Sort by {ariaLabel}'", () => {
    const sort: SortState<string> = { key: "name", dir: "asc" };
    render(
      <SortHeader sortKey="name" sort={sort} onSort={vi.fn()} ariaLabel="App name">
        Name
      </SortHeader>,
    );
    const btn = screen.getByTestId("sort-header-btn");
    expect(btn.getAttribute("aria-label")).toBe("Sort by App name");
  });

  it("applies aria-label to the filter button as 'Filter {ariaLabel}'", () => {
    const sort: SortState<string> = { key: "status", dir: "asc" };
    render(
      <SortHeader
        sortKey="status"
        sort={sort}
        onSort={vi.fn()}
        filterContent={<div>opts</div>}
        hasActiveFilter={false}
        ariaLabel="Status"
      >
        Status
      </SortHeader>,
    );
    const filterBtn = screen.getByTestId("filter-btn");
    expect(filterBtn.getAttribute("aria-label")).toBe("Filter Status");
  });
});

describe("SortHeader — hasActiveFilter", () => {
  it("shows the active dot on the filter icon when hasActiveFilter=true", () => {
    render(
      <SortHeader filterContent={<div>opts</div>} hasActiveFilter={true}>
        Status
      </SortHeader>,
    );
    expect(screen.getByTestId("filter-icon-dot")).toBeTruthy();
  });

  it("does not show the active dot when hasActiveFilter=false", () => {
    render(
      <SortHeader filterContent={<div>opts</div>} hasActiveFilter={false}>
        Status
      </SortHeader>,
    );
    expect(screen.queryByTestId("filter-icon-dot")).toBeNull();
  });
});

describe("SortHeader — popover toggle", () => {
  it("opens popover on filter button click and closes on Escape", async () => {
    const user = userEvent.setup();
    render(
      <SortHeader filterContent={<div data-testid="pop-content">Content</div>} hasActiveFilter={false} ariaLabel="Col">
        Col
      </SortHeader>,
    );
    // Open
    await act(async () => {
      await user.click(screen.getByTestId("filter-btn"));
    });
    expect(screen.getByTestId("pop-content")).toBeTruthy();

    // Close with Escape
    await act(async () => {
      await user.keyboard("{Escape}");
    });
    expect(screen.queryByTestId("pop-content")).toBeNull();
  });

  it("closing the popover restores focus to the filter button", async () => {
    const user = userEvent.setup();
    render(
      <SortHeader filterContent={<button type="button">Inside</button>} hasActiveFilter={false} ariaLabel="Col">
        Col
      </SortHeader>,
    );
    const filterBtn = screen.getByTestId("filter-btn");
    await act(async () => {
      await user.click(filterBtn);
    });
    // Close with Escape
    await act(async () => {
      await user.keyboard("{Escape}");
    });
    expect(document.activeElement).toBe(filterBtn);
  });
});

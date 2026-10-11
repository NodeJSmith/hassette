import { describe, expect, it } from "vitest";

/** Every non-test component source under `src`, by path. */
const SOURCES = import.meta.glob<string>(["../**/*.tsx", "!../**/*.test.tsx"], {
  query: "?raw",
  import: "default",
  eager: true,
});

/** An `href` opening with `#`: a quoted attribute, or a string or template literal in braces. */
const IN_PAGE_HREF = /href=(?:["']#|\{\s*[`"']#)/g;

/** The JSX opening tag around `index`: back to its `<`, forward to the first `>` outside braces. */
function openingTagAt(source: string, index: number): string {
  const start = source.lastIndexOf("<", index);
  let depth = 0;
  for (let i = index; i < source.length; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}") depth--;
    else if (source[i] === ">" && depth === 0) return source.slice(start, i + 1);
  }
  return source.slice(start);
}

/** Each in-page anchor in `source` that lacks an `onClick`, or whose file never builds one with the helper. */
function unhandledAnchors(source: string): string[] {
  const tags = [...source.matchAll(IN_PAGE_HREF)].map((m) => openingTagAt(source, m.index));
  const usesHelper = source.includes("focusInPageTarget(");
  return tags.filter((tag) => !usesHelper || !tag.includes("onClick="));
}

describe("unhandledAnchors", () => {
  it("accepts an anchor with an onClick in a file that uses the helper", () => {
    const source = "const go = focusInPageTarget(ID);\n<a href={`#${ID}`} onClick={go} className={x}>Skip</a>";
    expect(unhandledAnchors(source)).toEqual([]);
  });

  it.each(['<a href="#top">Top</a>', "<a href='#top'>Top</a>", '<a href={"#top"}>Top</a>'])(
    "flags a bare %s even when another anchor in the file is handled",
    (bare) => {
      const source = `const go = focusInPageTarget(ID);\n<a href="#main" onClick={go}>Skip</a>\n${bare}`;
      expect(unhandledAnchors(source)).toHaveLength(1);
    },
  );
});

describe("in-page anchors", () => {
  it("finds the component sources", () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(10);
  });

  it("routes every `#id` href through an onClick built with focusInPageTarget", () => {
    const offenders = Object.entries(SOURCES).flatMap(([path, source]) =>
      unhandledAnchors(source).map((tag) => `${path}: ${tag}`),
    );
    expect(offenders).toEqual([]);
  });
});

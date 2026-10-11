import { describe, expect, it } from "vitest";

import { findAbsolutePaths } from "./no-absolute-paths";

describe("findAbsolutePaths", () => {
  it.each([
    ['fetch("/api/apps")', '"/api/apps'],
    ["const p = '/api';", "'/api"],
    ["`/api/ws`", "`/api/ws"],
    ['src: url("/fonts/geist.woff2")', 'url("/fonts'],
    ["src:url(/fonts/geist.woff2)", "url(/fonts"],
    ['<script src="/assets/index.js">', '"/assets'],
  ])("flags %s", (source, start) => {
    const hits = findAbsolutePaths(source);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatch(new RegExp(`^${start.replace(/[(/]/g, "\\$&")}`));
  });

  it.each([
    'fetch("api/apps")',
    "url(./fonts/geist.woff2)",
    'src="./assets/index.js"',
    'href="/hassette-logo.png"',
    '"/apps/foo"',
    "// see /api/ws in the docs",
    '"/apis"',
  ])("ignores %s", (source) => {
    expect(findAbsolutePaths(source)).toEqual([]);
  });
});

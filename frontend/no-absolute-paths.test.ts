import { describe, expect, it } from "vitest";

import { BASE_MARKER, findAbsolutePaths, findBundleProblems } from "./no-absolute-paths";

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

describe("findBundleProblems", () => {
  const index = `<head>${BASE_MARKER}</head>`;

  it("passes a bundle whose index.html keeps the marker and has no absolute paths", () => {
    expect(findBundleProblems({ "index.html": index, "assets/app.js": 'fetch("api/apps")' })).toEqual([]);
  });

  it.each(['<base href="/">', "<base href='/' />", '<base  href="/" />'])(
    "flags an index.html whose marker was rewritten to %s",
    (tag) => {
      const problems = findBundleProblems({ "index.html": `<head>${tag}</head>` });
      expect(problems).toHaveLength(1);
      expect(problems[0]).toContain(BASE_MARKER);
    },
  );

  it("names the file of each absolute path", () => {
    const problems = findBundleProblems({ "index.html": index, "assets/app.js": 'fetch("/api/apps")' });
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain('assets/app.js: "/api/apps');
  });
});

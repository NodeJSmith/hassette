import type { Plugin } from "vite";

/**
 * The URL prefixes the backend serves the app under: the API, built assets (fonts included), and the
 * pre-relative-base `/fonts` mount. Only these are checked; an absolute route path like `"/apps"` is a
 * router path, resolved against `<Router base>`, and is fine.
 */
const SERVED_PREFIXES = ["api", "fonts", "assets"];

/**
 * A served prefix as an absolute path opening a quoted or backtick string, or a CSS `url(`.
 *
 * Such a path in the shipped bundle resolves at the origin root, so it escapes the prefix the backend's
 * `<base href>` names (HA ingress, sub-path proxies) and breaks the UI there.
 */
const ABSOLUTE_PATH = new RegExp(`(?:["'\`]|url\\(\\s*["']?)/(?:${SERVED_PREFIXES.join("|")})\\b`, "g");

/** How much of the bundle to quote after each hit, so the build error shows where it is. */
const CONTEXT_CHARS = 40;

/** The absolute same-origin paths in `source`, each with a little context. */
export function findAbsolutePaths(source: string): string[] {
  return [...source.matchAll(ABSOLUTE_PATH)].map((m) => source.slice(m.index, m.index + CONTEXT_CHARS));
}

/**
 * The exact `<base>` tag the emitted `index.html` must keep. The backend substitutes it per request and
 * serves no UI when it's missing; `BASE_MARKER` in `src/hassette/web/spa.py` is the other half of this
 * contract, and the two must match byte for byte.
 */
export const BASE_MARKER = '<base href="/" />';

/**
 * Build errors for the emitted files (path to text): absolute served paths, and an `index.html` that is missing
 * or lost its `<base>` marker (the backend serves no UI without one).
 */
export function findBundleProblems(files: Record<string, string>): string[] {
  const offenders: string[] = [];
  for (const [fileName, source] of Object.entries(files)) {
    for (const hit of findAbsolutePaths(source)) offenders.push(`  ${fileName}: ${hit}`);
  }
  const problems: string[] = [];
  if (offenders.length > 0) {
    problems.push(
      `Absolute ${SERVED_PREFIXES.map((p) => `/${p}`).join(", ")} paths in the build output; ` +
        "they escape the <base href> prefix. " +
        "Use an app-relative path resolved through src/lib/base-path.ts.\n" +
        offenders.join("\n"),
    );
  }
  const index = files["index.html"];
  if (index === undefined) {
    problems.push("The build emitted no index.html; the backend has no shell to serve.");
  } else if (!index.includes(BASE_MARKER)) {
    problems.push(
      `The built index.html lacks the exact ${BASE_MARKER} tag the backend substitutes; ` +
        "keep it verbatim in frontend/index.html (and check no HTML transform rewrites it).",
    );
  }
  return problems;
}

/**
 * Fails `vite build` when any emitted chunk or asset, vendor chunks included, contains an absolute path,
 * or the emitted `index.html` lost its `<base>` marker.
 */
export function noAbsolutePaths(): Plugin {
  return {
    name: "hassette-no-absolute-paths",
    apply: "build",
    // Post-enforced generateBundle sees the final bundle (the HTML plugin's index.html, Vite's CSS URL
    // rewrites) before anything is written, so a failing build leaves no output a freshness check could reuse.
    enforce: "post",
    generateBundle(_options, bundle) {
      const files: Record<string, string> = {};
      for (const [fileName, output] of Object.entries(bundle)) {
        const source = output.type === "chunk" ? output.code : output.source;
        if (typeof source === "string") files[fileName] = source;
      }
      const problems = findBundleProblems(files);
      if (problems.length > 0) this.error(problems.join("\n"));
    },
  };
}

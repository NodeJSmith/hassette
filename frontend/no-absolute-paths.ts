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

/** Fails `vite build` when any emitted chunk or asset, vendor chunks included, contains an absolute path. */
export function noAbsolutePaths(): Plugin {
  return {
    name: "hassette-no-absolute-paths",
    apply: "build",
    // writeBundle sees the final bundle, after the HTML plugin emits index.html and Vite's URL rewrites.
    writeBundle(_options, bundle) {
      const offenders: string[] = [];
      for (const [fileName, output] of Object.entries(bundle)) {
        const source = output.type === "chunk" ? output.code : output.source;
        if (typeof source !== "string") continue;
        for (const hit of findAbsolutePaths(source)) offenders.push(`  ${fileName}: ${hit}`);
      }
      if (offenders.length > 0) {
        this.error(
          `Absolute ${SERVED_PREFIXES.map((p) => `/${p}`).join(", ")} paths in the build output; ` +
            "they escape the <base href> prefix. " +
            "Use an app-relative path resolved through src/lib/base-path.ts.\n" +
            offenders.join("\n"),
        );
      }
    },
  };
}

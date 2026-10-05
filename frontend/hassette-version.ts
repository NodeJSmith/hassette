import { readFileSync } from "node:fs";
import path from "node:path";

/** A plain release version, the only form whose PEP 440 normalization (what the server reports via
 * importlib.metadata) is the string itself. */
const CANONICAL_RELEASE_VERSION = /^\d+\.\d+\.\d+$/;

/**
 * The `[project]` version from the root pyproject.toml. Release builds run after release-please
 * bumps it, so it matches what the installed server reports. The Dockerfile's frontend stage copies
 * pyproject.toml to the matching `../` path.
 */
export function readHassetteVersion(): string {
  const pyproject = readFileSync(path.resolve(import.meta.dirname, "../pyproject.toml"), "utf8");
  const project = /^\[project\]$([\s\S]*?)(?=^\[|(?![\s\S]))/m.exec(pyproject)?.[1] ?? "";
  const version = /^version = "([^"]+)"/m.exec(project)?.[1];
  if (!version) {
    throw new Error("Could not find [project] version in ../pyproject.toml");
  }
  // A non-canonical version (e.g. "1.0.0-rc.1") would differ from the server's normalized form on
  // every connect and leave tabs with a reload prompt that reloading never clears.
  if (!CANONICAL_RELEASE_VERSION.test(version)) {
    throw new Error(`pyproject.toml version "${version}" is not a plain X.Y.Z release version`);
  }
  return version;
}

/** The `define` entries shared by vite.config.ts and vitest.config.ts. */
export function hassetteDefines(): Record<string, string> {
  return { __HASSETTE_VERSION__: JSON.stringify(readHassetteVersion()) };
}

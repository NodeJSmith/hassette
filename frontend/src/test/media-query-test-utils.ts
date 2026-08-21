/**
 * Test utilities for `useMediaQuery` hook tests.
 *
 * `renderMediaQuery()` renders `useMediaQuery(BREAKPOINT_MOBILE)` — the shared shape every
 * `useMediaQuery` test starts with. The caller sets the file-local `currentMatches` variable the
 * installed `matchMedia` mock reads *before* calling this: that variable (and the mock itself) is
 * declared per test file in its own `beforeEach`, so it can't move into this shared helper.
 */

import { renderHook } from "@testing-library/react";

import { BREAKPOINT_MOBILE, useMediaQuery } from "../hooks/use-media-query";

/** Renders `useMediaQuery(BREAKPOINT_MOBILE)`. Set the file-local `currentMatches` mock state
 * before calling. */
export function renderMediaQuery() {
  return renderHook(() => useMediaQuery(BREAKPOINT_MOBILE));
}

/**
 * MSW server instance for use in tests that need per-test handler overrides.
 *
 * Import `server` from here (not from test-setup.ts) when you need
 * `server.use(...)` to override default handlers for a specific test.
 */

import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);

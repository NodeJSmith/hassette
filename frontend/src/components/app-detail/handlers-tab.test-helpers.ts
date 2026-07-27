import { createElement } from "react";

import { createJob, createListener } from "../../test/factories";
import { renderWithAppState } from "../../test/render-helpers";
import { HandlersTab } from "./handlers-tab";

/**
 * Renders HandlersTab with sensible listener/job defaults and a fixed uptimeSeconds.
 *
 * Uses `createElement()` instead of JSX because this file is `.ts` (not `.tsx`) — JSX syntax
 * requires a `.tsx` extension to compile under this project's esbuild config.
 */
export function renderHandlersTab(
  listeners = [createListener({ listener_id: 1 })],
  jobs = [createJob({ job_id: 10 })],
  selectedHandler: string | null = null,
) {
  return renderWithAppState(
    createElement(HandlersTab, { listeners, jobs, selectedHandler, selectedExecId: null, appKey: "test_app" }),
    { storeOverrides: { uptimeSeconds: 120 } },
  );
}

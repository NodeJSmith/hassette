import { http, HttpResponse } from "msw";

import type { AppManifest, JobData, ListenerData } from "../api/endpoints";
import { createInstance, createManifest } from "../test/factories";
import { server } from "../test/server";

/** Registers MSW handlers for the manifest/listeners/jobs endpoints AppDetailPage queries. */
export function setupApi(manifest: AppManifest, listeners: ListenerData[] = [], jobs: JobData[] = []) {
  server.use(
    http.get("/api/apps/:app_key/manifest", () => HttpResponse.json(manifest)),
    http.get("/api/telemetry/app/:app_key/listeners", () => HttpResponse.json(listeners)),
    http.get("/api/telemetry/app/:app_key/jobs", () => HttpResponse.json(jobs)),
  );
}

/** Registers a 2-instance manifest (no ?instance= param selected) for multi-instance parent-view tests. */
export function setupMultiInstanceParent() {
  const manifest = createManifest({
    instance_count: 2,
    instances: [
      createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
      createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
    ],
  });
  setupApi(manifest);
}

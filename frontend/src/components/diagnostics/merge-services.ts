import type { ResourceStatus } from "../../api/endpoints";
import type { components } from "../../api/generated-types";
import type { ServiceStatusEntry } from "../../state/store";

type ServiceInfo = components["schemas"]["ServiceInfo"];

export interface MergedService {
  resource_name: string;
  status: ResourceStatus;
  ready_phase: string | null;
  exception: string | null;
}

export function mergeServices(
  httpServices: ServiceInfo[],
  wsStatus: Record<string, ServiceStatusEntry>,
): MergedService[] {
  const merged = new Map<string, MergedService>();

  // Seed from HTTP
  for (const httpEntry of httpServices) {
    merged.set(httpEntry.name, {
      resource_name: httpEntry.name,
      status: httpEntry.status,
      ready_phase: httpEntry.ready_phase ?? null,
      exception: null,
    });
  }

  // Overlay with WS updates (live data wins)
  for (const [name, wsEntry] of Object.entries(wsStatus)) {
    merged.set(name, {
      resource_name: name,
      status: wsEntry.status,
      ready_phase: wsEntry.ready_phase ?? null,
      exception: wsEntry.exception ?? null,
    });
  }

  // Anomalies first, then alphabetical — a failed service should never hide below the fold.
  return [...merged.values()].sort((a, b) => {
    const anomalyFirst = Number(a.status === "running") - Number(b.status === "running");
    return anomalyFirst || a.resource_name.localeCompare(b.resource_name);
  });
}

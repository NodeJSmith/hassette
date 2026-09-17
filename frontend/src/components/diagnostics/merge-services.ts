import type { components } from "../../api/generated-types";
import type { ServiceStatusEntry } from "../../state/store";

type ServiceInfoResponse = components["schemas"]["ServiceInfoResponse"];
type ResourceStatus = components["schemas"]["ResourceStatus"];

export interface MergedService {
  resource_name: string;
  status: ResourceStatus;
  role: string;
  ready_phase: string | null;
  retry_at: number | null;
  exception: string | null;
}

export function mergeServices(
  httpServices: ServiceInfoResponse[],
  wsStatus: Record<string, ServiceStatusEntry>,
): MergedService[] {
  const merged = new Map<string, MergedService>();

  // Seed from HTTP
  for (const httpEntry of httpServices) {
    merged.set(httpEntry.name, {
      resource_name: httpEntry.name,
      status: httpEntry.status,
      role: httpEntry.role ?? "",
      ready_phase: httpEntry.ready_phase ?? null,
      retry_at: httpEntry.retry_at ?? null,
      exception: null,
    });
  }

  // Overlay with WS updates (live data wins)
  for (const [name, wsEntry] of Object.entries(wsStatus)) {
    merged.set(name, {
      resource_name: name,
      status: wsEntry.status,
      role: wsEntry.role ?? "",
      ready_phase: wsEntry.ready_phase ?? null,
      retry_at: wsEntry.retry_at ?? null,
      exception: wsEntry.exception ?? null,
    });
  }

  // Anomalies first, then alphabetical — a failed service should never hide below the fold.
  return [...merged.values()].sort((a, b) => {
    const anomalyFirst = Number(a.status === "running") - Number(b.status === "running");
    return anomalyFirst || a.resource_name.localeCompare(b.resource_name);
  });
}

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
  for (const svc of httpServices) {
    merged.set(svc.name, {
      resource_name: svc.name,
      status: svc.status,
      role: svc.role ?? "",
      ready_phase: svc.ready_phase ?? null,
      retry_at: svc.retry_at ?? null,
      exception: null,
    });
  }

  // Overlay with WS updates (live data wins)
  for (const [name, entry] of Object.entries(wsStatus)) {
    merged.set(name, {
      resource_name: name,
      status: entry.status,
      role: entry.role ?? "",
      ready_phase: entry.ready_phase ?? null,
      retry_at: entry.retry_at ?? null,
      exception: entry.exception ?? null,
    });
  }

  // Anomalies first, then alphabetical — a failed service should never hide below the fold.
  return [...merged.values()].sort((a, b) => {
    const anomalyFirst = Number(a.status === "running") - Number(b.status === "running");
    return anomalyFirst || a.resource_name.localeCompare(b.resource_name);
  });
}

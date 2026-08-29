import { EmptyState } from "../shared/empty-state";
import type { MergedService } from "./merge-services";
import { Panel } from "./panel";
import { ServiceRow } from "./service-row";

interface ServicesPanelProps {
  services: MergedService[];
  wsConnected: boolean;
}

export function ServicesPanel({ services, wsConnected }: ServicesPanelProps) {
  const staleChip = wsConnected ? null : (
    <span
      className="rounded-full border border-[var(--status-warning)] px-2 py-px font-mono text-xs uppercase tracking-[var(--text-label-tracking)] text-[var(--status-warning)]"
      data-testid="diag-services-stale"
    >
      stale
    </span>
  );

  return (
    <Panel title="services" ariaLabel="Internal services" headingAside={staleChip} data-testid="diag-services-panel">
      {services.length === 0 ? (
        <EmptyState title="no services registered." data-testid="diag-services-empty" />
      ) : (
        <ul
          className="grid list-none grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-x-5 gap-y-1 p-0"
          aria-label="Service list"
        >
          {services.map((svc) => (
            <ServiceRow key={svc.resource_name} service={svc} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

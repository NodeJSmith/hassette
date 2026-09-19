import { Badge } from "@/components/ui/badge";

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
    <Badge
      variant="kind-warn"
      size="sm"
      className="font-mono uppercase tracking-[var(--text-label-tracking)]"
      data-testid="diag-services-stale"
    >
      stale
    </Badge>
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
          {services.map((service) => (
            <ServiceRow key={service.resource_name} service={service} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

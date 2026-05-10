import { EmptyState } from "../shared/empty-state";
import type { ListenerData, JobData } from "../../api/endpoints";

interface Props {
  listeners: ListenerData[];
  jobs: JobData[];
  appKey: string;
  instanceQs: string;
}

export function OverviewTab({ listeners, jobs, appKey, instanceQs }: Props) {
  // Suppress unused variable warnings until T03/T04 fill in real content
  void appKey;
  void instanceQs;
  void listeners;
  void jobs;

  return (
    <div class="ht-overview-tab" data-testid="overview-tab">
      {/* Handler health grid — content added in T03 */}
      <section class="ht-overview-tab__section ht-mb-4" data-testid="overview-health-section">
        <EmptyState
          title="Handler health"
          body="Loading handler status…"
          data-testid="overview-health-placeholder"
        />
      </section>

      {/* Recent activity + logs — content added in T04 */}
      <section class="ht-overview-tab__section" data-testid="overview-activity-section">
        <EmptyState
          title="Recent activity"
          body="Loading recent activity…"
          data-testid="overview-activity-placeholder"
        />
      </section>
    </div>
  );
}

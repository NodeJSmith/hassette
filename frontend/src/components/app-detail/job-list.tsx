import type { JobData } from "../../api/endpoints";
import { JobRow } from "./job-row";

interface Props {
  jobs: JobData[] | null;
}

export function JobList({ jobs }: Props) {
  if (!jobs) return null;
  if (jobs.length === 0) {
    return <p class="ht-text-muted ht-text-xs">No scheduled jobs.</p>;
  }

  return (
    <div class="ht-item-list" data-testid="job-list">
      {jobs.map((j) => (
        <JobRow key={j.job_id} job={j} />
      ))}
    </div>
  );
}

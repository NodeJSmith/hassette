import type { JobData } from "../../api/endpoints";
import { JobRow } from "./job-row";

interface Props {
  jobs: JobData[] | null;
}

export function JobList({ jobs }: Props) {
  if (!jobs) return null;
  if (jobs.length === 0) return null;

  return (
    <div class="ht-item-list" data-testid="job-list">
      {jobs.map((j) => (
        <JobRow key={j.job_id} job={j} />
      ))}
    </div>
  );
}

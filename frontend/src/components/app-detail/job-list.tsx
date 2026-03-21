import { JobRow } from "./job-row";

interface Props {
  jobs: unknown[] | null;
}

export function JobList({ jobs }: Props) {
  if (!jobs) return null;
  if (jobs.length === 0) {
    return <p class="ht-text-muted ht-text-xs">No scheduled jobs.</p>;
  }

  return (
    <div class="ht-item-list">
      {(jobs as Array<Record<string, unknown>>).map((j) => (
        <JobRow key={j.job_id as number} job={j as never} />
      ))}
    </div>
  );
}

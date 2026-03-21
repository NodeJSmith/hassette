import { JobRow } from "./job-row";

interface Props {
  jobs: unknown[] | null;
}

export function JobList({ jobs }: Props) {
  if (!jobs) return null;
  if (jobs.length === 0) {
    return <p class="ht-text-secondary">No scheduled jobs.</p>;
  }

  return (
    <table class="ht-table">
      <thead>
        <tr>
          <th style={{ width: "24px" }} />
          <th>Job</th>
          <th>Executions</th>
          <th>Errors</th>
          <th>Avg Duration</th>
        </tr>
      </thead>
      <tbody>
        {(jobs as Array<Record<string, unknown>>).map((j) => (
          <JobRow key={j.job_id as number} job={j as never} />
        ))}
      </tbody>
    </table>
  );
}

import { signal } from "@preact/signals";
import { useEffect, useMemo, useRef } from "preact/hooks";
import { useSearch } from "wouter";
import type { JobData } from "../../api/endpoints";
import { JobRow } from "./job-row";

interface Props {
  jobs: JobData[] | null;
}

export function JobList({ jobs }: Props) {
  const searchString = useSearch();

  // Parse the initial group filter from the URL search param (only once on mount)
  const initialGroup = useRef<string | null>(null);
  if (initialGroup.current === null) {
    const params = new URLSearchParams(searchString);
    initialGroup.current = params.get("group");
  }

  // Local signal for active group filter; initialized from URL on first mount
  const activeGroup = useRef(signal<string | null>(initialGroup.current)).current;

  // Derive a stable identity from the jobs data so the filter only resets on
  // instance/session switches, not on WS reconnect refetches that produce a
  // new array reference with identical content.
  const jobsIdentity = useMemo(() => {
    const first = jobs?.[0];
    return first ? `${first.app_key}:${first.instance_index}` : null;
  }, [jobs]);

  // Track whether the component has mounted so we skip the initial effect run
  const isMounted = useRef(false);

  // Reset filter when the app/instance identity changes, but not on initial mount
  // or mere WS reconnect refetches that produce a new array reference
  useEffect(() => {
    if (!isMounted.current) {
      isMounted.current = true;
      return;
    }
    activeGroup.value = null;
    // Clear the URL param too
    const params = new URLSearchParams(window.location.search);
    params.delete("group");
    const newSearch = params.toString();
    history.replaceState(null, "", newSearch ? `?${newSearch}` : window.location.pathname);
  }, [jobsIdentity]);

  if (!jobs) return null;
  if (jobs.length === 0) return null;

  // Compute distinct non-null groups (preserving order of first occurrence)
  const groups = [
    ...new Set(
      jobs
        .filter((j) => j.group !== null && j.group !== undefined)
        .map((j) => j.group as string),
    ),
  ];

  const hasFilterBar = groups.length >= 2;

  const handleChipClick = (group: string | null) => {
    activeGroup.value = group;
    const params = new URLSearchParams(window.location.search);
    if (group !== null) {
      params.set("group", group);
    } else {
      params.delete("group");
    }
    const newSearch = params.toString();
    history.replaceState(null, "", newSearch ? `?${newSearch}` : window.location.pathname);
  };

  const handleGroupClick = (group: string) => {
    handleChipClick(group);
  };

  const filteredJobs =
    activeGroup.value !== null
      ? jobs.filter((j) => j.group === activeGroup.value)
      : jobs;

  return (
    <div>
      {hasFilterBar && (
        <div
          class="ht-group-filter-bar"
          data-testid="group-filter-bar"
          role="group"
          aria-label="Filter by group"
        >
          <button
            type="button"
            class={`ht-badge ht-badge--neutral ht-group-chip${activeGroup.value === null ? " ht-group-chip--active" : ""}`}
            aria-pressed={activeGroup.value === null}
            onClick={() => handleChipClick(null)}
          >
            All
          </button>
          {groups.map((group) => (
            <button
              key={group}
              type="button"
              class={`ht-badge ht-badge--neutral ht-group-chip${activeGroup.value === group ? " ht-group-chip--active" : ""}`}
              aria-pressed={activeGroup.value === group}
              onClick={() => handleChipClick(group)}
            >
              {group}
            </button>
          ))}
        </div>
      )}
      {activeGroup.value !== null && filteredJobs.length === 0 ? (
        <p class="ht-text-muted ht-text-sm" data-testid="no-filter-results">
          No jobs match this filter
        </p>
      ) : (
        <div class="ht-item-list" data-testid="job-list">
          {filteredJobs.map((j) => (
            <JobRow
              key={j.job_id}
              job={j}
              onGroupClick={hasFilterBar ? handleGroupClick : undefined}
            />
          ))}
        </div>
      )}
    </div>
  );
}

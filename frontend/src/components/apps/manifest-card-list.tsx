import type { Signal } from "@preact/signals";
import type { AppManifest } from "../../api/endpoints";
import { StatusBadge } from "../shared/status-badge";
import { ActionButtons } from "./action-buttons";
import { pluralize } from "../../utils/format";

interface AppStatusEntry {
  status: string;
  index: number;
}

interface Props {
  manifests: AppManifest[];
  expanded: Signal<Set<string>>;
  toggleExpand: (appKey: string) => void;
  appStatus: Signal<Record<string, AppStatusEntry>>;
}

export function ManifestCardList({ manifests, expanded, toggleExpand, appStatus }: Props) {
  const expandedValue = expanded.value;

  return (
    <div class="ht-manifest-card-list">
      {manifests.map((m) => {
        const status = appStatus.value[m.app_key]?.status ?? m.status;
        const isMultiInstance = m.instance_count > 1;
        const isExpanded = isMultiInstance && expandedValue.has(m.app_key);
        const expandLabel = isExpanded
          ? `Collapse instances for ${m.app_key}`
          : `Expand instances for ${m.app_key}`;

        return (
          <div key={m.app_key} class="ht-manifest-card" data-testid={`manifest-card-${m.app_key}`}>
            <div class="ht-manifest-card__header">
              <div class="ht-manifest-card__title">
                {isMultiInstance && (
                  <button
                    type="button"
                    class="ht-manifest-card__chevron"
                    onClick={() => toggleExpand(m.app_key)}
                    aria-label={expandLabel}
                    aria-expanded={isExpanded}
                    data-testid={`expand-toggle-${m.app_key}`}
                  >
                    {isExpanded ? "▾" : "▸"}
                  </button>
                )}
                <a href={`/apps/${m.app_key}`} class="ht-manifest-card__name">
                  {m.display_name}
                </a>
              </div>
              <div class="ht-manifest-card__badges">
                <StatusBadge status={status} size="small" />
                {isMultiInstance && (
                  <span class="ht-badge ht-badge--sm ht-badge--neutral">
                    {pluralize(m.instance_count, "instance")}
                  </span>
                )}
              </div>
            </div>
            {/* TODO: handler/job counts — requires backend to expose handler_count/job_count
               on AppManifestResponse (currently only on DashboardAppGridEntry). See design spec. */}
            <div class="ht-manifest-card__actions">
              <ActionButtons appKey={m.app_key} status={status} />
            </div>
            {isMultiInstance && isExpanded && m.instances?.map((inst) => (
              <div
                key={`${m.app_key}-${inst.index}`}
                class="ht-manifest-card__instance"
                data-testid={`instance-card-${m.app_key}-${inst.index}`}
              >
                <div class="ht-manifest-card__instance-header">
                  <a
                    href={`/apps/${m.app_key}/${inst.index}`}
                    class="ht-manifest-card__instance-name"
                  >
                    {inst.instance_name}
                  </a>
                  <StatusBadge status={inst.status} size="small" />
                </div>
                <div class="ht-manifest-card__instance-actions">
                  <ActionButtons appKey={m.app_key} status={inst.status} />
                </div>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

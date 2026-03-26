import type { AppManifest } from "../../api/endpoints";
import { StatusBadge } from "../shared/status-badge";
import { pluralize } from "../../utils/format";
import { ActionButtons } from "./action-buttons";

interface Props {
  manifest: AppManifest;
  liveStatus?: string;
  isExpanded: boolean;
  onToggleExpand: () => void;
}

export function ManifestRow({ manifest, liveStatus, isExpanded, onToggleExpand }: Props) {
  const status = liveStatus ?? manifest.status;
  const isMultiInstance = manifest.instance_count > 1;
  const expandLabel = isExpanded
    ? `Collapse instances for ${manifest.app_key}`
    : `Expand instances for ${manifest.app_key}`;

  return (
    <>
      <tr class="ht-item-row" data-testid={`app-row-${manifest.app_key}`}>
        <td>
          {isMultiInstance && (
            <button
              type="button"
              class="ht-item-row__chevron-inline"
              onClick={onToggleExpand}
              aria-label={expandLabel}
              aria-expanded={isExpanded}
              data-testid={`expand-toggle-${manifest.app_key}`}
            >
              {isExpanded ? "▾" : "▸"}
            </button>
          )}
          <a href={`/apps/${manifest.app_key}`} class="ht-text-mono">
            {manifest.app_key}
          </a>
        </td>
        <td>
          {manifest.display_name}
          {manifest.class_name !== manifest.display_name && (
            <div class="ht-text-secondary ht-text-xs">{manifest.class_name}</div>
          )}
        </td>
        <td>
          <StatusBadge status={status} size="small" />
          {isMultiInstance && (
            <span class="ht-badge ht-badge--sm ht-badge--neutral ht-ml-1">
              {pluralize(manifest.instance_count, "instance")}
            </span>
          )}
        </td>
        <td class="ht-text-secondary">
          {manifest.error_message ? (
            <span class="ht-text-danger">{manifest.error_message}</span>
          ) : (
            "—"
          )}
        </td>
        <td><ActionButtons appKey={manifest.app_key} status={status} /></td>
      </tr>
      {isMultiInstance && isExpanded && manifest.instances.map((inst) => (
        <tr key={`${manifest.app_key}-${inst.index}`} class="ht-instance-row">
          <td>
            <a href={`/apps/${manifest.app_key}/${inst.index}`} class="ht-text-mono">
              {inst.instance_name}
            </a>
          </td>
          <td />
          <td><StatusBadge status={inst.status} size="small" /></td>
          <td class="ht-text-secondary">
            {inst.error_message ? (
              <span class="ht-text-danger">{inst.error_message}</span>
            ) : (
              "—"
            )}
          </td>
          <td><ActionButtons appKey={manifest.app_key} status={inst.status} /></td>
        </tr>
      ))}
    </>
  );
}

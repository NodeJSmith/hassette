import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import type { AppManifest } from "../../api/endpoints";
import { StatusBadge } from "../shared/status-badge";
import { pluralize } from "../../utils/format";
import { ActionButtons } from "./action-buttons";

interface Props {
  manifest: AppManifest;
  liveStatus?: string;
}

export function ManifestRow({ manifest, liveStatus }: Props) {
  const status = liveStatus ?? manifest.status;
  const isMultiInstance = manifest.instance_count > 1;
  const expanded = useRef(signal(false)).current;

  return (
    <>
      <tr class="ht-item-row" data-testid={`app-row-${manifest.app_key}`}>
        <td>
          {isMultiInstance && (
            <span
              class="ht-item-row__chevron-inline"
              style={{ cursor: "pointer", marginRight: "4px" }}
              onClick={() => { expanded.value = !expanded.value; }}
              title={expanded.value ? "Collapse" : "Expand"}
            >
              {expanded.value ? "▾" : "▸"}
            </span>
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
            <span class="ht-badge ht-badge--sm ht-badge--neutral" style={{ marginLeft: "4px" }}>
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
      {isMultiInstance && expanded.value && manifest.instances.map((inst) => (
        <tr key={`${manifest.app_key}-${inst.index}`} class="ht-instance-row">
          <td style={{ paddingLeft: "2rem" }}>
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

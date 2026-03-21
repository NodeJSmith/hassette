import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import type { AppManifest } from "../../api/endpoints";
import { StatusBadge } from "../shared/status-badge";
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
      <tr class="ht-item-row">
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
          <a href={`/apps/${manifest.app_key}`}>
            <code>{manifest.app_key}</code>
          </a>
        </td>
        <td>{manifest.display_name}</td>
        <td class="ht-text-secondary">{manifest.class_name}</td>
        <td>
          <StatusBadge status={status} size="small" />
          {isMultiInstance && (
            <span class="ht-badge ht-badge--sm ht-badge--neutral" style={{ marginLeft: "4px" }}>
              {manifest.instance_count} instances
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
            <a href={`/apps/${manifest.app_key}/${inst.index}`}>
              <code>{inst.instance_name}</code>
            </a>
          </td>
          <td />
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

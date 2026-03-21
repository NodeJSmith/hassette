import type { AppManifest } from "../../api/endpoints";
import { StatusBadge } from "../shared/status-badge";
import { ActionButtons } from "./action-buttons";

interface Props {
  manifest: AppManifest;
  liveStatus?: string;
}

export function ManifestRow({ manifest, liveStatus }: Props) {
  const status = liveStatus ?? manifest.status;

  return (
    <tr class="ht-item-row">
      <td>
        <a href={`/apps/${manifest.app_key}`} class="ht-item-row-link">
          {manifest.display_name}
        </a>
      </td>
      <td><StatusBadge status={status} size="small" /></td>
      <td class="ht-text-secondary">{manifest.class_name}</td>
      <td class="ht-text-secondary">{manifest.instance_count}</td>
      <td><ActionButtons appKey={manifest.app_key} status={status} /></td>
    </tr>
  );
}

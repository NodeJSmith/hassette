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
        <a href={`/apps/${manifest.app_key}`}>
          <code>{manifest.app_key}</code>
        </a>
      </td>
      <td>{manifest.display_name}</td>
      <td class="ht-text-secondary">{manifest.class_name}</td>
      <td><StatusBadge status={status} size="small" /></td>
      <td class="ht-text-secondary">
        {manifest.error_message ? (
          <span class="ht-text-danger">{manifest.error_message}</span>
        ) : (
          "—"
        )}
      </td>
      <td><ActionButtons appKey={manifest.app_key} status={status} /></td>
    </tr>
  );
}

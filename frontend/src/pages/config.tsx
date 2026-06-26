import { useQuery } from "@tanstack/preact-query";

import { getConfig } from "../api/endpoints";
import { ConfigSchemaView } from "../components/shared/config-schema-view";
import { Spinner } from "../components/shared/spinner";
import { useDocumentTitle } from "../hooks/use-document-title";
import { queryKeys } from "../lib/query-keys";

export function ConfigPage() {
  useDocumentTitle("Config");
  const {
    data: config,
    isPending: loading,
    error,
  } = useQuery({
    queryKey: queryKeys.config(),
    queryFn: getConfig,
  });

  return (
    <div class="ht-page" data-testid="config-page">
      <div class="ht-page-header">
        <h1 class="ht-display">config</h1>
      </div>

      {loading && <Spinner />}

      {error && (
        <div class="ht-alert ht-alert--danger" role="alert">
          {error.message}
        </div>
      )}

      {config && <ConfigSchemaView schema={config.config_schema} values={config.config_values} />}
    </div>
  );
}

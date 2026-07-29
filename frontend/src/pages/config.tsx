import { useQuery } from "@tanstack/react-query";

import { getConfig } from "../api/endpoints";
import { ConfigSchemaView } from "../components/shared/config-schema-view";
import { Spinner } from "../components/shared/spinner";
import { useDocumentTitle } from "../hooks/use-document-title";
import { queryKeys } from "../lib/query-keys";

const PAGE_CLASS = "flex flex-1 flex-col gap-8 p-8 max-mobile:p-3 max-small-mobile:p-2";
const PAGE_HEADER_CLASS = "flex items-baseline gap-4 border-b border-border pb-3";
const PAGE_TITLE_CLASS =
  "m-0 font-heading text-[length:var(--text-display)] font-normal tracking-[var(--text-display-tracking)] text-foreground";
const ALERT_CLASS =
  "flex items-start gap-3 rounded-md border border-destructive bg-[var(--destructive-bg)] px-4 py-3 text-sm text-foreground";

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
    <div className={PAGE_CLASS} data-testid="config-page">
      <div className={PAGE_HEADER_CLASS}>
        <h1 className={PAGE_TITLE_CLASS}>config</h1>
      </div>

      {loading && <Spinner />}

      {error && (
        <div className={ALERT_CLASS} role="alert">
          {error.message}
        </div>
      )}

      {config && <ConfigSchemaView schema={config.config_schema} values={config.config_values} />}
    </div>
  );
}

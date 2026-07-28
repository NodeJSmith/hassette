import type { HandlerKind } from "../../utils/app-routes";
import { type ExecutionRecord, ExecutionTable } from "../shared/execution-table";
import { Spinner } from "../shared/spinner";

interface ExecutionSectionProps {
  heading: string;
  records: ExecutionRecord[] | undefined;
  kind: "handler" | "job";
  tableId: string;
  loading: boolean;
  appKey?: string;
  handlerKind?: HandlerKind;
  handlerId?: number;
  instanceQs?: string;
}

export function ExecutionSection({
  heading,
  records,
  kind,
  tableId,
  loading,
  appKey,
  handlerKind,
  handlerId,
  instanceQs,
}: ExecutionSectionProps) {
  const hasData = records !== undefined;

  return (
    <div className="mt-4 border-t border-border pt-4">
      <h3 className="mb-3 font-sans text-[length:var(--text-h3)] font-medium text-foreground">{heading}</h3>
      {loading && !hasData ? (
        <Spinner />
      ) : (
        <ExecutionTable
          records={records ?? []}
          kind={kind}
          tableId={tableId}
          appKey={appKey}
          handlerKind={handlerKind}
          handlerId={handlerId}
          instanceQs={instanceQs}
        />
      )}
    </div>
  );
}

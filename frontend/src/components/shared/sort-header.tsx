interface Props {
  active: boolean;
  direction: "asc" | "desc";
  onClick: () => void;
  class?: string;
  "data-testid"?: string;
  children: preact.ComponentChildren;
}

export function SortHeader({ active, direction, onClick, class: className, "data-testid": testId, children }: Props) {
  const arrow = active ? (direction === "asc" ? " ↑" : " ↓") : "";
  const ariaSortValue = active ? (direction === "asc" ? "ascending" : "descending") : undefined;
  return (
    <th class={className} aria-sort={ariaSortValue} data-testid={testId}>
      <button
        type="button"
        class={`ht-sort-header${active ? " ht-sort-header--active" : ""}`}
        onClick={onClick}
      >
        {children}<span aria-hidden="true">{arrow}</span>
      </button>
    </th>
  );
}

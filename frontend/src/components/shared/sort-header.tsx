export interface SortState<K extends string = string> {
  key: K;
  dir: "asc" | "desc";
}

interface BaseProps {
  class?: string;
  "data-testid"?: string;
  children: preact.ComponentChildren;
}

interface ManualProps extends BaseProps {
  active: boolean;
  direction: "asc" | "desc";
  onClick: () => void;
  sortKey?: never;
  sort?: never;
  onSort?: never;
}

interface ManagedProps<K extends string> extends BaseProps {
  sortKey: K;
  sort: SortState<K>;
  onSort: (s: SortState<K>) => void;
  active?: never;
  direction?: never;
  onClick?: never;
}

type Props<K extends string = string> = ManualProps | ManagedProps<K>;

export function SortHeader<K extends string = string>(props: Props<K>) {
  const { class: className, "data-testid": testId, children } = props;

  let active: boolean;
  let direction: "asc" | "desc";
  let onClick: () => void;

  if ("sortKey" in props && props.sortKey !== undefined) {
    const managed = props as ManagedProps<K>;
    active = managed.sort.key === managed.sortKey;
    direction = active ? managed.sort.dir : "asc";
    const key = managed.sortKey;
    const onSort = managed.onSort;
    onClick = () => onSort({ key, dir: active && managed.sort.dir === "asc" ? "desc" : "asc" });
  } else {
    active = (props as ManualProps).active;
    direction = (props as ManualProps).direction;
    onClick = (props as ManualProps).onClick;
  }

  const arrow = active ? (direction === "asc" ? " ↑" : " ↓") : "";
  const ariaSortValue = active ? (direction === "asc" ? "ascending" : "descending") : undefined;
  return (
    <th scope="col" class={className} aria-sort={ariaSortValue} data-testid={testId}>
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

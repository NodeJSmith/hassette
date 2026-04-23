import type { Signal } from "@preact/signals";

interface Props {
  showAll: Signal<boolean>;
  totalCount: number;
}

export function ShowMoreButton({ showAll, totalCount }: Props) {
  return (
    <button
      type="button"
      class="ht-btn ht-btn--xs ht-btn--ghost ht-show-more"
      onClick={() => { showAll.value = !showAll.value; }}
    >
      {showAll.value ? "Show less" : `Show all ${totalCount}`}
    </button>
  );
}

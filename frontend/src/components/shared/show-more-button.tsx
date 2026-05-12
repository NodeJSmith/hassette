import type { Signal } from "@preact/signals";
import clsx from "clsx";
import styles from "./show-more-button.module.css";

interface Props {
  showAll: Signal<boolean>;
  totalCount: number;
}

export function ShowMoreButton({ showAll, totalCount }: Props) {
  return (
    <button
      type="button"
      class={clsx("ht-btn ht-btn--xs ht-btn--ghost", styles.showMore)}
      onClick={() => { showAll.value = !showAll.value; }}
    >
      {showAll.value ? "Show less" : `Show all ${totalCount}`}
    </button>
  );
}

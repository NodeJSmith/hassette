import type { Signal } from "@preact/signals";
import styles from "./show-more-button.module.css";
import { Button } from "./button";

interface Props {
  showAll: Signal<boolean>;
  totalCount: number;
}

export function ShowMoreButton({ showAll, totalCount }: Props) {
  return (
    <Button
      ghost
      size="xs"
      class={styles.showMore}
      onClick={() => { showAll.value = !showAll.value; }}
    >
      {showAll.value ? "Show less" : `Show all ${totalCount}`}
    </Button>
  );
}

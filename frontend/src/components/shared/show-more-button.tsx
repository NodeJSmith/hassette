import { Button } from "./button";
import styles from "./show-more-button.module.css";

/** Structural signal-like value — accepts a real `Signal<boolean>` or any `{ value: boolean }`. */
interface BooleanValueHolder {
  value: boolean;
}

interface Props {
  showAll: BooleanValueHolder;
  totalCount: number;
}

export function ShowMoreButton({ showAll, totalCount }: Props) {
  return (
    <Button
      ghost
      size="xs"
      class={styles.showMore}
      onClick={() => {
        showAll.value = !showAll.value;
      }}
    >
      {showAll.value ? "Show less" : `Show all ${totalCount}`}
    </Button>
  );
}

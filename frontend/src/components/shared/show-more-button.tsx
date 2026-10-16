import { Button } from "@/components/ui/button";

interface Props {
  showAll: boolean;
  onToggle: () => void;
  totalCount: number;
}

export function ShowMoreButton({ showAll, onToggle, totalCount }: Props) {
  return (
    <Button variant="link" size="xs" className="mt-auto pt-2" onClick={onToggle}>
      {showAll ? "Show less" : `Show all ${totalCount}`}
    </Button>
  );
}

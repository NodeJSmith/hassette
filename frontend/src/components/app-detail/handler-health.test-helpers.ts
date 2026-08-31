import type { HandlerKind } from "../../utils/app-routes";

export const CARD_TESTID_PREFIX = "overview-health-card-";
export const CARD_SELECTOR = `[data-testid^='${CARD_TESTID_PREFIX}']`;

export function cardTestId(kind: HandlerKind, id: number) {
  return `${CARD_TESTID_PREFIX}${kind}-${id}`;
}

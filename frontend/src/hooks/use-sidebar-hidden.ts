import { useAppState } from "../state/context";
import { BREAKPOINT_SIDEBAR, useMediaQuery } from "./use-media-query";

/**
 * True when the sidebar's contents are off screen — either collapsed on desktop or
 * replaced by the off-canvas drawer below BREAKPOINT_SIDEBAR.
 *
 * The status bar reads this to decide whether to render its compact health fallback.
 * Both causes are treated the same on purpose: the reason the sidebar went away does
 * not change the fact that connection status has to stay visible somewhere.
 */
export function useSidebarHidden(): boolean {
  const { sidebarCollapsed } = useAppState();
  const belowBreakpoint = useMediaQuery(BREAKPOINT_SIDEBAR);

  return belowBreakpoint || sidebarCollapsed.value;
}

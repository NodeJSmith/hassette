export const STATUS_SHAPE_SIZE = 10;
export const DETAIL_FETCH_LIMIT = 50;
// Shared default size (px) for small inline SVG glyphs (FilterIcon, StatusShape)
// used in table-header contexts.
export const SMALL_ICON_SIZE = 12;
// Status shape scaled to sit alongside heading-sized text (h1/h2).
export const HEADING_STATUS_SHAPE_SIZE = 14;

// The StatusShape sizes below are named for the role they play, not the pixel value they
// happen to hold. Some coincide numerically today; they are still separate names so that
// retuning one context cannot silently drag an unrelated one with it. Pick by the role being
// rendered, never by matching a number.
//
// Status shape scaled to sit inline inside a badge/pill. Deliberately smaller than the
// standalone STATUS_SHAPE_SIZE above, which is sized for table cells and list rows.
export const BADGE_STATUS_SHAPE_SIZE = 8;
// Status shapes in the apps table's own rows — smaller than STATUS_SHAPE_SIZE (10) to fit the
// table's tighter row height. The instance sub-row is smaller again to read as nested under
// its parent app row.
export const APP_ROW_STATUS_SHAPE_SIZE = 7;
export const INSTANCE_ROW_STATUS_SHAPE_SIZE = 6;
// Status shape in a dense list row — one tighter than the standard list row STATUS_SHAPE_SIZE
// (10) targets, whether because the row is nested under a parent or because its own line
// height is compressed. Currently the sidebar's instance sub-rows and the command palette's
// results.
export const COMPACT_STATUS_SHAPE_SIZE = 8;
// Status shape beside a collapsible group header's uppercase micro-label, smaller again than
// the compact row size so the header reads as a divider rather than another row.
export const GROUP_HEADER_STATUS_SHAPE_SIZE = 7;

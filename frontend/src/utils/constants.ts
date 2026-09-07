export const STATUS_DOT_SIZE = 10;
export const DETAIL_FETCH_LIMIT = 50;
// Shared default size (px) for small inline SVG glyphs (FilterIcon, StatusShape)
// used in table-header contexts.
export const SMALL_ICON_SIZE = 12;
// Status shape scaled to sit alongside heading-sized text (h1/h2).
export const HEADING_STATUS_SHAPE_SIZE = 14;
// The StatusShape sizes below are named for the role they play, not the pixel value they
// happen to hold. Some pairs coincide numerically today; they are still separate names so
// that retuning one context cannot silently drag an unrelated one with it. Pick by the role
// being rendered, never by matching a number.
//
// Status shape scaled to sit inline inside a badge/pill. Deliberately smaller than the
// standalone STATUS_DOT_SIZE above, which is sized for table cells and list rows. Shares its
// value with COMPACT_STATUS_DOT_SIZE below — that one is for unadorned dense rows, this one
// only for shapes enclosed in a badge or pill.
export const BADGE_STATUS_DOT_SIZE = 8;
// Status shapes in the apps table's own rows — smaller than STATUS_DOT_SIZE (10) to fit the
// table's tighter row height. The instance sub-row is smaller again to read as nested under
// its parent app row. APP_ROW shares its value with GROUP_HEADER_STATUS_SHAPE_SIZE below,
// which sizes a header divider rather than a data row.
export const APP_ROW_STATUS_SHAPE_SIZE = 7;
export const INSTANCE_ROW_STATUS_SHAPE_SIZE = 6;
// Status shape in a dense list row — one tighter than the standard list row STATUS_DOT_SIZE
// (10) targets, whether because the row is nested under a parent or because its own line
// height is compressed. Currently the sidebar's instance sub-rows and the command palette's
// results. Same value as BADGE_STATUS_DOT_SIZE above, which covers badge/pill interiors.
export const COMPACT_STATUS_DOT_SIZE = 8;
// Status shape beside a collapsible group header's uppercase micro-label, smaller again than
// the compact row size so the header reads as a divider rather than another row. Same value
// as APP_ROW_STATUS_SHAPE_SIZE above, which sizes actual data rows.
export const GROUP_HEADER_STATUS_SHAPE_SIZE = 7;

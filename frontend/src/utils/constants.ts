export const STATUS_DOT_SIZE = 10;
export const DETAIL_FETCH_LIMIT = 50;
// Shared default size (px) for small inline SVG glyphs (FilterIcon, StatusShape)
// used in table-header contexts.
export const SMALL_ICON_SIZE = 12;
// Status shape scaled to sit alongside heading-sized text (h1/h2).
export const HEADING_STATUS_SHAPE_SIZE = 14;
// Status shape scaled to sit inline inside a badge/pill. Deliberately smaller than the
// standalone STATUS_DOT_SIZE above, which is sized for table cells and list rows.
export const BADGE_STATUS_DOT_SIZE = 8;
// Status shapes in the apps table's own rows — smaller than STATUS_DOT_SIZE (10) to fit the
// table's tighter row height. The instance sub-row is smaller again to read as nested under
// its parent app row.
export const APP_ROW_STATUS_SHAPE_SIZE = 7;
export const INSTANCE_ROW_STATUS_SHAPE_SIZE = 6;

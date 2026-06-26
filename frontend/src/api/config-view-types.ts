/**
 * Shapes of the config-view API payload ({config_schema, config_values}) returned by
 * /api/config and /api/apps/{key}/config. These describe server response data, so they
 * live in the api layer; the shared renderer consumes them.
 */

export type ConfigRecord = Record<string, unknown>;

/** Subset of JSON Schema node we consume. Kept intentionally loose — unknown fields pass through. */
export interface SchemaNode {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  writeOnly?: boolean;
  format?: string;
  properties?: Record<string, SchemaNode>;
  anyOf?: SchemaNode[];
  items?: SchemaNode;
  ui?: UiHints;
  [key: string]: unknown;
}

/** Presentation-metadata namespace set via json_schema_extra on Pydantic fields/models. */
export interface UiHints {
  label?: string;
  group_label?: string;
  order?: number;
  widget?: string;
  /** Reserved for future tiering fast-follow — unset on all fields, ignored by the renderer. */
  tier?: "common" | "advanced";
}

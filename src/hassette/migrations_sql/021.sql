-- Migration 021: persist the app manifest's optional one-line description.
--
-- app_manifests is the source of truth for an app's static metadata (see overlay_runtime_state in
-- core/app_registry.py), so an app removed from config still serves the description it last had.
-- Length and line breaks are validated on AppManifest, the column's only writer; no CHECK here, so a
-- later limit change needs no table rebuild.
ALTER TABLE app_manifests ADD COLUMN description TEXT;

# HA Core Comparison Audit — 2026-02-19

Comparison of Hassette's `api.py` and `models/states/` against the HA core repo (`~/source/core`), focusing on HA-owned/core functionality only.

## Critical — Major Functionality Gaps

### 1. MediaPlayerState has virtually no core attributes

**File:** `src/hassette/models/states/media_player.py`

Hassette only models 3 integration-specific fields (`assumed_state`, `adb_response`, `hdmi_input`). It is missing ALL 20+ core HA media player attributes.

**Missing state_attributes (from HA `ATTR_TO_PROPERTY`):**

| Attribute | HA constant | Type |
|-----------|------------|------|
| `volume_level` | `ATTR_MEDIA_VOLUME_LEVEL` | `float \| None` |
| `is_volume_muted` | `ATTR_MEDIA_VOLUME_MUTED` | `bool \| None` |
| `media_content_id` | `ATTR_MEDIA_CONTENT_ID` | `str \| None` |
| `media_content_type` | `ATTR_MEDIA_CONTENT_TYPE` | `str \| None` |
| `media_duration` | `ATTR_MEDIA_DURATION` | `int \| None` |
| `media_position` | `ATTR_MEDIA_POSITION` | `int \| None` |
| `media_position_updated_at` | `ATTR_MEDIA_POSITION_UPDATED_AT` | `datetime \| None` |
| `media_title` | `ATTR_MEDIA_TITLE` | `str \| None` |
| `media_artist` | `ATTR_MEDIA_ARTIST` | `str \| None` |
| `media_album_name` | `ATTR_MEDIA_ALBUM_NAME` | `str \| None` |
| `media_album_artist` | `ATTR_MEDIA_ALBUM_ARTIST` | `str \| None` |
| `media_track` | `ATTR_MEDIA_TRACK` | `int \| None` |
| `media_series_title` | `ATTR_MEDIA_SERIES_TITLE` | `str \| None` |
| `media_season` | `ATTR_MEDIA_SEASON` | `str \| None` |
| `media_episode` | `ATTR_MEDIA_EPISODE` | `str \| None` |
| `media_channel` | `ATTR_MEDIA_CHANNEL` | `str \| None` |
| `media_playlist` | `ATTR_MEDIA_PLAYLIST` | `str \| None` |
| `app_id` | `ATTR_APP_ID` | `str \| None` |
| `app_name` | `ATTR_APP_NAME` | `str \| None` |
| `source` | `ATTR_INPUT_SOURCE` | `str \| None` |
| `sound_mode` | `ATTR_SOUND_MODE` | `str \| None` |
| `shuffle` | `ATTR_MEDIA_SHUFFLE` | `bool \| None` |
| `repeat` | `ATTR_MEDIA_REPEAT` | `str \| None` |
| `group_members` | `ATTR_GROUP_MEMBERS` | `list[str] \| None` |

**Missing capability_attributes:**

| Attribute | HA constant | Type |
|-----------|------------|------|
| `source_list` | `ATTR_INPUT_SOURCE_LIST` | `list[str] \| None` |
| `sound_mode_list` | `ATTR_SOUND_MODE_LIST` | `list[str] \| None` |

**Impact:** Any automation that reads media player attributes will get `None` for all typed fields. Data falls through to `extras` dict only.

**Fix:** Replace the 3 integration-specific fields with the full set of HA core attributes. Move `assumed_state`, `adb_response`, `hdmi_input` to extras (they're integration-specific, not core).

---

### ~~2. CoverState has no attributes~~ (Resolved)

CoverState now has a dedicated `src/hassette/models/states/cover.py` with `CoverAttributes` including `current_position`, `current_tilt_position`, and feature support helpers. No action needed.

---

### 3. LockState has no attributes

**File:** `src/hassette/models/states/simple.py:51`

Defined as a bare `StringBaseState` with no `LockAttributes` class.

**Missing state_attributes:**

| Attribute | HA constant | Type |
|-----------|------------|------|
| `changed_by` | `ATTR_CHANGED_BY` | `str \| None` |
| `code_format` | `ATTR_CODE_FORMAT` | `str \| None` |

**Fix:** Create `lock.py` with `LockAttributes` and `LockState`, remove `LockState` from `simple.py`.

---

## Concerning — Missing Attributes on Otherwise-Modeled Entities

### 4. LightState — Missing RGBW/RGBWW color support

**File:** `src/hassette/models/states/light.py`

**Missing attributes:**

| Attribute | Type | Notes |
|-----------|------|-------|
| `rgbw_color` | `tuple[int, int, int, int] \| None` | Only when `ColorMode.RGBW` supported |
| `rgbww_color` | `tuple[int, int, int, int, int] \| None` | Only when `ColorMode.RGBWW` supported |

---

### 5. ClimateState — Missing several attributes

**File:** `src/hassette/models/states/climate.py`

**Missing state_attributes:**

| Attribute | Type | Notes |
|-----------|------|-------|
| `humidity` | `float \| None` | Target humidity (different from `current_humidity`) |
| `swing_horizontal_mode` | `str \| None` | Newer HA feature |

**Missing capability_attributes:**

| Attribute | Type | Notes |
|-----------|------|-------|
| `target_temp_step` | `float \| None` | Temperature step granularity |
| `min_humidity` | `float \| None` | If TARGET_HUMIDITY feature supported |
| `max_humidity` | `float \| None` | If TARGET_HUMIDITY feature supported |
| `target_humidity_step` | `float \| None` | If TARGET_HUMIDITY feature supported |
| `swing_horizontal_modes` | `list[str] \| None` | Newer HA feature |

---

### 6. WeatherState — Missing key attributes

**File:** `src/hassette/models/states/weather.py`

**Missing attributes:**

| Attribute | Type | Notes |
|-----------|------|-------|
| `ozone` | `float \| None` | Ozone level |
| `uv_index` | `float \| None` | UV index |
| `wind_gust_speed` | `float \| None` | Wind gust speed |
| `visibility` | `float \| None` | Has `visibility_unit` but not the value! |

---

### 7. FanState — Missing direction; has integration-specific junk

**File:** `src/hassette/models/states/fan.py`

**Missing attribute:**

| Attribute | Type | Notes |
|-----------|------|-------|
| `direction` | `str \| None` | `current_direction` in HA core |

**Integration-specific fields that don't belong in the core model:**

These should be removed — they're specific to certain fan integrations and will correctly land in `extras` via `extra="allow"`:

- `temperature` — not a core fan attribute
- `model` — not a core fan attribute
- `sn` — serial number from a specific integration
- `screen_status` — integration-specific
- `child_lock` — integration-specific
- `night_light` — integration-specific
- `mode` — integration-specific (not `preset_mode`)

---

### 8. CameraState — Missing motion_detection

**File:** `src/hassette/models/states/camera.py`

**Missing attribute:**

| Attribute | Type | Notes |
|-----------|------|-------|
| `motion_detection` | `bool \| None` | Whether motion detection is enabled |

---

## Minor

### 9. SensorState — Missing last_reset

**File:** `src/hassette/models/states/sensor.py`

| Attribute | Type | Notes |
|-----------|------|-------|
| `last_reset` | `str \| None` | ISO datetime string, only for `TOTAL` state_class |

### 10. HumidifierState — Missing target_humidity_step

**File:** `src/hassette/models/states/humidifier.py`

| Attribute | Type | Notes |
|-----------|------|-------|
| `target_humidity_step` | `float \| None` | Capability attribute |

### 11. AlarmControlPanelState — Extra fields not in HA core

**File:** `src/hassette/models/states/alarm_control_panel.py`

`previous_state` and `next_state` are not in HA core's `state_attributes`. They may be integration-specific and should be removed from the typed model (they'll still be accessible via `extras`).

### 12. FanAttributes — Integration-specific fields (same as #7)

See finding #7.

---

## API Gaps

### 13. No registry APIs

**File:** `src/hassette/api/api.py`

No typed wrappers for:
- `config/device_registry/list` — List devices
- `config/entity_registry/list` — List entity registry entries
- `config/area_registry/list` — List areas
- Create/update/delete operations on all three registries

Users must use raw `ws_send_and_wait(type="config/device_registry/list")` with untyped responses.

### 14. No statistics API

Missing `statistics/during_period` WebSocket command for retrieving long-term statistics data.

### 15. Phantom `update_state` in API docstring

**File:** `src/hassette/api/api.py:62`

The module docstring shows `await self.api.update_state("sensor.custom", {"battery": 85})` but no `update_state` method exists. Either add the method or remove the example.

---

## Entities with Complete Coverage

These Hassette state models match HA core well:

- **AlarmControlPanelState** — Complete (minor: extra fields, see #11)
- **AutomationState** — Complete (`id`, `last_triggered`, `mode`, `current`, `max`)
- **CalendarState** — Complete
- **DeviceTrackerState** — Complete
- **EventState** — Complete
- **HumidifierState** — Nearly complete (minor: missing `target_humidity_step`)
- **Input\*** states — Complete
- **NumberState** — Complete
- **PersonState** — Complete
- **RemoteState** — Complete
- **SceneState** — Complete
- **ScriptState** — Complete
- **SelectState** — Complete
- **SirenState** — Complete
- **SunState** — Complete
- **TextState** — Complete
- **TimerState** — Complete
- **UpdateState** — Complete
- **VacuumState** — Complete
- **ValveState** — Bare `StringBaseState` with no attributes — may need `current_position` similar to CoverState
- **WaterHeaterState** — Complete
- **ZoneState** — Complete

---

## Methodology

- Compared Hassette state models against HA core `state_attributes` and `capability_attributes` properties
- HA core source: `~/source/core/homeassistant/components/<domain>/__init__.py`
- Hassette source: `src/hassette/models/states/`
- Focused on HA-owned components only, not third-party integrations
- All "missing" attributes would still be accessible via `extras` (due to `extra="allow"`), but without type safety

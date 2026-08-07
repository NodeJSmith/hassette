---
task_id: "T01"
title: "Generate NON_NUMERIC_DEVICE_CLASSES and pin HA's predicate source"
status: "planned"
depends_on: []
implements: ["FR#11", "FR#17", "AC#7", "AC#15"]
---

## Summary

Teach codegen to extract Home Assistant's `NON_NUMERIC_DEVICE_CLASSES` set literal and emit it as a
runtime constant in `src/hassette/const/sensor.py`, so the shape classifier's *data* half tracks HA
releases instead of being hand-maintained. Also add a drift guard: codegen snapshots the source text
of HA's `_numeric_state_expected` function and fails the freshness check when upstream changes it,
forcing a human to re-verify the hand-written port. This task is a prerequisite for the classifier
in T04.

## Target Files

- modify: `codegen/src/hassette_codegen/extractors/constants.py`
- modify: `codegen/src/hassette_codegen/generators/constants.py`
- create: `codegen/snapshots/numeric_state_expected.py.txt` (path may be adjusted — see Focus)
- modify: `codegen/src/hassette_codegen/pipeline.py`
- regenerate: `src/hassette/const/sensor.py`
- read: `codegen/src/hassette_codegen/rendering.py`
- read: `codegen/src/hassette_codegen/ha_source.py`
- read: `~/source/core/homeassistant/components/sensor/const.py`
- read: `~/source/core/homeassistant/components/sensor/__init__.py`
- modify: `codegen/tests/test_constants_and_exports.py`
- modify: `codegen/tests/test_extractors.py`
- read: `codegen/tests/test_integration.py`

## Prompt

Read `context.md` first, then the design doc's `## Architecture → The shape classifier` section
(specifically the "The data" and "The drift guard (FR#17)" paragraphs).

**Part 1 — extract the set (FR#11).**

Add a set-literal extractor to `codegen/src/hassette_codegen/extractors/constants.py`, mirroring the
shape of the existing `_extract_strenum_members` (parse, walk, match a named target, return values,
tolerate a `SyntaxError` by returning empty). Wire it into `extract_sensor_constants`, which already
reads `homeassistant/components/sensor/const.py` for `SensorDeviceClass` and `SensorStateClass`.

The upstream literal is at `homeassistant/components/sensor/const.py:556-561`:

```python
NON_NUMERIC_DEVICE_CLASSES = {
    SensorDeviceClass.DATE,
    SensorDeviceClass.ENUM,
    SensorDeviceClass.TIMESTAMP,
    SensorDeviceClass.UPTIME,
}
```

Note this is a set of **enum attribute references** (`ast.Attribute` nodes), not string constants —
`_extract_strenum_members` reads `ast.Constant` and will not work as-is. Resolve each member to its
string value by cross-referencing the `SensorDeviceClass` members already extracted from the same
file. Do not lowercase the attribute name as a shortcut: resolve against the enum so the extractor
stays correct if HA ever gives a member a value that differs from its lowercased name.

**Part 2 — render it as a runtime set (FR#11).**

`generators/constants.py` currently renders every `ExtractedConstantSet` as a `Literal[...]` type
alias. `NON_NUMERIC_DEVICE_CLASSES` must be a **runtime `frozenset[str]`**, not a type alias,
because the classifier compares values against it at runtime. Extend the generator with a rendering
path for runtime-set constants while leaving the existing `Literal` output for `DEVICE_CLASS`,
`STATE_CLASS`, and `UNIT_OF_MEASUREMENT` byte-for-byte unchanged.

Regenerate and commit `src/hassette/const/sensor.py`:

```bash
cd codegen && uv run hassette-codegen generate --ha-core-path ~/source/core
```

**Part 3 — the drift guard (FR#17).**

Extract the source text of `_numeric_state_expected` from
`homeassistant/components/sensor/__init__.py:126-145` and compare it against a committed snapshot.
On mismatch, fail the codegen freshness check (`hassette-codegen generate --check`, which is what CI
runs) with a message that names the file, says the ported predicate in
`src/hassette/models/states/sensor_shapes.py` must be re-verified against the new upstream logic,
and tells the operator to update the snapshot once they have done so.

Use `ast` to locate the function and `ast.get_source_segment` (or equivalent) to capture its text, so
the snapshot is insensitive to unrelated edits elsewhere in the file. Write the snapshot as a plain
text file committed to the repo.

Add codegen unit tests for the new extractor and the drift comparison in `codegen/tests/` — the
existing `test_extractors.py` and `test_constants_and_exports.py` are the right homes. CI runs these
via `cd codegen && uv run pytest tests/ -q --rootdir=.`.

## Focus

**Exact snapshot path is yours to determine.** `codegen/snapshots/` does not exist today — the
design names it as an example, not a requirement ("exact path per existing codegen layout
conventions"). Codegen's current layout is `codegen/src/hassette_codegen/{extractors,generators,
templates,overrides}/` plus `codegen/tests/` and `codegen/ha-version.txt`. Pick whichever fits: a
new top-level `codegen/snapshots/` next to `ha-version.txt` (both are pinned-upstream-state files,
which is a genuine parallel), or inside the package next to the extractor that reads it. Prefer the
top-level sibling of `ha-version.txt` unless the packaging config (`codegen/pyproject.toml`) makes
a non-package data file awkward to ship — check before deciding, and record the reason in the
commit message.

**The version pin already matches.** `codegen/ha-version.txt` is 2026.8.0 and `~/source/core` is at
2026.8.0, so regeneration will not pull in an unrelated version bump or trip
`_warn_version_mismatch` (`ha_source.py`).

**Regeneration touches more than `const/sensor.py`.** `hassette-codegen generate` rewrites every
generated file. After running it, check `git status` — if files unrelated to this task changed, that
is pre-existing drift, not your change. Report it rather than committing it silently.

**Do not port the predicate logic in this task.** T04 owns the hand-written classifier. This task
only produces the generated data and the snapshot that guards the port. The snapshot's failure
message may reference `sensor_shapes.py` even though that file does not exist yet — it is a message
string, not an import.

**`_extract_strenum_members` returns `list[str]` in declaration order.** The four non-numeric device
classes appear first in the generated `DEVICE_CLASS` Literal today (`date`, `enum`, `timestamp`,
`uptime`), which is HA's own declaration order — a useful cross-check that your extractor resolved
the right members.

## Verify

- [ ] FR#11: `NON_NUMERIC_DEVICE_CLASSES` appears in `src/hassette/const/sensor.py` as a runtime
      `frozenset` containing exactly `date`, `enum`, `timestamp`, `uptime`, and is produced by
      codegen rather than hand-written.
- [ ] FR#17: Codegen extracts `_numeric_state_expected`'s source text and compares it to a committed
      snapshot; a mismatch fails the freshness check with a message directing re-verification of the
      port.
- [ ] AC#7: `cd codegen && uv run hassette-codegen generate --ha-core-path ~/source/core` leaves
      `git diff --exit-code` clean, and `NON_NUMERIC_DEVICE_CLASSES` appears in
      `src/hassette/const/sensor.py`.
- [ ] AC#15: With the committed snapshot deliberately modified, the codegen freshness check fails
      with a message directing re-verification of the port; restored, it passes. Covered by a
      codegen unit test in `codegen/tests/`, runnable via `cd codegen && uv run pytest tests/ -q --rootdir=.`.

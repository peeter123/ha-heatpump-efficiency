# Design

## Context

See proposal.md - Why. The planned section is a collapsed form section (`validation.SECTION_PLANNED`, key
`planned`) that holds only the price source (`validation.FIELD_PRICE`, `PLANNED_FIELDS = (FIELD_PRICE,)`), built by
`config_flow._planned_schema` and stored in the entry options by `validation.normalize_mapping` when filled. Nothing
reads it: `validation.statistic_ids` excludes it, and no engine, sensor, issue or diagnostics code uses it.
`validation.expanded_sections` lets it expand when it has stored values. Config entries are at `VERSION` 1,
`MINOR_VERSION` 3 (`config_flow.py`); `__init__.async_migrate_entry` runs `with_default_seasons` for minor < 2 and
`with_defrost_moved` for minor < 3 (archived change `2026-11-23-add-defrost-correction`, design D3), then stores
everything with one `async_update_entry`. `with_defrost_moved` reads the planned section's legacy `defrost_heat`
key and keeps the rest of the section (the price source).

Facts that shape the change, all ha-core at tag 2026.11.2, already used and cited in the archived designs (no new
API):

- `config_entries.py` `ConfigEntry.async_migrate`: an entry whose `minor_version` differs from the handler's
  `MINOR_VERSION` at the same `VERSION` calls the integration's `async_migrate_entry(hass, entry)`, also when the
  entry's minor version is higher (an older integration version then keeps the entry if it returns True).
- `config_entries.py` `ConfigEntries.async_update_entry(entry, *, options=..., minor_version=...)` stores the new
  options and minor version; no reload is triggered.
- `data_entry_flow.py` `section`: a section that is not in the schema is neither shown nor submitted.

## Goals / Non-Goals

**Goals:**

- After the migration, no stored entry holds a planned section, so stored data matches what the forms show.
- Entries from every earlier minor version (1, 2, 3) end in the same shape as a new entry.
- No change to any figure, read, sensor, attribute or entity ID.

**Non-Goals:**

- Removing the migration helpers of earlier minor versions; minor 1 and 2 entries still need them.
- A replacement for the price source in any form (see proposal.md - Out of scope).

## Decisions

### D1. Drop the stored value, do not keep it ignored

The user decided (2026-11-23) that a stored price source is dropped. Alternatives considered:

- Keep it stored and ignored. Rejected: the entry would hold data that no form shows and no code reads, and it
  would disappear silently on the owner's next options save anyway, since `normalize_mapping` no longer builds a
  planned section. A migration makes that happen once, at a known moment, and the README can say so.
- Keep the field hidden in the form. Rejected: a slot that will never be used is the thing being removed.

### D2. Migration to minor version 4

`ConfigFlow.MINOR_VERSION = 4` (`VERSION` stays 1). New pure helper `without_planned(options)` in `validation.py`:
returns a copy of the options without the `planned` key; every other key is kept unchanged, the input is not
modified, and options without the key come back as an equal copy (idempotent). `async_migrate_entry` runs the
steps in order for `entry.version == 1 and entry.minor_version < 4`: `minor_version < 2` adds the season dates,
`minor_version < 3` moves the defrost slot (unchanged), then always `without_planned`, then one
`async_update_entry(entry, options=..., minor_version=4)`.

Order matters for a minor 1 or 2 entry: `with_defrost_moved` must still see the planned section's `defrost_heat`
before the section is dropped. The two helpers stay separate pure functions instead of folding the drop into
`with_defrost_moved`, so the minor 3 step keeps its tested behaviour and each step is tested on its own plus once
in the full chain. Alternative: let `with_defrost_moved` drop the whole section. Rejected: it would change a tested
step's contract and mix two migrations in one function.

Downgrade: an older version (minor 3) calls its own `async_migrate_entry` for a minor 4 entry, which does nothing
for minor >= 3 and returns True; its form then shows an empty planned section. Nothing breaks. A price source
saved there stays stored at minor 4 after upgrading again, since no migration runs; nothing reads it, and the next
options save drops it (`normalize_mapping` builds no planned section). Accepted (whole-change review, 2026-11-23).

### D3. Constants and form code

- `FIELD_PRICE` and `PLANNED_FIELDS` are removed. `SECTION_PLANNED` stays, documented as the legacy stored key that
  only the migration helpers read (`with_defrost_moved`, `without_planned`); `FIELD_DEFROST_HEAT` stays (it is the
  service field too).
- `config_flow._planned_schema` and the section in `_form_schema` are removed; the options flow docstring no longer
  names the price source.
- `normalize_mapping` no longer reads a planned section; a stale submitted `planned` key is ignored.
  `expanded_sections` intersects with the services and `seasons` only. `statistic_ids` loses its note on the price
  source.
- `translations/en.json`: the `planned` section is removed from `config.step.user.sections` and
  `options.step.init.sections`, and "the planned price source" from the options step description. A text-level test
  in `tests/test_integration_files.py` checks that neither step has a planned section and that no translation
  string mentions a price source.

### D4. README

The "Planned (not used yet)" bullet is removed. Its paragraph on the moved defrost slot is kept, without the price
source, and moves to the description of the Defrost heat statistics field under a short "Entries from earlier
versions" note, which also says that a stored price source is dropped once. The Configure paragraph no longer
names the price source. One sentence in the overview says cost is not part of the integration. The existing README
test phrases ("moved once") keep passing; the test gains a check that "Planned (not used yet)" and the field label
"**Price source:**" are gone (the migration note still names the price source in lower case).

## Risks / Trade-offs

- [An owner who chose a price source loses it] -> it never did anything; the README states the drop. Reinstalling
  an older version does not bring it back, which is acceptable for an unused value.
- [A minor 1 or 2 entry migrated in the wrong order would lose its defrost slot] -> the chain is fixed in D2 and
  tested end to end: a minor 2 options dict with a price source and a planned defrost slot ends with the slot under
  Heating and no planned section.

## Migration Plan

Install the new version on the live installation and restart (final task group, with the user's go-ahead and a
backup offered). The entry migrates from minor 3 to 4 on load. Check the stored options (no planned section, the
rest unchanged), the options form (no planned section) and the sensors. Rollback: reinstall the previous version;
it keeps the minor 4 entry (D2 Downgrade).

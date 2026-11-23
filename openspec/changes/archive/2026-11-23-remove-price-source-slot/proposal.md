# Proposal

## Why

The setup and options forms have a collapsed "Planned (not used yet)" section with one optional price source,
stored only, for a later cost per kWh of heat. Cost does not fit this integration. With a dynamic tariff the cost
of a period is the sum of price times energy at each moment, not the average price times the period's energy
(derived). Computing it from a price entity would mean averaging the price within each statistics hour (the kind
of time average the integration exists to avoid), and the cheap counter-difference reads for long periods would no
longer work. Whether solar self-consumption, net metering, taxes or fixed charges count is a tariff policy that
differs per installation, which a universal integration should not decide. Cost per kWh of heat is therefore
dropped from this integration, and the unused slot goes with it, so the forms show nothing that will never work.

## What Changes

- **BREAKING (stored data only):** the planned section with its price source is removed from the setup and options
  forms. No other field moves; no entity, sensor or attribute changes, since none was ever created from the slot.
- **Migration.** A config entry migration to minor version 4 drops the stored planned section, including a stored
  price source, once, when an entry is first loaded by this version. Every other stored value stays unchanged. The
  existing steps (season dates for minor 2, the defrost slot moved into Heating for minor 3) still run first for
  older entries, so a minor 2 entry's planned defrost slot is still moved before the section is dropped.
- Translations: the planned section is removed from both forms, and the options form's description no longer names
  the price source.
- README: the "Planned (not used yet)" bullet, the price source in the Configure paragraph and in the note on the
  moved defrost slot are removed; a short note says that cost is not part of the integration, and that the
  migration drops a stored price source.
- Out of scope:
  - cost per kWh of heat in any form. No follow-up change in this repository covers it; an owner who wants it
    builds a cost counter in their own Home Assistant configuration. The backlog entry for it (outside the
    tracked files) is removed when this change is archived;
  - any change to the efficiency, season, series or defrost figures;
  - publishing or a release (a separate step).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `efficiency-setup`: requirement "Price source slot" removed; "Mapping changed later" no longer names the price
  source; "Defrost slot of existing entries" no longer keeps a price source; new requirements state that the forms
  offer no cost settings ("No cost settings") and that the planned section of existing entries is dropped ("Planned
  section of existing entries").

## Impact

- Code: `custom_components/heatpump_efficiency/` (`validation.py`: the price field, the planned fields and their
  handling in `normalize_mapping` and `expanded_sections` removed, a pure helper that drops the planned section;
  `config_flow.py`: the planned schema removed, `MINOR_VERSION = 4`; `__init__.py`: the migration step;
  `translations/en.json`), `tests/`, `README.md`.
- Home Assistant APIs (ha-core 2026.11.2), all already in use: `config_entries.py` entry migration
  (`ConfigEntry.async_migrate`, `ConfigFlow.MINOR_VERSION`, `ConfigEntries.async_update_entry`) and
  `data_entry_flow.py` `section`. No new reads; statistics stay untouched.
- Live installation (final task group, each step with the user's go-ahead): copy the updated integration to the
  Home Assistant host and restart (backup offered); check that the entry migrated to minor version 4, that its
  stored options have no planned section and are otherwise unchanged, that the options form no longer shows the
  planned section, and that the sensors work unchanged. No dashboard change.

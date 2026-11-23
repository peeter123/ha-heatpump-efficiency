# Tasks

Validation for every group: `python -m unittest discover tests` and `python -m compileall -q custom_components`
exit 0 (from the repository root, standard library only).

## 1. Remove the planned section and migrate stored entries

- [x] 1.1 Remove the price source from `validation.py` (design D3): drop `FIELD_PRICE` and `PLANNED_FIELDS`, stop `normalize_mapping` from building a planned section, limit `expanded_sections` to the services and `seasons`, remove the price note from `statistic_ids`, and document `SECTION_PLANNED` as the legacy stored key read only by the migration helpers; verify `tests/test_validation.py`, updated where it used the planned section, shows that a submitted `planned` key is ignored and that the expanded sections never include `planned`
- [x] 1.2 Add the pure helper `without_planned(options)` to `validation.py` and the minor version 4 step to `__init__.async_migrate_entry` after the defrost step, with one `async_update_entry(..., minor_version=4)` and the ha-core citations kept (design D2); verify tests that "Price source dropped" and "Entry without a planned section" hold, that the helper does not modify its input and is idempotent, that a minor 2 options dict with a price source and a planned defrost slot ends with the slot under Heating and no planned section, that "Slot holding an output statistic" ends without a planned section, and that the source checks name `minor_version=4)` once
- [x] 1.3 Remove `_planned_schema` and the planned section from `config_flow._form_schema`, set `MINOR_VERSION = 4` with its comment listing the minor 4 step, and update the options flow docstring (design D3); verify `python -m compileall` passes and `tests/test_integration_files.py` checks `MINOR_VERSION = 4`
- [x] 1.4 Remove the `planned` section from `config.step.user.sections` and `options.step.init.sections` in `translations/en.json` and the price source from the options step description (design D3); verify `tests/test_integration_files.py` checks that the form sections in both steps match the schema with no planned section and that no translation string mentions a price source ("No cost settings")
- [x] 1.5 Update README.md (design D4): remove the "Planned (not used yet)" bullet and the price source from the Configure paragraph, keep the moved-defrost-slot paragraph without the price source under an "Entries from earlier versions" note at the Defrost heat statistics field that also says a stored price source is dropped once, and add one sentence that cost is not part of the integration; verify the README test still finds "moved once" and checks that "Planned (not used yet)" and the field label "**Price source:**" are gone

## 2. Live installation

- [x] 2.1 [User authorization: copies files to the Home Assistant host and restarts it] Offer a backup, copy the updated `custom_components/heatpump_efficiency/` to the host and restart; verify the entry loads without errors in the log
- [x] 2.2 Check the migrated entry (read-only): minor version 4, no planned section in its options, the mapping, defrost statistics and season dates unchanged, and the options form without a planned section; verify the sensors exist with the same entity IDs and their figures match those before the restart

## Workflow follow-up

- Archive the change after the final whole-change review.
- Remove the "Cost per kWh of heat" entry from `private/BACKLOG.md` once the change is archived.

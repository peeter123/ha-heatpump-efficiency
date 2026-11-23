# Spec Delta

## ADDED Requirements

### Requirement: No cost settings
The setup and options forms SHALL offer no price source or other cost setting, and no planned section. The
integration SHALL create no cost entities.

#### Scenario: Setup form
- **WHEN** the setup form opens
- **THEN** it shows the Heating, Hot water, Cooling, Overall and season sections, and no planned section or price source field

#### Scenario: Options form
- **WHEN** the user opens Configure on an existing heat pump
- **THEN** the form shows no planned section or price source field

### Requirement: Planned section of existing entries
An entry stored with a planned section SHALL have that section, including a stored price source, dropped once when
it is first loaded by a version without the section. Every other stored value SHALL stay unchanged.

#### Scenario: Price source dropped
- **WHEN** an entry with Heating, Overall, season dates and a price source in the planned section is loaded by this version
- **THEN** the entry has no planned section, and its mapping and season dates are unchanged

#### Scenario: Entry without a planned section
- **WHEN** an entry without a planned section is loaded by this version
- **THEN** its stored values are unchanged

## MODIFIED Requirements

### Requirement: Mapping changed later
The user SHALL be able to change the mapping, the measured-since dates, the season dates, the cooling efficiency
unit and the defrost heat statistics after setup; the sensors then use the new configuration from the next update,
every season is recalculated with the new dates, and services removed from the mapping lose their sensors.

#### Scenario: Meter replaced
- **WHEN** the user changes Overall electricity to a new meter's statistic
- **THEN** the Overall sensors keep their entity IDs and use the new statistic

#### Scenario: Season dates changed
- **WHEN** the user changes the heating season from 1 October to 30 April into 15 September to 15 May
- **THEN** the heating season sensors and every season in their history use the new dates from the next update

#### Scenario: Defrost statistic added
- **WHEN** the user adds a defrost heat statistic to Heating in the options
- **THEN** the Heating and Overall sensors keep their entity IDs and show corrected figures from the next update

### Requirement: Defrost slot of existing entries
An entry created with the planned defrost slot SHALL have that value moved once into the Heating section's defrost
field, when it is first loaded by a version with defrost fields. A slot value that is also an output or electrical
statistic of the entry SHALL be dropped instead of moved. Every other mapped value SHALL stay unchanged; the
planned section itself is then dropped as in "Planned section of existing entries".

#### Scenario: Slot moved to Heating
- **WHEN** an entry with Heating, Overall, a price source and a planned defrost heat statistic is loaded by this version
- **THEN** the entry stores that statistic as the Heating defrost heat, has no planned section, and its other mapped values are unchanged

#### Scenario: Entry without a defrost slot
- **WHEN** an entry without a planned defrost heat statistic is loaded by this version
- **THEN** its mapping and season dates are unchanged

#### Scenario: Slot holding an output statistic
- **WHEN** an entry whose planned defrost heat statistic is also its Heating output statistic is loaded by this version
- **THEN** the entry has no Heating defrost heat and no planned section, and the Heating output and electricity are unchanged

## REMOVED Requirements

### Requirement: Price source slot
**Reason**: Cost per kWh of heat is dropped from the integration: with a dynamic tariff it needs the price at each
moment times the energy at that moment, which a ratio of statistics changes cannot give without averaging the
price, and the tariff policy (solar, net metering, taxes, fixed charges) differs per installation.
**Migration**: Nothing to do for the owner. The migration in "Planned section of existing entries" drops a stored
price source; an owner who wants cost per kWh of heat builds a cost counter in their own Home Assistant
configuration.

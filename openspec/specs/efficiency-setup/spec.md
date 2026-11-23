# efficiency-setup Specification

## Purpose

Lets any heat pump owner add a heat pump through the Home Assistant UI by mapping their own energy statistics to
services and Overall, and change that mapping later, without editing YAML.

## Requirements

### Requirement: Heat pump added through the UI
The integration SHALL be added through Home Assistant's integrations UI, once per heat pump, with a name. For
Heating, Hot water, Cooling and Overall the user SHALL be able to choose one or more output energy statistics and
one or more electrical energy statistics; a service left without output and electrical statistics is not
configured and gets no sensors. At least one service or Overall SHALL be configured.

#### Scenario: Heating only
- **WHEN** the user maps only Heating output and electricity
- **THEN** only Heating sensors and series are created

#### Scenario: Nothing mapped
- **WHEN** the user submits the form without any mapping
- **THEN** the form shows an error and nothing is created

#### Scenario: Output without electricity
- **WHEN** the user maps Cooling output but no Cooling electricity
- **THEN** the form shows an error on the Cooling section that asks for its electricity statistics

#### Scenario: Two heat pumps
- **WHEN** the user adds the integration twice with different names and mappings
- **THEN** each has its own sensors, and neither affects the other

### Requirement: Mapped statistics validated
The integration SHALL accept only statistics that exist in the recorder, have a running sum and have an energy
unit convertible to kWh, and SHALL show which choice fails and why. External statistics (imported by another
integration, without 5-minute statistics) SHALL be accepted and are read hourly (`period-efficiency`).

#### Scenario: External statistic
- **WHEN** the user chooses an external energy statistic with a running sum as Overall electricity
- **THEN** it is accepted

#### Scenario: Power instead of energy
- **WHEN** the user chooses a statistic in W as electricity
- **THEN** the form shows that the statistic is not an energy statistic

#### Scenario: Mean-only statistic
- **WHEN** the user chooses a statistic without a running sum
- **THEN** the form shows that the statistic has no running sum

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

### Requirement: Measured-since dates
For each service and Overall the integration SHALL let the user optionally set the date from which its
statistics are measured rather than estimated, and SHALL use it only to mark estimated history
(`efficiency-series`).

#### Scenario: Date stored
- **WHEN** the user sets 13 November 2026 as Hot water's measured-since date
- **THEN** the setting is kept and shown when the configuration is opened again

### Requirement: Season dates
The setup and options forms SHALL let the user set a start and an end month and day for the heating season and
for the cooling season, prefilled from Home Assistant's latitude, and SHALL store all four dates in the entry. A
date left empty, a start equal to its end, a day that does not exist in its month, or 29 February SHALL be
rejected with an error.

#### Scenario: Northern hemisphere defaults
- **WHEN** Home Assistant's latitude is 52.0 and the setup form opens
- **THEN** the heating season is prefilled as 1 October to 30 April and the cooling season as 1 June to 30 September

#### Scenario: Southern hemisphere defaults
- **WHEN** Home Assistant's latitude is -33.9 and the setup form opens
- **THEN** the heating season is prefilled as 1 April to 31 October and the cooling season as 1 December to 28 February

#### Scenario: Same start and end
- **WHEN** the user sets the cooling season to start and end on 1 June
- **THEN** the form shows an error on the seasons and nothing is stored

#### Scenario: Day not in the month
- **WHEN** the user sets the heating season to end on 31 April
- **THEN** the form shows an error on the seasons and nothing is stored

#### Scenario: Date left empty
- **WHEN** the user clears the day of the heating season's end and submits
- **THEN** the form shows an error on the seasons and nothing is stored

#### Scenario: Dates stored
- **WHEN** the user saves the heating season as 15 September to 15 May
- **THEN** those dates are kept and shown when the configuration is opened again

### Requirement: Season dates for existing entries
An entry created before season dates existed SHALL get the latitude defaults stored in the entry once, when it is
first loaded by a version with seasons, without changing its mapping.

#### Scenario: Entry from the previous version
- **WHEN** an entry without season dates is loaded and Home Assistant's latitude is 52.0
- **THEN** the entry stores the heating season 1 October to 30 April and the cooling season 1 June to 30 September, and its mapping is unchanged

### Requirement: Cooling efficiency unit
The user SHALL be able to choose the cooling efficiency unit, W/W (the default) or BTU/Wh, when Cooling is
configured, and the choice SHALL be stored in the entry and shown when the configuration is opened again.

#### Scenario: Default unit
- **WHEN** the user configures Cooling without choosing a unit
- **THEN** the cooling efficiency unit is W/W

#### Scenario: Unit stored
- **WHEN** the user chooses BTU/Wh for Cooling
- **THEN** BTU/Wh is kept and shown when the configuration is opened again

### Requirement: Warning before a cooling unit change
When the user changes the cooling efficiency unit in the options and any Cooling sensor already has long-term
statistics, the options flow SHALL show a confirmation step that explains that Home Assistant cannot convert
those statistics and will report the unit change, and SHALL store the change only after confirmation.

#### Scenario: Statistics exist
- **WHEN** the Cooling sensors have long-term statistics and the user changes the cooling unit from W/W to BTU/Wh (live check)
- **THEN** the confirmation step is shown, and closing it leaves the unit at W/W

#### Scenario: No statistics yet
- **WHEN** no Cooling sensor has long-term statistics and the user changes the cooling unit
- **THEN** the change is stored without a confirmation step

### Requirement: Defrost heat statistics
The Heating and Hot water sections SHALL offer an optional defrost heat field of one or more statistics, summed,
validated as in "Mapped statistics validated" and stored in the entry. A defrost field alone SHALL NOT configure
its service. Cooling and Overall SHALL have no defrost field.

#### Scenario: Defrost statistic stored
- **WHEN** the user maps Heating output and electricity and chooses a defrost heat statistic for Heating
- **THEN** the defrost statistic is stored under Heating and shown when the configuration is opened again

#### Scenario: Defrost statistic in W
- **WHEN** the user chooses a statistic in W as the Hot water defrost heat
- **THEN** the form shows on the Hot water section that the statistic is not an energy statistic

#### Scenario: Defrost alone does not configure a service
- **WHEN** the user maps Overall output and electricity and only a defrost heat statistic in the Heating section
- **THEN** the entry is created with Overall sensors and no Heating sensors

#### Scenario: Only a defrost statistic
- **WHEN** the user maps only a Heating defrost heat statistic and nothing else
- **THEN** the form shows an error and nothing is created

### Requirement: Defrost statistic mapped once
The integration SHALL reject a defrost statistic that is chosen in both the Heating and the Hot water section, or
that is also chosen as an output or electrical statistic, with an error on the section of the defrost field.

#### Scenario: Same statistic in both sections
- **WHEN** the user chooses the same defrost heat statistic for Heating and for Hot water
- **THEN** the form shows an error that a defrost statistic may be mapped only once, and nothing is stored

#### Scenario: Defrost statistic used as output
- **WHEN** the user chooses the Heating output statistic also as the Heating defrost heat statistic
- **THEN** the form shows that error on the Heating section, and nothing is stored

### Requirement: Defrost statistic without a use
A defrost statistic in the section of a service that is not configured SHALL correct Overall only. When Overall is
not configured either, the integration SHALL reject it with an error on that section.

#### Scenario: Nothing to correct
- **WHEN** the user maps Hot water output and electricity and a defrost heat statistic in the Heating section, and Overall is not configured
- **THEN** the form shows on the Heating section that its defrost statistic corrects nothing, and nothing is stored

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

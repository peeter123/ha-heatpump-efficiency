# Spec Delta

## ADDED Requirements

### Requirement: Price source slot
The user MAY choose a price source for cost per kWh of heat. The integration SHALL store it and show it when the
configuration is opened again, and SHALL NOT create entities for it or compute anything from it yet.

#### Scenario: Slot stored only
- **WHEN** the user chooses a price source
- **THEN** it is stored and shown again, and no cost entity is created

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
statistic of the entry SHALL be dropped instead of moved. The price source and every other value SHALL stay
unchanged.

#### Scenario: Slot moved to Heating
- **WHEN** an entry with Heating, Overall, a price source and a planned defrost heat statistic is loaded by this version
- **THEN** the entry stores that statistic as the Heating defrost heat, keeps the price source in the planned section, and its other values are unchanged

#### Scenario: Entry without a defrost slot
- **WHEN** an entry without a planned defrost heat statistic is loaded by this version
- **THEN** its mapping, season dates and planned section are unchanged

#### Scenario: Slot holding an output statistic
- **WHEN** an entry whose planned defrost heat statistic is also its Heating output statistic is loaded by this version
- **THEN** the entry has no Heating defrost heat, the planned section keeps only the price source, and the Heating output and electricity are unchanged

## MODIFIED Requirements

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

### Requirement: Mapping changed later
The user SHALL be able to change the mapping, the measured-since dates, the season dates, the cooling efficiency
unit, the defrost heat statistics and the price source after setup; the sensors then use the new configuration
from the next update, every season is recalculated with the new dates, and services removed from the mapping lose
their sensors.

#### Scenario: Meter replaced
- **WHEN** the user changes Overall electricity to a new meter's statistic
- **THEN** the Overall sensors keep their entity IDs and use the new statistic

#### Scenario: Season dates changed
- **WHEN** the user changes the heating season from 1 October to 30 April into 15 September to 15 May
- **THEN** the heating season sensors and every season in their history use the new dates from the next update

#### Scenario: Defrost statistic added
- **WHEN** the user adds a defrost heat statistic to Heating in the options
- **THEN** the Heating and Overall sensors keep their entity IDs and show corrected figures from the next update

## REMOVED Requirements

### Requirement: Cost and defrost slots
**Reason**: The defrost heat statistic is now used: it moves from the planned section into the Heating and Hot
water sections ("Defrost heat statistics"). The price source stays stored only ("Price source slot").
**Migration**: An existing planned defrost heat value is moved into the Heating section once
("Defrost slot of existing entries"); no action is needed from the user.

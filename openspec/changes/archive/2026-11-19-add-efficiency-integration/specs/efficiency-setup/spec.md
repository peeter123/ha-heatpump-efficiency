## Purpose

Lets any heat pump owner add a heat pump through the Home Assistant UI by mapping their own energy statistics to
services and Overall, and change that mapping later, without editing YAML.

## ADDED Requirements

### Requirement: Heat pump added through the UI
The integration SHALL be added through Home Assistant's integrations UI, once per heat pump, with a name. For
Heating, Hot water, Cooling and Overall the user SHALL be able to choose one or more output energy statistics and
one or more electrical energy statistics; a service left without statistics is not configured and gets no
sensors. At least one service or Overall SHALL be configured.

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
The user SHALL be able to change the mapping, the measured-since dates and the optional slots after setup; the
sensors then use the new mapping from the next update, and services removed from the mapping lose their sensors.

#### Scenario: Meter replaced
- **WHEN** the user changes Overall electricity to a new meter's statistic
- **THEN** the Overall sensors keep their entity IDs and use the new statistic

### Requirement: Measured-since dates
For each service and Overall the integration SHALL let the user optionally set the date from which its
statistics are measured rather than estimated, and SHALL use it only to mark estimated history
(`efficiency-series`).

#### Scenario: Date stored
- **WHEN** the user sets 13 November 2026 as Hot water's measured-since date
- **THEN** the setting is kept and shown when the configuration is opened again

### Requirement: Cost and defrost slots
The user MAY choose a price source for cost per kWh of heat and a defrost heat statistic. The integration SHALL
store them and show them when the configuration is opened again, and SHALL NOT create entities for them or
compute anything from them yet.

#### Scenario: Slots stored only
- **WHEN** the user chooses a price source and a defrost heat statistic
- **THEN** both are stored, and no cost or defrost entity is created

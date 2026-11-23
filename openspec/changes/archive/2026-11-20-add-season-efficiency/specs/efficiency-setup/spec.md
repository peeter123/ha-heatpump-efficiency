# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Mapping changed later
The user SHALL be able to change the mapping, the measured-since dates, the season dates, the cooling efficiency
unit and the optional slots after setup; the sensors then use the new configuration from the next update, every
season is recalculated with the new dates, and services removed from the mapping lose their sensors.

#### Scenario: Meter replaced
- **WHEN** the user changes Overall electricity to a new meter's statistic
- **THEN** the Overall sensors keep their entity IDs and use the new statistic

#### Scenario: Season dates changed
- **WHEN** the user changes the heating season from 1 October to 30 April into 15 September to 15 May
- **THEN** the heating season sensors and every season in their history use the new dates from the next update

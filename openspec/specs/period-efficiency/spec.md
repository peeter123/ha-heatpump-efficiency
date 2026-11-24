# period-efficiency Specification

## Purpose

Shows a heat pump's efficiency per service and overall for today, month to date, year to date and the rolling
12 months as a ratio of energy changes from Home Assistant's long-term statistics, never as a time average of
instantaneous COPs.

## Requirements

### Requirement: Efficiency is a ratio of energy changes
The efficiency of a service or Overall over a period SHALL be the sum of the `change` of its mapped output
statistics divided by the sum of the `change` of its mapped electrical statistics over that period, with all
energies converted to kWh. It SHALL be unknown when the electrical change is below 0.1 kWh. When defrost heat
statistics are mapped for the service or Overall, the output change SHALL first be reduced by their change
(`defrost-correction`).

#### Scenario: Month with both counters
- **WHEN** over a month the hot water output rose by 180.0 kWh and its electricity by 50.0 kWh
- **THEN** hot water efficiency for that month is 3.60

#### Scenario: Too little electricity
- **WHEN** over a day the cooling electricity rose by 0.05 kWh
- **THEN** the cooling efficiency for that day is unknown, not a large number

#### Scenario: Several output statistics summed
- **WHEN** Overall is mapped to two output statistics that rose by 30.0 kWh and 2.0 kWh and one electrical statistic that rose by 8.0 kWh
- **THEN** the Overall efficiency is 4.00

#### Scenario: Units converted
- **WHEN** an electrical statistic is recorded in Wh and rose by 2500 Wh while the output rose by 10.0 kWh
- **THEN** the efficiency is 4.00

#### Scenario: Time average not used
- **WHEN** a live COP sensor averaged 4.0 over a day whose hot water output rose by 8.91 kWh and electricity by 2.86 kWh
- **THEN** the hot water efficiency for that day is 3.12

#### Scenario: Defrost heat subtracted
- **WHEN** over a month the hot water output rose by 180.0 kWh, its defrost statistic by 5.0 kWh and its electricity by 50.0 kWh
- **THEN** hot water efficiency for that month is 3.50

#### Scenario: Defrost statistic in Wh
- **WHEN** a defrost statistic is recorded in Wh and rose by 2000 Wh while the output rose by 10.0 kWh and the electricity by 2.0 kWh
- **THEN** the efficiency is 4.00

### Requirement: Period sensors
For each configured service (Heating, Hot water, Cooling) and for Overall the integration SHALL provide sensors
for today, month to date, year to date and the rolling 12 months, each with state class measurement and 2
decimals. They SHALL have no unit, except the Cooling sensors when the cooling efficiency unit is BTU/Wh, which
SHALL have the unit `BTU/Wh`.

#### Scenario: Sensors per service
- **WHEN** Heating and Overall are configured
- **THEN** eight period sensors exist: today, month to date, year to date and rolling 12 months for each

#### Scenario: Cooling unit shown
- **WHEN** the cooling efficiency unit is BTU/Wh
- **THEN** the Cooling period and season sensors have the unit `BTU/Wh`, and with W/W they have no unit

### Requirement: Periods in the Home Assistant time zone
Periods SHALL end now and start at local midnight in the Home Assistant time zone: today on the current day, month
to date on the 1st, year to date on 1 January, and the rolling 12 months on the same calendar day one year earlier,
or the last day of that month when that day does not exist. In a time zone whose offset is not a whole number of
hours, a day SHALL start at the first whole UTC hour at or after local midnight, because Home Assistant's hourly
statistics start on UTC hours.

#### Scenario: Month to date includes today
- **WHEN** on the 17th the hot water counters rose by 60.0 kWh output and 18.0 kWh electricity from the 1st to midnight, and by 2.0 kWh and 0.5 kWh since midnight
- **THEN** hot water month to date reports 3.35

#### Scenario: Year to date on the 1st of a month
- **WHEN** it is 1 March 10:00 and the counters have statistics since 1 January
- **THEN** year to date covers 1 January 00:00 to now and month to date covers 1 March 00:00 to now

#### Scenario: Rolling 12 months across a leap day
- **WHEN** it is 1 March 2029 and the rolling 12 months are computed
- **THEN** they start at 1 March 2028 00:00 local

#### Scenario: Rolling 12 months from 29 February
- **WHEN** it is 29 February 2028
- **THEN** the rolling 12 months start at 28 February 2027 00:00 local

#### Scenario: Daylight saving change
- **WHEN** today is the day clocks go forward or back in the Home Assistant time zone
- **THEN** today starts at local midnight and the periods neither overlap nor leave a gap at that day

#### Scenario: Half-hour time zone
- **WHEN** the Home Assistant time zone is Asia/Kolkata (UTC+05:30), whose hourly statistics start at half past the local hour
- **THEN** each day, and so today, month to date, year to date and the rolling 12 months, starts at 00:30 local, the first hour boundary of the statistics at or after local midnight, and no energy between 23:30 and 00:30 is missed or counted twice

#### Scenario: Kept out of the logbook
- **WHEN** a period sensor changes value
- **THEN** it has state class measurement, so Home Assistant writes no logbook entry for it

### Requirement: Period start limited to the mapped history
When a mapped statistic's first statistics hour lies after a period's start, the period SHALL start at the first
day start at or after the latest first statistics hour among the output and electrical statistics of that service
or Overall, and the sensor SHALL report that effective start. A defrost heat statistic SHALL NOT limit it
(`defrost-correction`). The daily and monthly series are limited the same way. When that limited period has not
begun, the sensor SHALL be unknown.

#### Scenario: Electricity history shorter than output history
- **WHEN** the output statistic has statistics since January and the electrical statistic since 13 November 00:00, and year to date is computed on 17 November
- **THEN** year to date uses 13 November 00:00 to now for both counters and reports 13 November as its effective start

#### Scenario: History starting mid-day
- **WHEN** the electrical statistic's first statistics hour is 13 November 14:00
- **THEN** the effective start is 14 November 00:00, so no heat without matching electricity is counted

#### Scenario: Limited period not begun
- **WHEN** the electrical statistic's first statistics hour is today 09:00
- **THEN** today, month to date, year to date and rolling 12 months are unknown until tomorrow

#### Scenario: Defrost history shorter than the other counters
- **WHEN** the output and electrical statistics have statistics since January and the defrost heat statistic since 18 November 10:00, and year to date is computed on 22 November
- **THEN** year to date starts in January and reports January as its effective start

### Requirement: Never a partial figure
A sensor SHALL be unknown, never a figure computed from part of its period, when any statistics read that its
period needs failed, did not cover the whole period, or was made before one of its mapped statistics had
statistics up to the end of that read, and SHALL be unknown when any of its mapped statistics has no statistics
at all. Such a read SHALL be retried at the next update.

#### Scenario: Month read fails
- **WHEN** the read of completed months fails while the reads of days and today succeed
- **THEN** year to date and rolling 12 months are unknown and today and month to date are reported

#### Scenario: History extended by a backfill
- **WHEN** the completed months were read while the effective start was 13 November, and a backfill later moves the electrical statistic's first statistics hour to January
- **THEN** year to date is unknown, not a figure from 13 November onwards, until the completed months have been read again for the new start, and is then reported from 1 January

#### Scenario: Sensor offline
- **WHEN** the electrical sensor of a service has had no statistics since 08:20 and it is 10:20
- **THEN** every period of that service ends at 08:20 for both counters, so no output without matching electricity is counted

#### Scenario: New statistic without an hourly row
- **WHEN** the integration is set up while a mapped electrical statistic has only 5-minute statistics from today
- **THEN** every period of that service is unknown until the next day, not a figure from the output's whole history

#### Scenario: Lagging statistic
- **WHEN** a mapped statistic's statistics for yesterday evening are not yet there when the completed days are read after midnight
- **THEN** the periods of that service that include yesterday are unknown, and the completed days are read again at each update until that statistic has caught up

#### Scenario: Statistic without data
- **WHEN** a mapped electrical statistic has no statistics
- **THEN** every sensor of that service is unknown, not 0

### Requirement: Energy attributes
Each period sensor SHALL carry the output energy and the electrical energy of its period in kWh and the
effective start of its period as attributes, also when the ratio is unknown because of the 0.1 kWh rule.

#### Scenario: Inputs visible
- **WHEN** hot water month to date reports 3.35 from 62.0 kWh output and 18.5 kWh electricity
- **THEN** its attributes show 62.0 kWh output and 18.5 kWh electricity

### Requirement: Update timing
The sensors SHALL update every 5 minutes after Home Assistant has compiled the 5-minute statistics, so each
reflects the counters up to the last completed 5-minute period, and after start-up and after the configuration
changes. Completed days and months SHALL be read again only when a day or month completes, the configuration
changes, a statistic's history start moves, or a previous read failed or was incomplete, not on every update.

#### Scenario: Shortly after midnight
- **WHEN** the update after 00:05 local runs
- **THEN** today covers 00:00 to 00:05, yesterday is counted as a completed day, and no energy is counted twice or missed

#### Scenario: Cached history
- **WHEN** ten updates run within the same day
- **THEN** completed months and completed days are read once that day, and only today is read on each update

### Requirement: External statistics read hourly
A service or Overall with an external statistic (one that has no 5-minute statistics) SHALL reflect its counters
up to the last hour for which all its statistics have hourly statistics.

#### Scenario: External statistic
- **WHEN** Overall electricity is an external statistic with hourly statistics up to 14:00 and it is 14:20
- **THEN** every Overall period ends at 14:00 for both counters, and the other services still end at 14:15

### Requirement: Cooling efficiency in the chosen unit
Every Cooling figure (the period sensors, the daily and monthly series and the cooling season with its history)
SHALL be shown in the cooling efficiency unit: W/W, or BTU/Wh as the W/W ratio times 3.412142, rounded to 2
decimals after the conversion. Energies SHALL stay in kWh, the 0.1 kWh rule SHALL be unchanged, and Overall and
the other services SHALL stay W/W.

#### Scenario: Cooling in BTU/Wh
- **WHEN** the cooling unit is BTU/Wh and over a month the cooling output rose by 470.0 kWh and its electricity by 100.0 kWh
- **THEN** the Cooling month to date is 16.04, with 470.0 kWh and 100.0 kWh as its energies

#### Scenario: Overall not converted
- **WHEN** the cooling unit is BTU/Wh
- **THEN** the Overall and Heating sensors still show W/W ratios without a unit

#### Scenario: Too little electricity in BTU/Wh
- **WHEN** the cooling unit is BTU/Wh and over a day the cooling electricity rose by 0.05 kWh
- **THEN** the Cooling efficiency for that day is unknown

### Requirement: Sensor icons
Every sensor of the integration, period and season sensors alike, SHALL get its icon from the integration's icon
translations by its translation key, one icon per service: the same icon for all Heating sensors, one for Hot
water, one for Cooling and one for Overall, each different from the others. The sensors SHALL set no icon in code.

#### Scenario: An icon for every translation key
- **WHEN** the test suite reads `icons.json` and `translations/en.json`
- **THEN** the sensor keys in `icons.json` equal the sensor translation keys in `translations/en.json`, each has a
  `default` starting with `mdi:`, sensors of one service share their icon, and the four services have four
  different icons

#### Scenario: Icons on the live installation (live check)
- **WHEN** the released version is installed and the entry has loaded
- **THEN** each sensor shows its service's icon in the entity list and on the dashboard, and no sensor shows a
  missing-icon placeholder

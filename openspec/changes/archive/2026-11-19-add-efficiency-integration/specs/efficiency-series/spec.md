## Purpose

Provides daily and monthly efficiency series, computed as ratios of energy changes, for charts of a heat pump's
efficiency over time, and marks the points that rest on estimated history.

## ADDED Requirements

### Requirement: Daily and monthly series
For each configured service and Overall the integration SHALL provide the efficiency of each of the last 31 days
(today included, so far) and of each of the last 24 calendar months (the current month included, so far), each
computed by the rule of `period-efficiency` for that day or month. A day or month without a known efficiency SHALL
have no point, not 0. The series SHALL be kept out of Home Assistant's recorder.

#### Scenario: Cooling outside the season
- **WHEN** a winter month has no cooling electricity
- **THEN** the cooling monthly series has no point for that month

#### Scenario: Same month last year
- **WHEN** the series is read in November 2026 and the counters have statistics since November 2025
- **THEN** the monthly series has a point for November 2025 and for November 2026 so far

#### Scenario: Not recorded
- **WHEN** Home Assistant records the sensor that carries the series
- **THEN** the series attributes are not stored in the recorder

### Requirement: Estimated history marked
When a measured-since date is configured for a service or Overall, each daily or monthly point and each period
sensor whose covered start lies before that date SHALL be marked as including estimated history. The covered
start is the start of the day, month or period, or the effective start (`period-efficiency`) where that cuts it.

#### Scenario: Month starting at the measured history
- **WHEN** hot water is measured since 13 November 2026 and its effective start is also 13 November 2026
- **THEN** the November 2026 point and year to date are not marked estimated

#### Scenario: Month spanning the switch-over
- **WHEN** hot water is measured since 13 November 2026 and the monthly series is computed
- **THEN** the point for November 2026 and all earlier points are marked estimated, and December 2026 is not

#### Scenario: No date configured
- **WHEN** no measured-since date is configured for Heating
- **THEN** no Heating point and no Heating sensor is marked estimated

### Requirement: Chart examples
The README SHALL give example dashboard cards that chart the daily and monthly series and show the period
sensors, and SHALL NOT use a statistics `mean` of a COP or efficiency sensor as a period figure.

#### Scenario: Example cards
- **WHEN** a user copies the README's example cards
- **THEN** each figure comes from this integration's sensors or series, and none uses `stat_type: mean` or `stat_types: [mean]`

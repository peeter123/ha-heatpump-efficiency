# season-efficiency Specification

## Purpose
Shows a heat pump's measured efficiency per heating and cooling season, and a history of past seasons, as a ratio
of energy changes from Home Assistant's long-term statistics, so seasons can be compared year to year.

## Requirements

### Requirement: Season sensors
The integration SHALL provide a heating season sensor for Heating and for Overall and a cooling season sensor for
Cooling, each only when that service or Overall is configured, with state class measurement and 2 decimals. Hot
water SHALL get no season sensor.

#### Scenario: Heating, Cooling and Overall configured
- **WHEN** Heating, Hot water, Cooling and Overall are configured
- **THEN** three season sensors exist: Heating heating season, Overall heating season and Cooling cooling season

#### Scenario: Cooling not configured
- **WHEN** only Heating is configured
- **THEN** only the Heating heating season sensor exists, and no cooling season sensor

### Requirement: Seasons from recurring dates
A season SHALL run from the start of its start day to the end of its end day, both in the Home Assistant time
zone and starting at a day start as defined in `period-efficiency`, recurring every year. A season whose start
day lies after its end day in the calendar SHALL cross the new year.

#### Scenario: Heating season crossing the new year
- **WHEN** the heating season runs from 1 October to 30 April
- **THEN** the season that starts on 1 October 2026 ends at the start of 1 May 2027

#### Scenario: Season within one year
- **WHEN** the cooling season runs from 1 June to 30 September
- **THEN** the 2026 season covers 1 June 2026 00:00 up to 1 October 2026 00:00

#### Scenario: End of February in a leap year
- **WHEN** a season ends on 28 February and the season ends in 2028
- **THEN** the season includes 29 February 2028

### Requirement: Season efficiency
The efficiency of a season SHALL follow the rules of `period-efficiency` for the season's range: the ratio of
energy changes, the 0.1 kWh rule, the start limited to the mapped history, the end at the last common statistics
while the season runs, and never a partial figure.

#### Scenario: Season ratio
- **WHEN** over a finished heating season the Heating output rose by 9000.0 kWh and its electricity by 2500.0 kWh
- **THEN** that season's Heating efficiency is 3.60

#### Scenario: Season cut by the history start
- **WHEN** the heating season started on 1 October 2026 and the Heating statistics start on 13 November 2026 14:00
- **THEN** the season is computed from 14 November 2026 00:00

#### Scenario: Finished season equals its days
- **WHEN** a finished season is computed and the same season is summed day by day from the day statistics
- **THEN** both give the same output and electrical energy

### Requirement: Sensor state between seasons
A season sensor's state SHALL be the efficiency of the current season so far while a season runs, and of the
last season between seasons. It SHALL be unknown when no season has begun within the mapped history.

#### Scenario: During the season
- **WHEN** it is 15 January 2027 and the heating season runs from 1 October to 30 April
- **THEN** the heating season sensors show the season from 1 October 2026 to now

#### Scenario: Between seasons
- **WHEN** it is 15 July 2027 and the heating season runs from 1 October to 30 April
- **THEN** the heating season sensors show the finished season from 1 October 2026 to 30 April 2027

#### Scenario: No season yet
- **WHEN** the Cooling statistics start on 13 November 2026 and the cooling season runs from 1 June to 30 September
- **THEN** the cooling season sensor is unknown until 1 June 2027

### Requirement: Season history
Each season sensor SHALL carry the list of every season from the one that contains the start of the mapped
history up to the current or last season, oldest first, with no cap. The list SHALL be kept out of Home
Assistant's recorder.

#### Scenario: Several years of history
- **WHEN** the Heating statistics start on 1 September 2023 and it is 15 January 2027
- **THEN** the history has the seasons starting 1 October 2023, 2024, 2025 and 2026

#### Scenario: Not recorded
- **WHEN** Home Assistant records a season sensor
- **THEN** the season history is not stored in the recorder

### Requirement: Season points
Each season in the history SHALL give its start (the effective start where the history cuts it), its end, its
efficiency, its output and electrical energy in kWh, and the flags `estimated`, `complete` and `ended`. A season
with an unknown efficiency SHALL keep its point, with the efficiency null.

#### Scenario: Unknown season kept
- **WHEN** a finished season's electrical energy is 0.05 kWh
- **THEN** its point is in the history with efficiency null and its energies shown

### Requirement: Complete and ended flags
A season SHALL be marked `complete` when its start is not cut by the start of the mapped history, and `ended`
when the season is over. The season sensor SHALL carry both flags of the season it shows.

#### Scenario: Season cut at its start
- **WHEN** the heating season started 1 October 2026 and the history starts 13 November 2026
- **THEN** that season is not complete

#### Scenario: Running season
- **WHEN** a heating season started 1 October 2026 within the history and it is 15 January 2027
- **THEN** that season is complete and not ended

#### Scenario: Finished whole season
- **WHEN** the heating season from 1 October 2025 to 30 April 2026 lies entirely within the history
- **THEN** that season is complete and ended

### Requirement: Estimated seasons
A season SHALL be marked `estimated` when its covered start lies before the start of the measured-since date of
its service or Overall, by the rule of `efficiency-series`.

#### Scenario: Season before the measured history
- **WHEN** Heating is measured since 13 November 2026 and the heating season started 1 October 2026 within the history
- **THEN** that season and the earlier ones are marked estimated

### Requirement: Finished seasons read once
A finished season SHALL be read when the entry loads, when it has just ended, when a mapped statistic's history
start moves, and again after a failed or incomplete read, not on every update. A failed or incomplete read SHALL
make only the seasons that need it unknown.

#### Scenario: Cached seasons
- **WHEN** ten updates run within the same day between seasons
- **THEN** the finished seasons are read at most once that day

#### Scenario: Season just ended
- **WHEN** the first update after the end of the heating season runs
- **THEN** that season is reported as ended and its figure covers the whole season, with no hour missed or counted twice

## MODIFIED Requirements

### Requirement: Finished seasons read once
A finished season SHALL be read when the entry loads, when it has just ended, when a mapped statistic's history
start moves, and again after a failed or incomplete read, not on every update. A failed read SHALL make the season
sensor unavailable only while the shown season needs it and no earlier readings of that boundary are kept; an
incomplete read SHALL make only the seasons that need it unknown.

#### Scenario: Cached seasons
- **WHEN** ten updates run within the same day between seasons
- **THEN** the finished seasons are read at most once that day

#### Scenario: Season just ended
- **WHEN** the first update after the end of the heating season runs
- **THEN** that season is reported as ended and its figure covers the whole season, with no hour missed or counted twice

#### Scenario: Boundary read fails
- **WHEN** the heating season has ended and the first read of its end boundary fails
- **THEN** the Heating and Overall season sensors are unavailable until the read succeeds, and the period sensors
  stay available

#### Scenario: Repeated boundary read fails
- **WHEN** a boundary was read with readings and its read on the following day fails
- **THEN** the season sensor stays available with the figure read before

#### Scenario: Running season needs a failed read
- **WHEN** the heating season is running and the read of completed months fails
- **THEN** the Heating and Overall season sensors are unavailable, as year to date is

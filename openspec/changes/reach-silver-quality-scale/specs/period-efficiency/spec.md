## MODIFIED Requirements

### Requirement: Never a partial figure
A sensor SHALL never show a figure computed from part of its period. It SHALL be unavailable while a statistics
read that its value needs has failed (see "Unavailable while a needed read fails"). It SHALL be unknown when a read
that its period needs did not cover the whole period, or was made before one of its mapped statistics had
statistics up to the end of that read, and when any of its mapped statistics has no statistics at all. Such a read
SHALL be retried at the next update.

#### Scenario: Month read fails
- **WHEN** the read of completed months fails while the reads of days and today succeed
- **THEN** year to date and rolling 12 months are unavailable and today and month to date are reported

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

## ADDED Requirements

### Requirement: Unavailable while a needed read fails
A sensor SHALL be unavailable while a statistics read that its value needs failed at its latest attempt, and
available again at the first update at which that read succeeds; every other sensor of the entry SHALL stay
available. A period sensor needs the recent read of its service or Overall and the reads its period's ranges use.
Every sensor needs the metadata, and a service's sensors its first statistics hours, until read once.

#### Scenario: Month read fails for one update
- **WHEN** the read of completed months fails at one update and succeeds at the next
- **THEN** year to date and rolling 12 months are unavailable after the first update and show their figures after
  the second, while today and month to date stay available throughout

#### Scenario: Recent read fails
- **WHEN** the read of today's 5-minute statistics fails
- **THEN** every period sensor of the services that read 5-minute statistics is unavailable, and the period
  sensors of a service that reads hourly statistics stay available

#### Scenario: Metadata never read
- **WHEN** the entry loads while the statistics metadata cannot be read
- **THEN** every sensor of the entry is unavailable until the metadata is read

#### Scenario: Later metadata failure
- **WHEN** the statistics metadata was read once and a later read of it fails
- **THEN** the sensors stay available and use the last metadata read

#### Scenario: Unknown is not unavailable
- **WHEN** every read succeeds and a period is unknown because it has not begun, a statistic has no data, or the
  electricity is below 0.1 kWh
- **THEN** the sensor is available and its state is unknown


### Requirement: Failed reads logged once
A failed statistics read SHALL be logged once when it fails or its error changes, and once when it works again,
at info level.

#### Scenario: Logged once
- **WHEN** the read of completed months fails at three updates in a row and then succeeds
- **THEN** the log has one info line that names the failed read and its error, and one info line when it works
  again

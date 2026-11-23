## Purpose

Tells the owner, through Home Assistant repairs, when a statistic the integration was set up with is missing,
unsuitable or no longer updating, instead of leaving sensors unknown without explanation.

## ADDED Requirements

### Requirement: Repair issue for a problem statistic
The integration SHALL raise one repair issue per heat pump and mapped statistic when that statistic no longer
exists, has no running sum, has a unit that is not an energy unit, or has had no new 5-minute statistics for
more than 2 hours (hourly statistics for an external statistic, which has no 5-minute statistics). The issue
SHALL name the heat pump, the statistic and the problem, and SHALL be removed when the problem is gone.

#### Scenario: Statistic renamed
- **WHEN** a mapped statistic is renamed in Home Assistant so its old ID no longer exists
- **THEN** a repair issue names the heat pump, the old statistic ID and that it no longer exists

#### Scenario: Unit changed
- **WHEN** a mapped statistic's unit changes to W
- **THEN** a repair issue says it is not an energy statistic

#### Scenario: Sensor stopped
- **WHEN** a mapped statistic has had no new 5-minute statistics for 3 hours
- **THEN** a repair issue says it has stopped updating since its last statistics time

#### Scenario: Problem resolved
- **WHEN** the statistic updates again or the mapping is changed to a valid statistic
- **THEN** the repair issue is removed at the next check

#### Scenario: Integration removed
- **WHEN** the heat pump's configuration is removed
- **THEN** its repair issues are removed

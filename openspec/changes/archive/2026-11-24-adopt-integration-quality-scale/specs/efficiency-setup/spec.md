# Spec Delta

## ADDED Requirements

### Requirement: Same heat pump not added twice
When a heat pump is added, the integration SHALL refuse it if any of its output statistics (of any service or
Overall) is already an output statistic of another entry of the integration. The setup SHALL end with a message that
the heat pump is already configured and names the shared statistics; nothing is created. Statistics shared between
sections of the same entry, and electrical or defrost statistics, SHALL NOT count.

#### Scenario: Output already used by another entry
- **WHEN** an entry maps statistic A as Heating output, and the user adds a heat pump whose Overall output includes A
- **THEN** the setup ends with the already-configured message naming A, and no entry is created

#### Scenario: Different outputs
- **WHEN** the user adds a second heat pump whose output statistics are all different from those of the existing
  entries
- **THEN** the entry is created, as before

#### Scenario: Overall reuses a service output in the same entry
- **WHEN** the user adds a heat pump whose Overall output includes its own Heating output statistic, and no other
  entry uses it
- **THEN** the entry is created

#### Scenario: Only electricity shared
- **WHEN** the user adds a heat pump that shares an electrical statistic with another entry but no output statistic
- **THEN** the entry is created

#### Scenario: Pure check
- **WHEN** the standard-library test suite calls the duplicate check with a mapping and the mappings of other
  entries
- **THEN** it returns exactly the sorted output statistic IDs that are an output in another entry, and nothing when
  there is no other entry

# Spec Delta

## MODIFIED Requirements

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

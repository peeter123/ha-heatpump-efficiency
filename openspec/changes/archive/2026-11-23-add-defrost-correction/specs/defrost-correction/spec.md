# Spec Delta

## Purpose

Corrects a heat pump's Heating, Hot water and Overall efficiency for the heat a defrost draws back out of the
water circuit, which many heat meters count as output, by subtracting a mapped defrost heat statistic.

## ADDED Requirements

### Requirement: Defrost heat subtracted from the output
When a service has defrost statistics (`efficiency-setup`), each of its figures (the four periods, the daily and
monthly series and the seasons) SHALL be the output change minus the defrost change, divided by the electrical
change over the same range, all in kWh. Heating SHALL subtract the Heating section's defrost statistics, Hot water
the Hot water section's, and Overall the sum of both. Cooling SHALL never be corrected.

#### Scenario: Corrected day
- **WHEN** over a day the Heating output rose by 36.8 kWh, its defrost statistic by 1.84 kWh and its electricity by 9.2 kWh
- **THEN** the Heating efficiency for that day is 3.80

#### Scenario: Overall subtracts both sections
- **WHEN** over a month the Overall output rose by 50.0 kWh and its electricity by 12.5 kWh, the Heating defrost statistic by 2.0 kWh and the Hot water defrost statistic by 0.5 kWh
- **THEN** the Overall efficiency for that month is 3.80

#### Scenario: Defrost of a service that is not configured
- **WHEN** only Overall is configured and a defrost statistic is mapped in the Heating section
- **THEN** no Heating sensors exist and the Overall figures subtract that defrost statistic

#### Scenario: Cooling not corrected
- **WHEN** Heating and Cooling are configured and a Heating defrost statistic rose by 1.0 kWh over a day
- **THEN** the Cooling figures for that day equal the cooling output change divided by its electricity change

#### Scenario: No defrost statistic
- **WHEN** no defrost statistic is mapped and over a day the Heating output rose by 36.8 kWh and its electricity by 9.2 kWh
- **THEN** the Heating efficiency for that day is 4.00, as without this correction

#### Scenario: Corrected figures on the live installation
- **WHEN** the defrost statistic is mapped under Heating on the live installation (live check)
- **THEN** today and the current heating season of Heating equal the output change minus the defrost change, divided by the electrical change, read directly from the statistics, to 0.001 kWh in each energy

### Requirement: Defrost history never limits a period
A defrost statistic SHALL NOT move or limit the effective start of its service or Overall (`period-efficiency`).
It SHALL count from the end of its first statistics hour, with the running sum at that point as its baseline:
before then it SHALL count as 0 kWh, in periods, points and seasons alike, whatever its first sum is.

#### Scenario: Defrost counter newer than the other counters
- **WHEN** the Heating output and electrical statistics have statistics since 1 January 2026, its defrost statistic since 18 November 2026 10:00, and year to date is computed on 22 November 2026
- **THEN** year to date starts on 1 January 2026, its effective start is 1 January 2026, and it subtracts the defrost heat from 18 November 2026 11:00 onwards

#### Scenario: Defrost statistic whose sum does not start at 0
- **WHEN** an external Heating defrost statistic's first statistics hour is 18 November 2026 10:00 with a sum of 500.0 kWh, its sum is 502.0 kWh at the end of that day, and over that day the Heating output rose by 36.8 kWh and its electricity by 9.2 kWh
- **THEN** the Heating defrost energy for that day is 2.0 kWh and its efficiency is 3.78, and month to date and year to date subtract 2.0 kWh for that day, not 502.0 kWh

#### Scenario: Finished season spanning the defrost counter's start
- **WHEN** the heating season from 1 October 2025 to 31 March 2026 has finished, and an external Heating defrost statistic's first statistics hour is 15 November 2025 10:00 with a sum of 500.0 kWh and its sum is 520.0 kWh at the season's end
- **THEN** that season's defrost energy is 20.0 kWh

#### Scenario: Finished season before the defrost counter
- **WHEN** the heating season from 1 October 2025 to 30 April 2026 has finished and the defrost statistic starts on 18 November 2026
- **THEN** that season's defrost energy is 0.0 kWh and its efficiency equals its uncorrected efficiency

#### Scenario: Defrost statistic without an hourly row yet
- **WHEN** a mapped defrost statistic has only 5-minute statistics from today
- **THEN** the Heating figures stay known, subtract the defrost heat of today's 5-minute statistics, and every period and point counts as starting before the defrost statistic

### Requirement: Defrost statistics are part of the read
The defrost statistics SHALL count as mapped statistics of their service or Overall for the rules "Never a partial
figure", "External statistics read hourly" and the end of every period at the last common statistics
(`period-efficiency`). A corrected figure SHALL be unknown, never the uncorrected figure, when its defrost energy
is unknown.

#### Scenario: Defrost statistic without data
- **WHEN** a mapped Heating defrost statistic has no statistics
- **THEN** every Heating and Overall sensor is unknown, not the uncorrected figure

#### Scenario: Defrost sensor offline
- **WHEN** the Heating defrost statistic has had no statistics since 08:20 and it is 10:20
- **THEN** every Heating period ends at 08:20 for the output, defrost and electrical statistics

#### Scenario: External defrost statistic
- **WHEN** the Heating defrost statistic is an external statistic with hourly statistics up to 14:00 and it is 14:20
- **THEN** every Heating period ends at 14:00

#### Scenario: Defrost read incomplete
- **WHEN** the completed days were read before the defrost statistic had statistics up to the end of that read
- **THEN** the Heating periods that include those days are unknown until the days are read again

### Requirement: Corrected output of zero or less
A corrected figure SHALL be unknown when its output change minus its defrost change is 0 kWh or less. The 0.1 kWh
rule SHALL stay on the electrical energy only; a corrected output above 0 SHALL give a figure.

#### Scenario: Defrost exceeds the output
- **WHEN** over a day the Heating output rose by 1.0 kWh, its defrost statistic by 1.2 kWh and its electricity by 0.5 kWh
- **THEN** the Heating efficiency for that day is unknown, there is no daily point for it, and its sensor shows 1.2 kWh as its defrost energy

#### Scenario: Small corrected output
- **WHEN** over a day the Heating output rose by 1.0 kWh, its defrost statistic by 0.8 kWh and its electricity by 0.5 kWh
- **THEN** the Heating efficiency for that day is 0.40

#### Scenario: Too little electricity
- **WHEN** over a day the Heating output rose by 2.0 kWh, its defrost statistic by 0.1 kWh and its electricity by 0.05 kWh
- **THEN** the Heating efficiency for that day is unknown

### Requirement: Defrost attributes
Each period and season sensor of a service with defrost statistics SHALL carry `defrost_energy` (kWh subtracted,
3 decimals), `efficiency_uncorrected` (by the same rules without the correction), and `defrost_since` (the latest
end of the first statistics hours of its defrost statistics, from which they are counted, ISO in the Home Assistant
time zone) only when its covered start lies before that point. `output_energy` SHALL stay the measured output. Without defrost statistics none is added.

#### Scenario: Inputs visible
- **WHEN** Heating today reports 3.80 from 36.8 kWh output, 1.84 kWh defrost heat and 9.2 kWh electricity
- **THEN** its attributes show 36.8 kWh output, 1.84 kWh defrost energy, 9.2 kWh electricity and 4.00 as the uncorrected efficiency

#### Scenario: Period starting before the defrost counter
- **WHEN** the defrost statistic's first statistics hour is 18 November 2026 10:00 and it is 22 November 2026
- **THEN** Heating year to date, month to date, rolling 12 months and the heating season show `defrost_since` 18 November 2026 11:00, and Heating today has no `defrost_since`

#### Scenario: Unknown corrected figure keeps its attributes
- **WHEN** a corrected period is unknown because its corrected output is 0 kWh or less
- **THEN** its output, defrost and electrical energies and its uncorrected efficiency are still shown

#### Scenario: No defrost statistic
- **WHEN** no defrost statistic is mapped for Hot water and none for Heating
- **THEN** the Hot water and Overall sensors have no `defrost_energy`, `efficiency_uncorrected` or `defrost_since`

### Requirement: Defrost marks on points
Each daily, monthly and season point of a service with defrost statistics SHALL carry `defrost_partial`, true when
the point's covered start lies before the latest end of the first statistics hours of those defrost statistics. Each such
season point SHALL also carry its `defrost_energy` in kWh. Points of a service without defrost statistics SHALL be
unchanged.

#### Scenario: Month spanning the defrost counter's start
- **WHEN** the defrost statistic's first statistics hour is 18 November 2026 10:00 and the monthly series is computed in December 2026
- **THEN** the point for November 2026 and all earlier points are `defrost_partial`, and December 2026 is not

#### Scenario: Day of the defrost counter's start
- **WHEN** the defrost statistic's first statistics hour is 18 November 2026 10:00
- **THEN** the daily point for 18 November 2026 is `defrost_partial` and the point for 19 November 2026 is not

#### Scenario: Season points
- **WHEN** the defrost statistic starts on 18 November 2026 and the heating seasons starting 1 October 2025 and 1 October 2026 are in the history
- **THEN** both points are `defrost_partial`, the 2025 point has a defrost energy of 0.0 kWh, and the 2026 point has the defrost heat since 18 November 2026

#### Scenario: No defrost marks without a defrost statistic
- **WHEN** no defrost statistic is mapped for Heating
- **THEN** the Heating daily, monthly and season points have no `defrost_partial` or `defrost_energy`

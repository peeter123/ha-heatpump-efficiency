# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

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

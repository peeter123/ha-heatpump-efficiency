# Spec Delta

## ADDED Requirements

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

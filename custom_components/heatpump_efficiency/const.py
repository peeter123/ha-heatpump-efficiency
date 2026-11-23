"""Constants for the Heat Pump Efficiency integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "heatpump_efficiency"

# homeassistant/const.py: Platform is EntityPlatforms (homeassistant/generated/entity_platforms.py).
PLATFORMS: Final = [Platform.SENSOR]

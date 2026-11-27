"""Sensor platform: four period sensors and a season sensor per configured service."""

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import efficiency as eff
from .const import DOMAIN
from .coordinator import HeatPumpEfficiencyConfigEntry, HeatPumpEfficiencyCoordinator
from .engine import PeriodResult, SeasonResult, ServiceResult
from .sensor_model import (
    SensorSpec,
    period_attributes,
    season_attributes,
    sensor_specs,
    stale_unique_ids,
)

PARALLEL_UPDATES = 0  # the coordinator updates; entities never poll


class EfficiencySensor(CoordinatorEntity[HeatPumpEfficiencyCoordinator], SensorEntity):
    """A period efficiency sensor: no unit (BTU/Wh for Cooling in BTU/Wh), state class measurement, 2 decimals."""

    _attr_has_entity_name = True
    # state_class makes the logbook skip it (components/logbook is_sensor_continuous);
    # components/sensor/const.py SensorStateClass.
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: HeatPumpEfficiencyCoordinator,
        entry: HeatPumpEfficiencyConfigEntry,
        spec: SensorSpec,
    ) -> None:
        """Set up the sensor of one service and period from its spec."""
        super().__init__(coordinator)
        self._spec = spec
        self._attr_unique_id = spec.unique_id
        self._attr_translation_key = spec.translation_key
        # components/sensor/entity.py SensorEntity.native_unit_of_measurement: set only for
        # Cooling in BTU/Wh. SensorEntity.state checks a unit only against DEVICE_CLASS_UNITS
        # (with a device class) and STATE_CLASS_UNITS (components/sensor/const.py, which
        # lists only measurement_angle), so a measurement sensor without a device class may
        # use BTU/Wh (design D5).
        self._attr_native_unit_of_measurement = spec.unit
        # helpers/device_registry.py DeviceInfo, DeviceEntryType.SERVICE
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _service(self) -> ServiceResult | None:
        data = self.coordinator.data
        return None if data is None else data.services.get(self._spec.service)

    @property
    def _period(self) -> PeriodResult | None:
        service = self._service
        return None if service is None else service.periods.get(self._spec.period)

    @property
    def _read_failed(self) -> bool:
        """Whether a read that the period needs failed (``PeriodResult.read_failed``)."""
        period = self._period
        return period is not None and period.read_failed

    @property
    def available(self) -> bool:
        """Whether the coordinator works and the period's own reads did not fail.

        helpers/update_coordinator.py CoordinatorEntity.available is the coordinator's
        last_update_success. helpers/entity.py Entity._stringify_state, called from
        Entity.__async_calculate_state, writes the state ``unavailable`` when this is
        False, and Entity.__async_calculate_state adds the state attributes and the
        extra state attributes only in its ``if available:`` branch. A missing result
        leaves the coordinator's value (design D5).
        """
        return super().available and not self._read_failed

    @property
    def native_value(self) -> float | None:
        """The efficiency, or None when the period is unknown."""
        period = self._period
        return None if period is None else period.efficiency

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The energies, the period start, the estimated mark and, when corrected, the defrost attributes."""
        period = self._period
        return None if period is None else period_attributes(period)


class TodayEfficiencySensor(EfficiencySensor):
    """Today; carries the daily series, which is not recorded."""

    # helpers/entity.py Entity.__init_subclass__ combines this class attribute with the
    # component's; a series of 31 points would otherwise count against the 16 KiB
    # state attribute limit (recorder/db_schema.py MAX_STATE_ATTRS_BYTES).
    _unrecorded_attributes = frozenset({"daily"})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the attributes with the daily series added."""
        attributes = super().extra_state_attributes
        service = self._service
        if attributes is None or service is None:
            return attributes
        return {**attributes, "daily": service.daily}


class MonthToDateEfficiencySensor(EfficiencySensor):
    """Month to date; carries the monthly series, which is not recorded."""

    _unrecorded_attributes = frozenset({"monthly"})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the attributes with the monthly series added."""
        attributes = super().extra_state_attributes
        service = self._service
        if attributes is None or service is None:
            return attributes
        return {**attributes, "monthly": service.monthly}


class SeasonEfficiencySensor(EfficiencySensor):
    """A season sensor: the current or last season; carries the season points, not recorded."""

    # helpers/entity.py Entity._unrecorded_attributes (combined by Entity.__init_subclass__);
    # the points of every season would count against recorder/db_schema.py MAX_STATE_ATTRS_BYTES.
    _unrecorded_attributes = frozenset({"seasons"})

    @property
    def _season(self) -> SeasonResult | None:
        service = self._service
        return None if service is None else service.season

    @property
    def _read_failed(self) -> bool:
        """Whether a read that the shown season needs failed (``SeasonResult.read_failed``)."""
        season = self._season
        return season is not None and season.read_failed

    @property
    def native_value(self) -> float | None:
        """The season's efficiency, or None when unknown or when there are no valid season dates."""
        season = self._season
        return None if season is None else season.efficiency

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The energies, the dates, the flags, the defrost attributes when corrected and the season points; None when unknown."""
        return season_attributes(self._season)


_CLASSES: dict[str, type[EfficiencySensor]] = {
    eff.PERIOD_TODAY: TodayEfficiencySensor,
    eff.PERIOD_MONTH_TO_DATE: MonthToDateEfficiencySensor,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeatPumpEfficiencyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Remove the sensors of services no longer mapped, then add the current ones."""
    coordinator = entry.runtime_data
    # helpers/entity_registry.py async_entries_for_config_entry and
    # EntityRegistry.async_remove (a missing entity is allowed).
    registry = er.async_get(hass)
    own = [
        registered
        for registered in er.async_entries_for_config_entry(registry, entry.entry_id)
        if registered.domain == "sensor" and registered.platform == DOMAIN
    ]
    stale = set(
        stale_unique_ids(
            entry.entry_id, coordinator.mapping, (r.unique_id for r in own)
        )
    )
    for registered in own:
        if registered.unique_id in stale:
            registry.async_remove(registered.entity_id)
    async_add_entities(
        (
            SeasonEfficiencySensor
            if spec.is_season
            else _CLASSES.get(spec.period, EfficiencySensor)
        )(coordinator, entry, spec)
        for spec in sensor_specs(entry.entry_id, coordinator.mapping)
    )

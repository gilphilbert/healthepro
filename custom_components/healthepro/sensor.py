"""Sensor entities for Health-e Pro School Menus (Today, Tomorrow, and -7..+7 day window)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, WINDOW_DAYS_FUTURE, WINDOW_DAYS_PAST
from .coordinator import ConfiguredMenuTarget, HealthEProCoordinator
from .entity import HealthEProEntity


@dataclass(frozen=True, kw_only=True)
class HealthEProDaySensorDescription(SensorEntityDescription):
    """Describes a relative-offset day sensor for a configured school menu."""

    day_offset: int


def _offset_key_and_name(offset: int) -> tuple[str, str]:
    """Map integer day offset in `[-7, +7]` to a stable key and friendly entity name."""
    if offset == 0:
        return "today", "Today"
    if offset == 1:
        return "tomorrow", "Tomorrow"
    if offset == -1:
        return "yesterday", "Yesterday"
    if offset > 1:
        return f"plus_{offset}_days", f"In {offset} Days"
    days_ago = abs(offset)
    return f"minus_{days_ago}_days", f"{days_ago} Days Ago"


def build_sensor_descriptions() -> tuple[HealthEProDaySensorDescription, ...]:
    """Build sensor descriptions for Today, Tomorrow, Past 7 Days, and Next 7 Days."""
    ordered_offsets = [
        0,
        1,
        *[offset for offset in range(2, WINDOW_DAYS_FUTURE + 1)],
        -1,
        *[-days_ago for days_ago in range(2, WINDOW_DAYS_PAST + 1)],
    ]
    descriptions: list[HealthEProDaySensorDescription] = []
    for offset in ordered_offsets:
        key, label = _offset_key_and_name(offset)
        descriptions.append(
            HealthEProDaySensorDescription(
                key=key,
                name=label,
                icon="mdi:food-apple-outline",
                day_offset=offset,
            )
        )
    return tuple(descriptions)


SENSOR_DESCRIPTIONS: tuple[HealthEProDaySensorDescription, ...] = (
    build_sensor_descriptions()
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Health-e Pro menu sensors from a config entry."""
    coordinator: HealthEProCoordinator = hass.data[DOMAIN]["coordinators"][
        entry.entry_id
    ]
    entities: list[HealthEProMenuSensor] = [
        HealthEProMenuSensor(coordinator, target, description)
        for target in coordinator.menu_targets
        for description in SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)


class HealthEProMenuSensor(HealthEProEntity, SensorEntity):
    """Sensor representing a school menu for a specific relative day offset."""

    entity_description: HealthEProDaySensorDescription

    def __init__(
        self,
        coordinator: HealthEProCoordinator,
        target: ConfiguredMenuTarget,
        description: HealthEProDaySensorDescription,
    ) -> None:
        """Initialize the day menu sensor."""
        super().__init__(coordinator, target)
        self.entity_description = description
        self._attr_unique_id = f"{target.key}_{description.key}"

    def _target_date(self) -> date:
        """Compute target calendar date in Home Assistant's configured local timezone."""
        return dt_util.now().date() + timedelta(
            days=self.entity_description.day_offset
        )

    @property
    def native_value(self) -> str:
        """Return non-blank menu summary (or configured 'No school' message)."""
        day_menu = self.coordinator.get_cached_day_menu(
            self.target.menu_id, self._target_date()
        )
        return day_menu.state_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full untruncated menu items, categories, notes, and metadata."""
        target_day = self._target_date()
        day_menu = self.coordinator.get_cached_day_menu(self.target.menu_id, target_day)
        attrs: dict[str, Any] = {
            **day_menu.to_dict(),
            "relative_day_offset": self.entity_description.day_offset,
            "organization_id": self.target.organization_id,
            "organization_name": self.target.organization_name,
            "school_id": self.target.school_id,
            "school_name": self.target.school_name,
            "menu_id": self.target.menu_id,
            "menu_name": self.target.menu_name,
        }

        if self.entity_description.day_offset == 0:
            today = dt_util.now().date()
            attrs["window_days"] = [
                self.coordinator.get_cached_day_menu(
                    self.target.menu_id, today + timedelta(days=offset)
                ).to_dict()
                for offset in range(-WINDOW_DAYS_PAST, WINDOW_DAYS_FUTURE + 1)
            ]

        return attrs

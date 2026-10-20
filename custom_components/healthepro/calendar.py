"""Calendar entity platform for per-day Health-e Pro School Menus."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import DayMenu
from .const import DOMAIN
from .coordinator import ConfiguredMenuTarget, HealthEProCoordinator
from .entity import HealthEProEntity


def _day_menu_to_calendar_event(day_menu: DayMenu) -> CalendarEvent:
    """Convert a `DayMenu` into an all-day `CalendarEvent` (never blank)."""
    lines: list[str] = []
    if day_menu.has_menu:
        for category, items in day_menu.categories.items():
            lines.append(f"{category}: {', '.join(items)}")
        for note in day_menu.notes:
            lines.append(note)
        description = "\n".join(lines)
    else:
        description = day_menu.status

    return CalendarEvent(
        start=day_menu.date,
        end=day_menu.date + timedelta(days=1),
        summary=day_menu.summary,
        description=description,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Health-e Pro calendar entities for each configured `(school, menu)`."""
    coordinator: HealthEProCoordinator = hass.data[DOMAIN]["coordinators"][
        entry.entry_id
    ]
    async_add_entities(
        [
            HealthEProCalendarEntity(coordinator, target)
            for target in coordinator.menu_targets
        ]
    )


class HealthEProCalendarEntity(HealthEProEntity, CalendarEntity):
    """Per-day calendar view entity for a configured school menu."""

    _attr_name = None
    _attr_icon = "mdi:calendar-month-outline"

    def __init__(
        self,
        coordinator: HealthEProCoordinator,
        target: ConfiguredMenuTarget,
    ) -> None:
        """Initialize the school menu calendar entity."""
        super().__init__(coordinator, target)
        self._attr_unique_id = f"{target.key}_calendar"

    @property
    def event(self) -> CalendarEvent:
        """Return today's all-day menu event (or explicit 'No school' event)."""
        today = dt_util.now().date()
        day_menu = self.coordinator.get_cached_day_menu(self.target.menu_id, today)
        return _day_menu_to_calendar_event(day_menu)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return per-day all-day events across `[start_date, end_date)`."""
        local_start = dt_util.as_local(start_date).date()
        local_end_dt = dt_util.as_local(end_date)
        # Exclusive midnight boundary in iCalendar / HA Calendar queries:
        if (
            local_end_dt.hour == 0
            and local_end_dt.minute == 0
            and local_end_dt.second == 0
            and local_end_dt.date() > local_start
        ):
            inclusive_end = local_end_dt.date() - timedelta(days=1)
        else:
            inclusive_end = local_end_dt.date()

        if inclusive_end < local_start:
            inclusive_end = local_start

        day_menus = await self.coordinator.async_get_range_menus(
            self.target.menu_id,
            local_start,
            inclusive_end,
        )
        return [_day_menu_to_calendar_event(dm) for dm in day_menus]

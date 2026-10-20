"""DataUpdateCoordinator and month cache for Health-e Pro School Menus."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    DayMenu,
    HealthEProApiClient,
    HealthEProApiError,
    make_empty_day_menu,
)
from .const import (
    CONF_MENUS,
    CONF_NO_MENU_MESSAGE,
    CONF_ORGANIZATION_ID,
    CONF_ORGANIZATION_NAME,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_NO_MENU_MESSAGE,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    MAX_SCAN_INTERVAL_HOURS,
    MIN_SCAN_INTERVAL_HOURS,
    MONTH_CACHE_TTL,
    WINDOW_DAYS_FUTURE,
    WINDOW_DAYS_PAST,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConfiguredMenuTarget:
    """Represents a single configured (organization, school, menu) tuple."""

    organization_id: int
    organization_name: str
    school_id: int
    school_name: str
    menu_id: int
    menu_name: str
    meal_type_id: int | None = None

    @property
    def key(self) -> str:
        """Stable identifier within Home Assistant."""
        return f"{self.organization_id}_{self.school_id}_{self.menu_id}"


@dataclass(slots=True)
class _CachedMonth:
    """Cached monthly `DayMenu` map with fetch timestamp."""

    fetched_at: datetime
    days: dict[date, DayMenu]


def _iter_dates(start_date: date, end_date: date) -> list[date]:
    """Return every date in `[start_date, end_date]` inclusive."""
    total_days = (end_date - start_date).days
    return [start_date + timedelta(days=offset) for offset in range(total_days + 1)]


def _months_in_range(start_date: date, end_date: date) -> list[tuple[int, int]]:
    """Return sorted unique `(year, month)` tuples spanned by `[start_date, end_date]`."""
    seen: set[tuple[int, int]] = set()
    ordered: list[tuple[int, int]] = []
    cursor = date(start_date.year, start_date.month, 1)
    limit = date(end_date.year, end_date.month, 1)
    while cursor <= limit:
        ym = (cursor.year, cursor.month)
        if ym not in seen:
            seen.add(ym)
            ordered.append(ym)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return ordered


class HealthEProCoordinator(
    DataUpdateCoordinator[dict[tuple[int, int, int], dict[date, DayMenu]]]
):
    """Coordinator managing periodic window refreshes and on-demand date queries."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: HealthEProApiClient,
    ) -> None:
        """Initialize the coordinator."""
        raw_hours = entry.options.get(
            CONF_SCAN_INTERVAL_HOURS,
            entry.data.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS),
        )
        scan_hours = max(
            MIN_SCAN_INTERVAL_HOURS,
            min(MAX_SCAN_INTERVAL_HOURS, int(raw_hours)),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(hours=scan_hours),
        )
        self.config_entry = entry
        self.client = client
        self._cache: dict[tuple[int, int, int], _CachedMonth] = {}
        self._fetch_locks: dict[tuple[int, int, int], asyncio.Lock] = {}

    @property
    def organization_id(self) -> int:
        """Configured district ID."""
        return int(self.config_entry.data[CONF_ORGANIZATION_ID])

    @property
    def organization_name(self) -> str:
        """Configured district name."""
        return str(self.config_entry.data.get(CONF_ORGANIZATION_NAME) or "")

    @property
    def no_menu_message(self) -> str:
        """Configured fallback message for days without menus (never blank)."""
        raw = self.config_entry.options.get(
            CONF_NO_MENU_MESSAGE,
            self.config_entry.data.get(CONF_NO_MENU_MESSAGE, DEFAULT_NO_MENU_MESSAGE),
        )
        return str(raw or "").strip() or DEFAULT_NO_MENU_MESSAGE

    @property
    def menu_targets(self) -> list[ConfiguredMenuTarget]:
        """Return all active `(school, menu)` selections from options or entry data."""
        raw_menus: list[dict[str, Any]] = self.config_entry.options.get(
            CONF_MENUS,
            self.config_entry.data.get(CONF_MENUS, []),
        )
        targets: list[ConfiguredMenuTarget] = []
        for item in raw_menus:
            targets.append(
                ConfiguredMenuTarget(
                    organization_id=self.organization_id,
                    organization_name=self.organization_name,
                    school_id=int(item["school_id"]),
                    school_name=str(item["school_name"]),
                    menu_id=int(item["menu_id"]),
                    menu_name=str(item["menu_name"]),
                    meal_type_id=(
                        int(item["meal_type_id"])
                        if item.get("meal_type_id") is not None
                        else None
                    ),
                )
            )
        return targets

    def _unique_menu_ids(self) -> list[int]:
        """Deduplicate `menu_id` across schools that share district-wide menus."""
        seen: set[int] = set()
        result: list[int] = []
        for target in self.menu_targets:
            if target.menu_id not in seen:
                seen.add(target.menu_id)
                result.append(target.menu_id)
        return result

    async def _async_fetch_month(
        self,
        menu_id: int,
        year: int,
        month: int,
        *,
        force_refresh: bool = False,
    ) -> dict[date, DayMenu]:
        """Fetch or reuse cached monthly menu data for `(menu_id, year, month)`."""
        cache_key = (menu_id, year, month)
        now = dt_util.utcnow()

        cached = self._cache.get(cache_key)
        if (
            not force_refresh
            and cached is not None
            and (now - cached.fetched_at) < MONTH_CACHE_TTL
        ):
            return cached.days

        lock = self._fetch_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = self._cache.get(cache_key)
            if (
                not force_refresh
                and cached is not None
                and (dt_util.utcnow() - cached.fetched_at) < MONTH_CACHE_TTL
            ):
                return cached.days

            days = await self.client.async_get_month_menu(
                organization_id=self.organization_id,
                menu_id=menu_id,
                year=year,
                month=month,
                no_menu_message=self.no_menu_message,
            )
            self._cache[cache_key] = _CachedMonth(fetched_at=dt_util.utcnow(), days=days)
            return days

    async def _async_update_data(
        self,
    ) -> dict[tuple[int, int, int], dict[date, DayMenu]]:
        """Refresh all months spanning `[today - 7 days, today + 7 days]`."""
        today = dt_util.now().date()
        window_start = today - timedelta(days=WINDOW_DAYS_PAST)
        window_end = today + timedelta(days=WINDOW_DAYS_FUTURE)
        months = _months_in_range(window_start, window_end)
        unique_menus = self._unique_menu_ids()

        if not unique_menus:
            return {}

        tasks = [
            self._async_fetch_month(menu_id, year, month, force_refresh=True)
            for menu_id in unique_menus
            for (year, month) in months
        ]

        try:
            await asyncio.gather(*tasks)
        except HealthEProApiError as err:
            raise UpdateFailed(f"Error fetching Health-e Pro menus: {err}") from err

        return {key: entry.days for key, entry in self._cache.items()}

    def get_cached_day_menu(self, menu_id: int, target_date: date) -> DayMenu:
        """Synchronously read a cached `DayMenu` or return explicit non-blank fallback."""
        month_map = self._cache.get(
            (menu_id, target_date.year, target_date.month)
        )
        if month_map is not None and target_date in month_map.days:
            return month_map.days[target_date]
        return make_empty_day_menu(target_date, self.no_menu_message)

    async def async_get_range_menus(
        self,
        menu_id: int,
        start_date: date,
        end_date: date,
    ) -> list[DayMenu]:
        """Return `DayMenu` entries for every day in `[start_date, end_date]`, fetching uncached months on demand."""
        months = _months_in_range(start_date, end_date)
        await asyncio.gather(
            *(self._async_fetch_month(menu_id, year, month) for year, month in months)
        )
        return [
            self.get_cached_day_menu(menu_id, current_day)
            for current_day in _iter_dates(start_date, end_date)
        ]

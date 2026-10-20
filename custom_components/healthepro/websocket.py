"""WebSocket API commands and shared query execution for Health-e Pro School Menus."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import HealthEProApiError
from .const import (
    DOMAIN,
    MAX_QUERY_RANGE_DAYS,
    WS_TYPE_GET_MENUS,
    WS_TYPE_LIST_MENUS,
)
from .coordinator import ConfiguredMenuTarget, HealthEProCoordinator


class InvalidMenuQueryError(ValueError):
    """Raised when date or filter arguments are invalid."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _parse_optional_date(raw: Any, field_name: str) -> date | None:
    """Parse an optional ISO date string (`YYYY-MM-DD`)."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        raise InvalidMenuQueryError(
            "invalid_date", f"`{field_name}` must be formatted as YYYY-MM-DD."
        )
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError as err:
        raise InvalidMenuQueryError(
            "invalid_date",
            f"Invalid `{field_name}` value '{raw}'; expected YYYY-MM-DD.",
        ) from err


def _parse_optional_int(raw: Any, field_name: str) -> int | None:
    """Coerce an optional integer ID filter (`menu_id`, `school_id`, `organization_id`)."""
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as err:
        raise InvalidMenuQueryError(
            "invalid_filter",
            f"Invalid `{field_name}` value '{raw}'; expected integer ID.",
        ) from err


def resolve_query_dates(
    raw_date: Any = None,
    raw_start_date: Any = None,
    raw_end_date: Any = None,
) -> tuple[date, date]:
    """Resolve optional date / date-range inputs, defaulting to today in HA local time."""
    single_date = _parse_optional_date(raw_date, "date")
    start_date = _parse_optional_date(raw_start_date, "start_date")
    end_date = _parse_optional_date(raw_end_date, "end_date")

    if single_date is not None and (start_date is not None or end_date is not None):
        raise InvalidMenuQueryError(
            "ambiguous_date_arguments",
            "Specify either `date` or `start_date`/`end_date`, not both.",
        )

    if single_date is not None:
        return single_date, single_date

    if start_date is None and end_date is None:
        today = dt_util.now().date()
        return today, today

    if start_date is None:
        assert end_date is not None
        return end_date, end_date
    if end_date is None:
        return start_date, start_date

    if end_date < start_date:
        raise InvalidMenuQueryError(
            "invalid_date_range",
            "`end_date` must be on or after `start_date`.",
        )

    if (end_date - start_date).days > MAX_QUERY_RANGE_DAYS:
        raise InvalidMenuQueryError(
            "range_too_large",
            f"Date range cannot exceed {MAX_QUERY_RANGE_DAYS} days per request.",
        )

    return start_date, end_date


async def async_execute_menu_query(
    hass: HomeAssistant,
    *,
    raw_date: Any = None,
    raw_start_date: Any = None,
    raw_end_date: Any = None,
    raw_menu_id: Any = None,
    raw_school_id: Any = None,
    raw_organization_id: Any = None,
) -> dict[str, Any]:
    """Execute a menu query across all loaded coordinators (shared by WS and service)."""
    start_date, end_date = resolve_query_dates(raw_date, raw_start_date, raw_end_date)
    filter_menu_id = _parse_optional_int(raw_menu_id, "menu_id")
    filter_school_id = _parse_optional_int(raw_school_id, "school_id")
    filter_org_id = _parse_optional_int(raw_organization_id, "organization_id")

    coordinators: dict[str, HealthEProCoordinator] = hass.data.get(DOMAIN, {}).get(
        "coordinators", {}
    )

    matched: list[tuple[HealthEProCoordinator, ConfiguredMenuTarget]] = []
    for coordinator in coordinators.values():
        if filter_org_id is not None and coordinator.organization_id != filter_org_id:
            continue
        for target in coordinator.menu_targets:
            if filter_school_id is not None and target.school_id != filter_school_id:
                continue
            if filter_menu_id is not None and target.menu_id != filter_menu_id:
                continue
            matched.append((coordinator, target))

    async def _build_target_payload(
        coord: HealthEProCoordinator, target: ConfiguredMenuTarget
    ) -> dict[str, Any]:
        days = await coord.async_get_range_menus(target.menu_id, start_date, end_date)
        return {
            "organization_id": target.organization_id,
            "organization_name": target.organization_name,
            "school_id": target.school_id,
            "school_name": target.school_name,
            "menu_id": target.menu_id,
            "menu_name": target.menu_name,
            "days": [day.to_dict() for day in days],
        }

    results = await asyncio.gather(
        *(_build_target_payload(coord, target) for coord, target in matched)
    )

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "menus": list(results),
    }


def list_configured_menus(hass: HomeAssistant) -> dict[str, Any]:
    """Return metadata for every configured district, school, and menu."""
    coordinators: dict[str, HealthEProCoordinator] = hass.data.get(DOMAIN, {}).get(
        "coordinators", {}
    )
    items: list[dict[str, Any]] = []
    for entry_id, coordinator in coordinators.items():
        for target in coordinator.menu_targets:
            items.append(
                {
                    "config_entry_id": entry_id,
                    "organization_id": target.organization_id,
                    "organization_name": target.organization_name,
                    "school_id": target.school_id,
                    "school_name": target.school_name,
                    "menu_id": target.menu_id,
                    "menu_name": target.menu_name,
                    "meal_type_id": target.meal_type_id,
                }
            )
    return {"menus": items}


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_TYPE_GET_MENUS,
        vol.Optional("date"): str,
        vol.Optional("start_date"): str,
        vol.Optional("end_date"): str,
        vol.Optional("menu_id"): vol.Any(int, str),
        vol.Optional("school_id"): vol.Any(int, str),
        vol.Optional("organization_id"): vol.Any(int, str),
    }
)
@websocket_api.async_response
async def websocket_get_menus(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle `healthepro/get_menus` WebSocket requests."""
    try:
        payload = await async_execute_menu_query(
            hass,
            raw_date=msg.get("date"),
            raw_start_date=msg.get("start_date"),
            raw_end_date=msg.get("end_date"),
            raw_menu_id=msg.get("menu_id"),
            raw_school_id=msg.get("school_id"),
            raw_organization_id=msg.get("organization_id"),
        )
    except InvalidMenuQueryError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    except HealthEProApiError as err:
        connection.send_error(msg["id"], "api_error", str(err))
        return

    connection.send_result(msg["id"], payload)


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_TYPE_LIST_MENUS,
    }
)
@websocket_api.callback
def websocket_list_menus(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle `healthepro/list_menus` WebSocket discovery requests."""
    connection.send_result(msg["id"], list_configured_menus(hass))


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register Health-e Pro WebSocket commands once per Home Assistant instance."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("ws_registered"):
        return
    websocket_api.async_register_command(hass, websocket_get_menus)
    websocket_api.async_register_command(hass, websocket_list_menus)
    domain_data["ws_registered"] = True

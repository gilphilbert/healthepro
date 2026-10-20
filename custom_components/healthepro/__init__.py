"""The Health-e Pro School Menus custom integration for Home Assistant."""

from __future__ import annotations

from datetime import datetime

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change

from .api import HealthEProApiClient, HealthEProApiError
from .const import DOMAIN, PLATFORMS, SERVICE_GET_MENUS
from .coordinator import HealthEProCoordinator
from .websocket import (
    InvalidMenuQueryError,
    async_execute_menu_query,
    async_register_websocket_commands,
)

SERVICE_GET_MENUS_SCHEMA = vol.Schema(
    {
        vol.Optional("date"): str,
        vol.Optional("start_date"): str,
        vol.Optional("end_date"): str,
        vol.Optional("menu_id"): vol.Any(int, str),
        vol.Optional("school_id"): vol.Any(int, str),
        vol.Optional("organization_id"): vol.Any(int, str),
    }
)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry cleanly when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the `healthepro.get_menus` service with response data support."""
    if hass.services.has_service(DOMAIN, SERVICE_GET_MENUS):
        return

    async def _handle_get_menus(call: ServiceCall) -> ServiceResponse:
        try:
            return await async_execute_menu_query(
                hass,
                raw_date=call.data.get("date"),
                raw_start_date=call.data.get("start_date"),
                raw_end_date=call.data.get("end_date"),
                raw_menu_id=call.data.get("menu_id"),
                raw_school_id=call.data.get("school_id"),
                raw_organization_id=call.data.get("organization_id"),
            )
        except (InvalidMenuQueryError, HealthEProApiError) as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_MENUS,
        _handle_get_menus,
        schema=SERVICE_GET_MENUS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Health-e Pro School Menus from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    coordinators: dict[str, HealthEProCoordinator] = domain_data.setdefault(
        "coordinators", {}
    )

    session = async_get_clientsession(hass)
    client = HealthEProApiClient(session)
    coordinator = HealthEProCoordinator(hass, entry, client)

    await coordinator.async_config_entry_first_refresh()
    coordinators[entry.entry_id] = coordinator

    async_register_websocket_commands(hass)
    _async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _handle_midnight_rollover(_now: datetime) -> None:
        """Refresh window and roll `Today`/`Tomorrow` sensors immediately after local midnight."""
        await coordinator.async_request_refresh()

    entry.async_on_unload(
        async_track_time_change(
            hass,
            _handle_midnight_rollover,
            hour=0,
            minute=0,
            second=5,
        )
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Health-e Pro config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinators: dict[str, HealthEProCoordinator] = hass.data.get(DOMAIN, {}).get(
            "coordinators", {}
        )
        coordinators.pop(entry.entry_id, None)
        if not coordinators and hass.services.has_service(DOMAIN, SERVICE_GET_MENUS):
            hass.services.async_remove(DOMAIN, SERVICE_GET_MENUS)
    return unload_ok

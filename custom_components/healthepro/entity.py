"""Shared entity base class for Health-e Pro School Menus."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, WEB_BASE_URL
from .coordinator import ConfiguredMenuTarget, HealthEProCoordinator


class HealthEProEntity(CoordinatorEntity[HealthEProCoordinator]):
    """Base entity binding each `(school, menu)` pair to a distinct Home Assistant Device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HealthEProCoordinator,
        target: ConfiguredMenuTarget,
    ) -> None:
        """Initialize base entity metadata and device registration."""
        super().__init__(coordinator)
        self.target = target
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, target.key)},
            name=f"{target.school_name} - {target.menu_name}",
            manufacturer=MANUFACTURER,
            model=target.organization_name or f"District {target.organization_id}",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=(
                f"{WEB_BASE_URL}/organizations/{target.organization_id}"
                f"/sites/{target.school_id}/menus/{target.menu_id}"
            ),
        )

"""End-to-end unit and integration tests for `custom_components.healthepro`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
import sys
from types import ModuleType
from typing import Any
import unittest
from unittest.mock import patch


def _install_homeassistant_stubs() -> None:
    """Install minimal `aiohttp`, `voluptuous`, and `homeassistant.*` stubs when running outside HA."""
    if "aiohttp" not in sys.modules:
        aiohttp_mod = ModuleType("aiohttp")

        class ClientError(Exception):
            pass

        class ClientTimeout:
            def __init__(self, total: float | None = None) -> None:
                self.total = total

        class ClientSession:
            pass

        aiohttp_mod.ClientError = ClientError  # type: ignore[attr-defined]
        aiohttp_mod.ClientTimeout = ClientTimeout  # type: ignore[attr-defined]
        aiohttp_mod.ClientSession = ClientSession  # type: ignore[attr-defined]
        sys.modules["aiohttp"] = aiohttp_mod

    if "voluptuous" not in sys.modules:
        vol_mod = ModuleType("voluptuous")

        class _Marker:
            def __init__(self, key: Any, default: Any = None) -> None:
                self.key = key
                self.default = default

            def __hash__(self) -> int:
                return hash(self.key)

            def __eq__(self, other: object) -> bool:
                return isinstance(other, _Marker) and self.key == other.key

        class Schema:
            def __init__(self, schema: Any) -> None:
                self.schema = schema

            def __call__(self, value: Any) -> Any:
                return value

        vol_mod.Schema = Schema  # type: ignore[attr-defined]
        vol_mod.Required = _Marker  # type: ignore[attr-defined]
        vol_mod.Optional = _Marker  # type: ignore[attr-defined]
        vol_mod.Any = lambda *args: args  # type: ignore[attr-defined]
        sys.modules["voluptuous"] = vol_mod

    if "homeassistant" in sys.modules:
        return

    ha_pkg = ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha_pkg

    const_mod = ModuleType("homeassistant.const")

    class Platform:
        SENSOR = "sensor"
        CALENDAR = "calendar"

    const_mod.Platform = Platform  # type: ignore[attr-defined]
    sys.modules["homeassistant.const"] = const_mod

    exceptions_mod = ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    exceptions_mod.HomeAssistantError = HomeAssistantError  # type: ignore[attr-defined]
    sys.modules["homeassistant.exceptions"] = exceptions_mod

    core_mod = ModuleType("homeassistant.core")

    class SupportsResponse:
        NONE = "none"
        OPTIONAL = "optional"
        ONLY = "only"

    @dataclass
    class ServiceCall:
        domain: str
        service: str
        data: dict[str, Any] = field(default_factory=dict)

    class _ServiceRegistry:
        def __init__(self) -> None:
            self._handlers: dict[tuple[str, str], Any] = {}

        def has_service(self, domain: str, service: str) -> bool:
            return (domain, service) in self._handlers

        def async_register(
            self,
            domain: str,
            service: str,
            handler: Any,
            schema: Any = None,
            supports_response: Any = None,
        ) -> None:
            self._handlers[(domain, service)] = handler

        def async_remove(self, domain: str, service: str) -> None:
            self._handlers.pop((domain, service), None)

        async def async_call(
            self, domain: str, service: str, data: dict[str, Any]
        ) -> Any:
            handler = self._handlers[(domain, service)]
            return await handler(ServiceCall(domain=domain, service=service, data=data))

    class _ConfigEntriesManager:
        def __init__(self) -> None:
            self.forwarded: list[tuple[str, list[str]]] = []
            self.reloaded: list[str] = []

        async def async_forward_entry_setups(
            self, entry: Any, platforms: list[str]
        ) -> None:
            self.forwarded.append((entry.entry_id, list(platforms)))

        async def async_unload_platforms(
            self, entry: Any, platforms: list[str]
        ) -> bool:
            return True

        async def async_reload(self, entry_id: str) -> None:
            self.reloaded.append(entry_id)

    class HomeAssistant:
        def __init__(self) -> None:
            self.data: dict[str, Any] = {}
            self.services = _ServiceRegistry()
            self.config_entries = _ConfigEntriesManager()

    core_mod.HomeAssistant = HomeAssistant  # type: ignore[attr-defined]
    core_mod.ServiceCall = ServiceCall  # type: ignore[attr-defined]
    core_mod.ServiceResponse = dict  # type: ignore[attr-defined]
    core_mod.SupportsResponse = SupportsResponse  # type: ignore[attr-defined]
    core_mod.callback = lambda fn: fn  # type: ignore[attr-defined]
    sys.modules["homeassistant.core"] = core_mod

    config_entries_mod = ModuleType("homeassistant.config_entries")

    @dataclass
    class ConfigEntry:
        entry_id: str
        data: dict[str, Any]
        options: dict[str, Any] = field(default_factory=dict)
        _unload_callbacks: list[Any] = field(default_factory=list)

        def add_update_listener(self, listener: Any) -> Any:
            return listener

        def async_on_unload(self, cb: Any) -> None:
            self._unload_callbacks.append(cb)

    class ConfigFlow:
        hass: Any
        unique_id: str | None = None

        def __init_subclass__(cls, domain: str | None = None, **kwargs: Any) -> None:
            super().__init_subclass__(**kwargs)
            cls.DOMAIN = domain

        async def async_set_unique_id(self, uid: str) -> None:
            self.unique_id = uid

        def _abort_if_unique_id_configured(self) -> None:
            return None

        def async_show_form(
            self,
            *,
            step_id: str,
            data_schema: Any = None,
            errors: dict[str, str] | None = None,
            description_placeholders: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
                "description_placeholders": description_placeholders or {},
            }

        def async_create_entry(
            self, *, title: str, data: dict[str, Any]
        ) -> dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

    class OptionsFlow:
        hass: Any
        config_entry: ConfigEntry

        def async_show_form(
            self,
            *,
            step_id: str,
            data_schema: Any = None,
            errors: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
            }

        def async_create_entry(
            self, *, title: str, data: dict[str, Any]
        ) -> dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

    config_entries_mod.ConfigEntry = ConfigEntry  # type: ignore[attr-defined]
    config_entries_mod.ConfigFlow = ConfigFlow  # type: ignore[attr-defined]
    config_entries_mod.ConfigFlowResult = dict  # type: ignore[attr-defined]
    config_entries_mod.OptionsFlow = OptionsFlow  # type: ignore[attr-defined]
    sys.modules["homeassistant.config_entries"] = config_entries_mod

    util_pkg = ModuleType("homeassistant.util")
    dt_mod = ModuleType("homeassistant.util.dt")
    dt_mod.now = lambda: datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)  # type: ignore[attr-defined]
    dt_mod.utcnow = lambda: datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)  # type: ignore[attr-defined]
    dt_mod.as_local = lambda dt: dt  # type: ignore[attr-defined]
    util_pkg.dt = dt_mod  # type: ignore[attr-defined]
    sys.modules["homeassistant.util"] = util_pkg
    sys.modules["homeassistant.util.dt"] = dt_mod

    helpers_pkg = ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers"] = helpers_pkg

    aiohttp_helper_mod = ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_helper_mod.async_get_clientsession = lambda hass: object()  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_helper_mod

    event_helper_mod = ModuleType("homeassistant.helpers.event")

    def async_track_time_change(
        hass: Any,
        action: Any,
        hour: Any = None,
        minute: Any = None,
        second: Any = None,
    ) -> Any:
        listeners = hass.data.setdefault("_time_listeners", [])
        record = {
            "action": action,
            "hour": hour,
            "minute": minute,
            "second": second,
            "unsubscribed": False,
        }
        listeners.append(record)

        def _unsub() -> None:
            record["unsubscribed"] = True

        return _unsub

    event_helper_mod.async_track_time_change = async_track_time_change  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.event"] = event_helper_mod

    dev_reg_mod = ModuleType("homeassistant.helpers.device_registry")

    class DeviceEntryType:
        SERVICE = "service"

    class DeviceInfo(dict):  # type: ignore[type-arg]
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)

    dev_reg_mod.DeviceEntryType = DeviceEntryType  # type: ignore[attr-defined]
    dev_reg_mod.DeviceInfo = DeviceInfo  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.device_registry"] = dev_reg_mod

    entity_platform_mod = ModuleType("homeassistant.helpers.entity_platform")
    entity_platform_mod.AddEntitiesCallback = Any  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform_mod

    selector_mod = ModuleType("homeassistant.helpers.selector")

    class SelectOptionDict(dict):  # type: ignore[type-arg]
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)

    @dataclass
    class SelectSelectorConfig:
        options: list[Any]
        multiple: bool = False
        mode: str = "dropdown"

    class SelectSelector:
        def __init__(self, config: SelectSelectorConfig) -> None:
            self.config = config

    class SelectSelectorMode:
        DROPDOWN = "dropdown"
        LIST = "list"

    class TextSelectorType:
        TEXT = "text"

    @dataclass
    class TextSelectorConfig:
        type: str = "text"

    class TextSelector:
        def __init__(self, config: TextSelectorConfig) -> None:
            self.config = config

    class NumberSelectorMode:
        BOX = "box"

    @dataclass
    class NumberSelectorConfig:
        min: float | None = None
        max: float | None = None
        step: float | None = None
        unit_of_measurement: str | None = None
        mode: str = "box"

    class NumberSelector:
        def __init__(self, config: NumberSelectorConfig) -> None:
            self.config = config

    selector_mod.NumberSelector = NumberSelector  # type: ignore[attr-defined]
    selector_mod.NumberSelectorConfig = NumberSelectorConfig  # type: ignore[attr-defined]
    selector_mod.NumberSelectorMode = NumberSelectorMode  # type: ignore[attr-defined]
    selector_mod.SelectOptionDict = SelectOptionDict  # type: ignore[attr-defined]
    selector_mod.SelectSelectorConfig = SelectSelectorConfig  # type: ignore[attr-defined]
    selector_mod.SelectSelector = SelectSelector  # type: ignore[attr-defined]
    selector_mod.SelectSelectorMode = SelectSelectorMode  # type: ignore[attr-defined]
    selector_mod.TextSelector = TextSelector  # type: ignore[attr-defined]
    selector_mod.TextSelectorConfig = TextSelectorConfig  # type: ignore[attr-defined]
    selector_mod.TextSelectorType = TextSelectorType  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.selector"] = selector_mod

    coord_mod = ModuleType("homeassistant.helpers.update_coordinator")

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator:
        def __class_getitem__(cls, item: Any) -> Any:
            return cls

        def __init__(
            self,
            hass: Any,
            logger: Any,
            *,
            name: str,
            update_interval: timedelta | None = None,
        ) -> None:
            self.hass = hass
            self.name = name
            self.update_interval = update_interval
            self.data: Any = None

        async def async_config_entry_first_refresh(self) -> None:
            self.data = await self._async_update_data()

        async def async_request_refresh(self) -> None:
            self.data = await self._async_update_data()

    class CoordinatorEntity:
        def __class_getitem__(cls, item: Any) -> Any:
            return cls

        def __init__(self, coordinator: Any) -> None:
            self.coordinator = coordinator

    coord_mod.UpdateFailed = UpdateFailed  # type: ignore[attr-defined]
    coord_mod.DataUpdateCoordinator = DataUpdateCoordinator  # type: ignore[attr-defined]
    coord_mod.CoordinatorEntity = CoordinatorEntity  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.update_coordinator"] = coord_mod

    comp_pkg = ModuleType("homeassistant.components")
    sys.modules["homeassistant.components"] = comp_pkg

    sensor_mod = ModuleType("homeassistant.components.sensor")

    @dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str
        name: str | None = None
        icon: str | None = None

    class SensorEntity:
        pass

    sensor_mod.SensorEntityDescription = SensorEntityDescription  # type: ignore[attr-defined]
    sensor_mod.SensorEntity = SensorEntity  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.sensor"] = sensor_mod

    cal_mod = ModuleType("homeassistant.components.calendar")

    @dataclass
    class CalendarEvent:
        start: date
        end: date
        summary: str
        description: str = ""

    class CalendarEntity:
        pass

    cal_mod.CalendarEvent = CalendarEvent  # type: ignore[attr-defined]
    cal_mod.CalendarEntity = CalendarEntity  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.calendar"] = cal_mod

    ws_mod = ModuleType("homeassistant.components.websocket_api")

    class ActiveConnection:
        def __init__(self) -> None:
            self.results: list[tuple[int, Any]] = []
            self.errors: list[tuple[int, str, str]] = []

        def send_result(self, msg_id: int, result: Any) -> None:
            self.results.append((msg_id, result))

        def send_error(self, msg_id: int, code: str, message: str) -> None:
            self.errors.append((msg_id, code, message))

    def websocket_command(schema: dict[str, Any]) -> Any:
        def decorator(fn: Any) -> Any:
            fn._ws_schema = schema
            return fn

        return decorator

    def async_register_command(hass: Any, handler: Any) -> None:
        reg = hass.data.setdefault("_ws_commands", [])
        reg.append(handler)

    ws_mod.ActiveConnection = ActiveConnection  # type: ignore[attr-defined]
    ws_mod.websocket_command = websocket_command  # type: ignore[attr-defined]
    ws_mod.async_response = lambda fn: fn  # type: ignore[attr-defined]
    ws_mod.callback = lambda fn: fn  # type: ignore[attr-defined]
    ws_mod.async_register_command = async_register_command  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.websocket_api"] = ws_mod


_install_homeassistant_stubs()

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from homeassistant.components.websocket_api import ActiveConnection  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402

from custom_components.healthepro import (  # noqa: E402
    async_setup_entry,
    async_unload_entry,
)
from custom_components.healthepro.api import (  # noqa: E402
    HealthEProApiClient,
    parse_month_overwrites,
)
from custom_components.healthepro.calendar import (  # noqa: E402
    async_setup_entry as async_setup_calendar,
)
from custom_components.healthepro.config_flow import HealthEProConfigFlow  # noqa: E402
from custom_components.healthepro.const import (  # noqa: E402
    CONF_MENUS,
    CONF_NO_MENU_MESSAGE,
    CONF_ORGANIZATION_ID,
    CONF_SCHOOLS,
    CONF_SEARCH_QUERY,
    DOMAIN,
    SERVICE_GET_MENUS,
)
from custom_components.healthepro.sensor import (  # noqa: E402
    async_setup_entry as async_setup_sensors,
)
from custom_components.healthepro.websocket import (  # noqa: E402
    websocket_get_menus,
    websocket_list_menus,
)


FAKE_API_RESPONSES: dict[str, Any] = {
    "/organizations/?query=Issaquah": {
        "data": [
            {
                "id": 48,
                "name": "Washington",
                "organizations": [
                    {
                        "id": 327,
                        "name": "Issaquah School District",
                        "state": "Washington",
                    }
                ],
            }
        ]
    },
    "/organizations/327/sites/list": {
        "data": [
            {"id": 2980, "name": "Apollo"},
            {"id": 2991, "name": "Maple Hills"},
        ]
    },
    "/organizations/327/sites/2980/menus/": {
        "data": [
            {
                "id": 138101,
                "custom_name": "26-27 Breakfast Menu",
                "name": "26-27 Breakfast Menu",
                "public_name": "26-27 Breakfast Menu",
                "meal_type_id": 1,
            },
            {
                "id": 137989,
                "custom_name": "26-27 Elementary Lunch Menu",
                "name": "26-27 Elementary Lunch Menu",
                "public_name": "26-27 Elementary Lunch Menu",
                "meal_type_id": 2,
            },
        ]
    },
    "/organizations/327/sites/2991/menus/": {
        "data": [
            {
                "id": 137989,
                "custom_name": "26-27 Elementary Lunch Menu",
                "name": "26-27 Elementary Lunch Menu",
                "public_name": "26-27 Elementary Lunch Menu",
                "meal_type_id": 2,
            }
        ]
    },
    "/organizations/327/menus/137989/year/2026/month/09/date_overwrites": {
        "data": [
            {
                "id": 1,
                "day": "2026-09-07",
                "meal_id": 137989,
                "overwritten": False,
                "setting": json.dumps(
                    {
                        "current_display": [],
                        "days_off": {"status": 1, "description": "Labor Day"},
                    }
                ),
            }
        ]
    },
    "/organizations/327/menus/137989/year/2026/month/10/date_overwrites": {
        "data": [
            {
                "id": 10,
                "day": "2026-10-19",
                "meal_id": 137989,
                "overwritten": False,
                "setting": json.dumps(
                    {
                        "current_display": [
                            {"item": "Lunch Entree", "weight": 0, "name": "Lunch Entree", "type": "category"},
                            {"item": 95800, "weight": 1, "name": "Fish Nuggets with French Fry Wedges", "type": "recipe"},
                            {"item": 95505, "weight": 2, "name": "Yogurt Lunch", "type": "recipe"},
                            {"item": "Vegetables", "weight": 3, "name": "Vegetables", "type": "category"},
                            {"item": 1683643, "weight": 4, "name": "Corn", "type": "recipe"},
                            {"item": 1683646, "weight": 5, "name": "Corn", "type": "recipe"},
                        ],
                        "days_off": [],
                    }
                ),
            },
            {
                "id": 11,
                "day": "2026-10-20",
                "meal_id": 137989,
                "overwritten": True,
                "setting": json.dumps(
                    {
                        "current_display": [
                            {
                                "item": "cust_pea_note",
                                "weight": 0,
                                "name": "*Peas are legumes.",
                                "type": "text",
                            },
                            {"item": "Lunch Entree", "weight": 1, "name": "Lunch Entree", "type": "category"},
                            {"item": 95900, "weight": 2, "name": "Nacho Supreme", "type": "recipe"},
                            {"item": 95901, "weight": 3, "name": "Plant Based Meat Nacho Supreme*", "type": "recipe"},
                        ],
                        "days_off": [],
                    }
                ),
            },
        ]
    },
    "/organizations/327/menus/138101/year/2026/month/10/date_overwrites": {
        "data": [
            {
                "id": 20,
                "day": "2026-10-19",
                "meal_id": 138101,
                "overwritten": False,
                "setting": json.dumps(
                    {
                        "current_display": [
                            {"item": "Breakfast Entree", "weight": 0, "name": "Breakfast Entree", "type": "category"},
                            {"item": 88001, "weight": 1, "name": "Warm Cinnamon Roll", "type": "recipe"},
                        ],
                        "days_off": [],
                    }
                ),
            }
        ]
    },
}


class HealthEProIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Comprehensive tests covering API parsing, ConfigFlow, Coordinator, Entities, WS, and Services."""

    def setUp(self) -> None:
        self.fetch_calls: list[str] = []

        async def _fake_get_json(_client: HealthEProApiClient, path: str) -> Any:
            self.fetch_calls.append(path)
            return FAKE_API_RESPONSES.get(path, {"data": []})

        self._patcher = patch.object(
            HealthEProApiClient, "_async_get_json", new=_fake_get_json
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()

    def test_month_parser_deduplicates_items_notes_and_holidays(self) -> None:
        oct_days = parse_month_overwrites(
            FAKE_API_RESPONSES[
                "/organizations/327/menus/137989/year/2026/month/10/date_overwrites"
            ]
        )
        mon = oct_days[date(2026, 10, 19)]
        self.assertTrue(mon.has_menu)
        self.assertEqual(
            mon.summary, "Fish Nuggets with French Fry Wedges, Yogurt Lunch"
        )
        # Duplicate 'Corn' recipes in Health-e Pro must collapse to a single 'Corn':
        self.assertEqual(mon.categories["Vegetables"], ("Corn",))

        tue = oct_days[date(2026, 10, 20)]
        self.assertEqual(tue.notes, ("*Peas are legumes.",))
        self.assertNotIn("*Peas are legumes.", tue.all_items)

        sep_days = parse_month_overwrites(
            FAKE_API_RESPONSES[
                "/organizations/327/menus/137989/year/2026/month/09/date_overwrites"
            ]
        )
        labor_day = sep_days[date(2026, 9, 7)]
        self.assertFalse(labor_day.has_menu)
        self.assertEqual(labor_day.summary, "No school (Labor Day)")

    async def test_config_flow_options_entities_calendar_and_websocket(self) -> None:
        hass = HomeAssistant()

        # 1. Complete 4-step ConfigFlow: District search -> District -> 2 Schools -> 3 Menus
        flow = HealthEProConfigFlow()
        flow.hass = hass

        step1 = await flow.async_step_user(
            {
                CONF_SEARCH_QUERY: "Issaquah",
                CONF_NO_MENU_MESSAGE: "No school",
                "scan_interval_hours": 4,
            }
        )
        self.assertEqual(step1["step_id"], "select_organization")

        step2 = await flow.async_step_select_organization(
            {CONF_ORGANIZATION_ID: "327"}
        )
        self.assertEqual(step2["step_id"], "select_schools")

        step3 = await flow.async_step_select_schools(
            {CONF_SCHOOLS: ["2980", "2991"]}
        )
        self.assertEqual(step3["step_id"], "select_menus")

        created = await flow.async_step_select_menus(
            {
                CONF_MENUS: [
                    "2980:138101",
                    "2980:137989",
                    "2991:137989",
                ]
            }
        )
        self.assertEqual(created["type"], "create_entry")
        self.assertEqual(created["title"], "Issaquah School District")
        self.assertEqual(len(created["data"][CONF_MENUS]), 3)

        # 2. Setup ConfigEntry and verify shared menu_id 137989 is fetched ONLY ONCE for Oct 2026!
        self.fetch_calls.clear()
        entry = ConfigEntry(entry_id="entry_1", data=created["data"])
        ok = await async_setup_entry(hass, entry)
        self.assertTrue(ok)
        coord = hass.data[DOMAIN]["coordinators"]["entry_1"]
        self.assertEqual(coord.update_interval, timedelta(hours=4))
        self.assertEqual(len(hass.data["_time_listeners"]), 1)
        self.assertEqual(
            (
                hass.data["_time_listeners"][0]["hour"],
                hass.data["_time_listeners"][0]["minute"],
                hass.data["_time_listeners"][0]["second"],
            ),
            (0, 0, 5),
        )
        oct_lunch_fetches = [
            p
            for p in self.fetch_calls
            if p
            == "/organizations/327/menus/137989/year/2026/month/10/date_overwrites"
        ]
        self.assertEqual(len(oct_lunch_fetches), 1)
        # Simulate local midnight rollover callback firing at 00:00:05:
        await hass.data["_time_listeners"][0]["action"](
            datetime(2026, 10, 20, 0, 0, 5, tzinfo=timezone.utc)
        )
        oct_lunch_fetches_after_midnight = [
            p
            for p in self.fetch_calls
            if p
            == "/organizations/327/menus/137989/year/2026/month/10/date_overwrites"
        ]
        self.assertEqual(len(oct_lunch_fetches_after_midnight), 2)

        # 3. Verify Sensor entities cover Today, Tomorrow, and full -7..+7 day window with zero blanks
        sensors: list[Any] = []
        await async_setup_sensors(hass, entry, sensors.extend)
        # 3 (school, menu) pairs * 15 days (-7..+7) = 45 sensors
        self.assertEqual(len(sensors), 45)
        for sensor in sensors:
            val = sensor.native_value
            self.assertTrue(isinstance(val, str) and len(val.strip()) > 0)

        by_uid = {s._attr_unique_id: s for s in sensors}
        self.assertEqual(
            by_uid["327_2991_137989_today"].native_value,
            "Fish Nuggets with French Fry Wedges, Yogurt Lunch",
        )
        self.assertEqual(
            by_uid["327_2991_137989_tomorrow"].native_value,
            "Nacho Supreme, Plant Based Meat Nacho Supreme*",
        )
        # Yesterday (Sunday 2026-10-18) must explicitly report "No school", never blank!
        self.assertEqual(
            by_uid["327_2991_137989_yesterday"].native_value,
            "No school",
        )
        self.assertEqual(
            len(by_uid["327_2991_137989_today"].extra_state_attributes["window_days"]),
            15,
        )

        # 4. Verify Calendar entities across school days and holidays
        calendars: list[Any] = []
        await async_setup_calendar(hass, entry, calendars.extend)
        self.assertEqual(len(calendars), 3)
        maple_cal = [c for c in calendars if c._attr_unique_id == "327_2991_137989_calendar"][0]
        events = await maple_cal.async_get_events(
            hass,
            datetime(2026, 9, 6, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            [(ev.start.isoformat(), ev.summary) for ev in events],
            [
                ("2026-09-06", "No school"),
                ("2026-09-07", "No school (Labor Day)"),
                ("2026-09-08", "No school"),
            ],
        )

        # 5. Verify WebSocket API: list_menus, default today, specific date + single menu filter, and date range
        conn = ActiveConnection()
        websocket_list_menus(hass, conn, {"id": 1, "type": "healthepro/list_menus"})
        self.assertEqual(len(conn.results[0][1]["menus"]), 3)

        # Omit date -> defaults to today (2026-10-19)
        await websocket_get_menus(hass, conn, {"id": 2, "type": "healthepro/get_menus"})
        today_ws = conn.results[1][1]
        self.assertEqual(today_ws["start_date"], "2026-10-19")
        self.assertEqual(len(today_ws["menus"]), 3)

        # Narrow to single menu (138101 Breakfast) on a weekend (2026-10-18) -> returns "No school"
        await websocket_get_menus(
            hass,
            conn,
            {
                "id": 3,
                "type": "healthepro/get_menus",
                "date": "2026-10-18",
                "menu_id": 138101,
            },
        )
        single_menu_ws = conn.results[2][1]
        self.assertEqual(len(single_menu_ws["menus"]), 1)
        self.assertEqual(single_menu_ws["menus"][0]["menu_id"], 138101)
        self.assertEqual(
            single_menu_ws["menus"][0]["days"][0]["summary"], "No school"
        )

        # Service action `healthepro.get_menus` works identically
        svc_resp = await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_MENUS,
            {
                "start_date": "2026-10-18",
                "end_date": "2026-10-20",
                "school_id": 2991,
                "menu_id": 137989,
            },
        )
        self.assertEqual(
            [d["summary"] for d in svc_resp["menus"][0]["days"]],
            [
                "No school",
                "Fish Nuggets with French Fry Wedges, Yogurt Lunch",
                "Nacho Supreme, Plant Based Meat Nacho Supreme*",
            ],
        )

        # OptionsFlow works cleanly
        opt_flow = HealthEProConfigFlow.async_get_options_flow(entry)
        opt_flow.hass = hass
        opt_step1 = await opt_flow.async_step_init(
            {CONF_SCHOOLS: ["2991"], CONF_NO_MENU_MESSAGE: "No school today"}
        )
        self.assertEqual(opt_step1["step_id"], "select_menus")
        opt_done = await opt_flow.async_step_select_menus({CONF_MENUS: ["2991:137989"]})
        self.assertEqual(opt_done["type"], "create_entry")
        self.assertEqual(opt_done["data"][CONF_NO_MENU_MESSAGE], "No school today")

        self.assertTrue(await async_unload_entry(hass, entry))


if __name__ == "__main__":
    unittest.main()

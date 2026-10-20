"""Config flow and Options flow for Health-e Pro School Menus."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    HealthEProApiClient,
    HealthEProApiError,
    HealthEProConnectionError,
    Organization,
    School,
    SchoolMenu,
)
from .const import (
    CONF_MENUS,
    CONF_NO_MENU_MESSAGE,
    CONF_ORGANIZATION_ID,
    CONF_ORGANIZATION_NAME,
    CONF_SCAN_INTERVAL_HOURS,
    CONF_SCHOOLS,
    CONF_SEARCH_QUERY,
    DEFAULT_NO_MENU_MESSAGE,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    MAX_SCAN_INTERVAL_HOURS,
    MIN_SCAN_INTERVAL_HOURS,
)


def _encode_school_menu_key(school_id: int, menu_id: int) -> str:
    """Encode `(school_id, menu_id)` as a selector option value."""
    return f"{school_id}:{menu_id}"


async def _fetch_menus_for_schools(
    client: HealthEProApiClient,
    organization_id: int,
    schools: list[School],
) -> list[dict[str, Any]]:
    """Fetch menus across all selected schools concurrently."""
    per_school_menus: list[list[SchoolMenu]] = await asyncio.gather(
        *(client.async_get_menus(organization_id, school.id) for school in schools)
    )
    discovered: list[dict[str, Any]] = []
    for school, menus in zip(schools, per_school_menus, strict=True):
        for menu in menus:
            discovered.append(
                {
                    "key": _encode_school_menu_key(school.id, menu.id),
                    "school_id": school.id,
                    "school_name": school.name,
                    "menu_id": menu.id,
                    "menu_name": menu.name,
                    "meal_type_id": menu.meal_type_id,
                    "label": f"{school.name} - {menu.name}",
                }
            )
    return discovered


class HealthEProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Multi-step UI flow to select District -> School(s) -> Menu(s)."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize transient flow state."""
        self._no_menu_message: str = DEFAULT_NO_MENU_MESSAGE
        self._scan_interval_hours: int = DEFAULT_SCAN_INTERVAL_HOURS
        self._organizations: dict[str, Organization] = {}
        self._selected_org: Organization | None = None
        self._schools: dict[str, School] = {}
        self._selected_schools: list[School] = []
        self._available_menus: dict[str, dict[str, Any]] = {}

    def _get_client(self) -> HealthEProApiClient:
        return HealthEProApiClient(async_get_clientsession(self.hass))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HealthEProOptionsFlow:
        """Create the options flow handler."""
        return HealthEProOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Search for a school district (or leave blank to list all)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            query = str(user_input.get(CONF_SEARCH_QUERY) or "").strip()
            raw_msg = str(
                user_input.get(CONF_NO_MENU_MESSAGE) or DEFAULT_NO_MENU_MESSAGE
            ).strip()
            self._no_menu_message = raw_msg or DEFAULT_NO_MENU_MESSAGE
            self._scan_interval_hours = max(
                MIN_SCAN_INTERVAL_HOURS,
                min(
                    MAX_SCAN_INTERVAL_HOURS,
                    int(
                        user_input.get(
                            CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
                        )
                    ),
                ),
            )

            try:
                orgs = await self._get_client().async_get_organizations(
                    query=query or None
                )
            except HealthEProConnectionError:
                errors["base"] = "cannot_connect"
            except HealthEProApiError:
                errors["base"] = "api_error"
            else:
                if not orgs:
                    errors["base"] = "no_organizations_found"
                else:
                    self._organizations = {str(org.id): org for org in orgs}
                    return await self.async_step_select_organization()

        schema = vol.Schema(
            {
                vol.Optional(CONF_SEARCH_QUERY, default=""): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
                vol.Optional(
                    CONF_NO_MENU_MESSAGE, default=self._no_menu_message
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Optional(
                    CONF_SCAN_INTERVAL_HOURS, default=self._scan_interval_hours
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL_HOURS,
                        max=MAX_SCAN_INTERVAL_HOURS,
                        step=1,
                        unit_of_measurement="h",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_select_organization(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Select a school district (`ORGANIZATION_ID`)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            org_key = str(user_input[CONF_ORGANIZATION_ID])
            selected = self._organizations.get(org_key)
            if selected is None:
                errors["base"] = "invalid_selection"
            else:
                try:
                    schools = await self._get_client().async_get_schools(selected.id)
                except HealthEProConnectionError:
                    errors["base"] = "cannot_connect"
                except HealthEProApiError:
                    errors["base"] = "api_error"
                else:
                    if not schools:
                        errors["base"] = "no_schools_found"
                    else:
                        self._selected_org = selected
                        self._schools = {str(s.id): s for s in schools}
                        return await self.async_step_select_schools()

        options = [
            SelectOptionDict(value=org_id, label=org.display_name)
            for org_id, org in self._organizations.items()
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_ORGANIZATION_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="select_organization",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_select_schools(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: Select one or more schools (`SCHOOL_ID`s) within the district."""
        assert self._selected_org is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            chosen_ids: list[str] = [str(sid) for sid in user_input.get(CONF_SCHOOLS, [])]
            chosen_schools = [
                self._schools[sid] for sid in chosen_ids if sid in self._schools
            ]
            if not chosen_schools:
                errors["base"] = "no_schools_selected"
            else:
                try:
                    discovered = await _fetch_menus_for_schools(
                        self._get_client(),
                        self._selected_org.id,
                        chosen_schools,
                    )
                except HealthEProConnectionError:
                    errors["base"] = "cannot_connect"
                except HealthEProApiError:
                    errors["base"] = "api_error"
                else:
                    if not discovered:
                        errors["base"] = "no_menus_found"
                    else:
                        self._selected_schools = chosen_schools
                        self._available_menus = {
                            item["key"]: item for item in discovered
                        }
                        return await self.async_step_select_menus()

        options = [
            SelectOptionDict(value=school_id, label=school.name)
            for school_id, school in self._schools.items()
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_SCHOOLS): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="select_schools",
            data_schema=schema,
            description_placeholders={"district": self._selected_org.display_name},
            errors=errors,
        )

    async def async_step_select_menus(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 4: Select one or more menus (`MENU_ID`s) across selected schools."""
        assert self._selected_org is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_keys: list[str] = [
                str(key) for key in user_input.get(CONF_MENUS, [])
            ]
            chosen_menus = [
                {
                    "school_id": self._available_menus[key]["school_id"],
                    "school_name": self._available_menus[key]["school_name"],
                    "menu_id": self._available_menus[key]["menu_id"],
                    "menu_name": self._available_menus[key]["menu_name"],
                    "meal_type_id": self._available_menus[key]["meal_type_id"],
                }
                for key in selected_keys
                if key in self._available_menus
            ]
            if not chosen_menus:
                errors["base"] = "no_menus_selected"
            else:
                unique_suffix = "_".join(sorted(selected_keys))
                await self.async_set_unique_id(
                    f"{self._selected_org.id}_{unique_suffix}"
                )
                self._abort_if_unique_id_configured()

                schools_payload = [
                    {"id": s.id, "name": s.name} for s in self._selected_schools
                ]
                return self.async_create_entry(
                    title=self._selected_org.name,
                    data={
                        CONF_ORGANIZATION_ID: self._selected_org.id,
                        CONF_ORGANIZATION_NAME: self._selected_org.name,
                        CONF_SCHOOLS: schools_payload,
                        CONF_MENUS: chosen_menus,
                        CONF_NO_MENU_MESSAGE: self._no_menu_message,
                        CONF_SCAN_INTERVAL_HOURS: self._scan_interval_hours,
                    },
                )

        options = [
            SelectOptionDict(value=key, label=item["label"])
            for key, item in self._available_menus.items()
        ]
        default_keys = list(self._available_menus.keys())
        schema = vol.Schema(
            {
                vol.Required(CONF_MENUS, default=default_keys): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="select_menus",
            data_schema=schema,
            description_placeholders={"district": self._selected_org.display_name},
            errors=errors,
        )


class HealthEProOptionsFlow(OptionsFlow):
    """Allow updating selected schools, menus, and empty-day message after setup."""

    def __init__(self, config_entry: ConfigEntry | None = None) -> None:
        """Initialize options flow cleanly across HA 2024.x - 2026.x."""
        if config_entry is not None and not hasattr(self, "config_entry"):
            self._fallback_entry = config_entry
        self._schools: dict[str, School] = {}
        self._selected_schools: list[School] = []
        self._available_menus: dict[str, dict[str, Any]] = {}
        self._no_menu_message: str = DEFAULT_NO_MENU_MESSAGE
        self._scan_interval_hours: int = DEFAULT_SCAN_INTERVAL_HOURS

    @property
    def _entry(self) -> ConfigEntry:
        if hasattr(self, "config_entry"):
            return self.config_entry
        return self._fallback_entry

    def _get_client(self) -> HealthEProApiClient:
        return HealthEProApiClient(async_get_clientsession(self.hass))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1 of options: adjust selected schools and empty-day message."""
        errors: dict[str, str] = {}
        org_id = int(self._entry.data[CONF_ORGANIZATION_ID])

        if not self._schools:
            try:
                schools = await self._get_client().async_get_schools(org_id)
                self._schools = {str(s.id): s for s in schools}
            except HealthEProConnectionError:
                errors["base"] = "cannot_connect"
            except HealthEProApiError:
                errors["base"] = "api_error"

        if user_input is not None and not errors:
            raw_msg = str(
                user_input.get(CONF_NO_MENU_MESSAGE) or DEFAULT_NO_MENU_MESSAGE
            ).strip()
            self._no_menu_message = raw_msg or DEFAULT_NO_MENU_MESSAGE
            self._scan_interval_hours = max(
                MIN_SCAN_INTERVAL_HOURS,
                min(
                    MAX_SCAN_INTERVAL_HOURS,
                    int(
                        user_input.get(
                            CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
                        )
                    ),
                ),
            )
            chosen_ids = [str(sid) for sid in user_input.get(CONF_SCHOOLS, [])]
            chosen_schools = [
                self._schools[sid] for sid in chosen_ids if sid in self._schools
            ]
            if not chosen_schools:
                errors["base"] = "no_schools_selected"
            else:
                try:
                    discovered = await _fetch_menus_for_schools(
                        self._get_client(), org_id, chosen_schools
                    )
                except HealthEProConnectionError:
                    errors["base"] = "cannot_connect"
                except HealthEProApiError:
                    errors["base"] = "api_error"
                else:
                    if not discovered:
                        errors["base"] = "no_menus_found"
                    else:
                        self._selected_schools = chosen_schools
                        self._available_menus = {
                            item["key"]: item for item in discovered
                        }
                        return await self.async_step_select_menus()

        existing_menus = self._entry.options.get(
            CONF_MENUS, self._entry.data.get(CONF_MENUS, [])
        )
        default_school_ids = sorted(
            {
                str(item["school_id"])
                for item in existing_menus
                if str(item["school_id"]) in self._schools
            }
        )
        current_msg = str(
            self._entry.options.get(
                CONF_NO_MENU_MESSAGE,
                self._entry.data.get(CONF_NO_MENU_MESSAGE, DEFAULT_NO_MENU_MESSAGE),
            )
        )
        current_hours = int(
            self._entry.options.get(
                CONF_SCAN_INTERVAL_HOURS,
                self._entry.data.get(
                    CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
                ),
            )
        )
        options = [
            SelectOptionDict(value=school_id, label=school.name)
            for school_id, school in self._schools.items()
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_SCHOOLS, default=default_school_ids): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_NO_MENU_MESSAGE, default=current_msg
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Optional(
                    CONF_SCAN_INTERVAL_HOURS, default=current_hours
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL_HOURS,
                        max=MAX_SCAN_INTERVAL_HOURS,
                        step=1,
                        unit_of_measurement="h",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def async_step_select_menus(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2 of options: choose active menus for selected schools."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_keys = [str(k) for k in user_input.get(CONF_MENUS, [])]
            chosen_menus = [
                {
                    "school_id": self._available_menus[key]["school_id"],
                    "school_name": self._available_menus[key]["school_name"],
                    "menu_id": self._available_menus[key]["menu_id"],
                    "menu_name": self._available_menus[key]["menu_name"],
                    "meal_type_id": self._available_menus[key]["meal_type_id"],
                }
                for key in selected_keys
                if key in self._available_menus
            ]
            if not chosen_menus:
                errors["base"] = "no_menus_selected"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_SCHOOLS: [
                            {"id": s.id, "name": s.name}
                            for s in self._selected_schools
                        ],
                        CONF_MENUS: chosen_menus,
                        CONF_NO_MENU_MESSAGE: self._no_menu_message,
                        CONF_SCAN_INTERVAL_HOURS: self._scan_interval_hours,
                    },
                )

        existing_menus = self._entry.options.get(
            CONF_MENUS, self._entry.data.get(CONF_MENUS, [])
        )
        existing_keys = {
            _encode_school_menu_key(int(m["school_id"]), int(m["menu_id"]))
            for m in existing_menus
        }
        default_keys = [
            key for key in self._available_menus if key in existing_keys
        ] or list(self._available_menus.keys())

        options = [
            SelectOptionDict(value=key, label=item["label"])
            for key, item in self._available_menus.items()
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_MENUS, default=default_keys): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="select_menus", data_schema=schema, errors=errors
        )

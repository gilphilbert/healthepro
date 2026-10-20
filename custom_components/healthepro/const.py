"""Constants for the Health-e Pro School Menus integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "healthepro"
NAME = "Health-e Pro School Menus"
MANUFACTURER = "Health-e Pro"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.CALENDAR]

API_BASE_URL = "https://menus.healthepro.com/api"
WEB_BASE_URL = "https://menus.healthepro.com"

CONF_SEARCH_QUERY = "search_query"
CONF_ORGANIZATION_ID = "organization_id"
CONF_ORGANIZATION_NAME = "organization_name"
CONF_SCHOOLS = "schools"
CONF_MENUS = "menus"
CONF_NO_MENU_MESSAGE = "no_menu_message"
CONF_SCAN_INTERVAL_HOURS = "scan_interval_hours"

DEFAULT_NO_MENU_MESSAGE = "No school"
DEFAULT_SCAN_INTERVAL_HOURS = 6
MIN_SCAN_INTERVAL_HOURS = 1
MAX_SCAN_INTERVAL_HOURS = 24
DEFAULT_SCAN_INTERVAL = timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS)
MONTH_CACHE_TTL = timedelta(hours=6)

WINDOW_DAYS_PAST = 7
WINDOW_DAYS_FUTURE = 7
MAX_QUERY_RANGE_DAYS = 62
MAX_STATE_LENGTH = 255

SERVICE_GET_MENUS = "get_menus"
WS_TYPE_GET_MENUS = "healthepro/get_menus"
WS_TYPE_LIST_MENUS = "healthepro/list_menus"

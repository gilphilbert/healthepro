"""Async client and parser for the undocumented Health-e Pro Menus API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
import json
import logging
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import API_BASE_URL, DEFAULT_NO_MENU_MESSAGE, MAX_STATE_LENGTH

_LOGGER = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
UNCATEGORIZED_HEADER = "Menu Items"


class HealthEProApiError(Exception):
    """Base exception for Health-e Pro API errors."""


class HealthEProConnectionError(HealthEProApiError):
    """Raised when a network or timeout error occurs communicating with Health-e Pro."""


@dataclass(frozen=True, slots=True)
class Organization:
    """Represents a school district in Health-e Pro."""

    id: int
    name: str
    state: str | None = None

    @property
    def display_name(self) -> str:
        """Human-readable label including state when available."""
        if self.state:
            return f"{self.name} ({self.state})"
        return self.name


@dataclass(frozen=True, slots=True)
class School:
    """Represents a school site within a district."""

    id: int
    name: str


@dataclass(frozen=True, slots=True)
class SchoolMenu:
    """Represents a published menu for a school site."""

    id: int
    name: str
    meal_type_id: int | None = None
    published_months: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DayMenu:
    """Normalized menu data for a single calendar date."""

    date: date
    has_menu: bool
    status: str
    summary: str
    entrees: tuple[str, ...] = ()
    categories: dict[str, tuple[str, ...]] = field(default_factory=dict)
    all_items: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def state_value(self) -> str:
        """Non-blank state string guaranteed to fit Home Assistant's 255-char limit."""
        text = self.summary.strip() or DEFAULT_NO_MENU_MESSAGE
        if len(text) <= MAX_STATE_LENGTH:
            return text
        return f"{text[: MAX_STATE_LENGTH - 3].rstrip()}..."

    def to_dict(self) -> dict[str, Any]:
        """Serialize into a JSON-friendly dictionary for attributes, services, and WS."""
        return {
            "date": self.date.isoformat(),
            "day_of_week": self.date.strftime("%A"),
            "has_menu": self.has_menu,
            "status": self.status,
            "summary": self.summary,
            "entrees": list(self.entrees),
            "categories": {
                category: list(items) for category, items in self.categories.items()
            },
            "all_items": list(self.all_items),
            "notes": list(self.notes),
        }


def make_empty_day_menu(
    target_date: date,
    no_menu_message: str = DEFAULT_NO_MENU_MESSAGE,
    reason: str | None = None,
) -> DayMenu:
    """Build an explicit non-blank DayMenu for weekends, holidays, or unscheduled days."""
    base = (no_menu_message or "").strip() or DEFAULT_NO_MENU_MESSAGE
    clean_reason = (reason or "").strip()
    if clean_reason and clean_reason.casefold() != base.casefold():
        message = f"{base} ({clean_reason})"
    else:
        message = base

    return DayMenu(
        date=target_date,
        has_menu=False,
        status=message,
        summary=message,
    )


def _extract_day_off_reason(days_off: Any) -> tuple[bool, str | None]:
    """Inspect Health-e Pro's polymorphic `days_off` structure."""
    if not days_off:
        return False, None

    if isinstance(days_off, dict):
        description = str(days_off.get("description") or days_off.get("name") or "").strip()
        status = days_off.get("status")
        if status or description:
            return True, description or None
        return False, None

    if isinstance(days_off, list):
        for entry in days_off:
            is_off, reason = _extract_day_off_reason(entry)
            if is_off:
                return True, reason
        return False, None

    if isinstance(days_off, bool):
        return days_off, None

    return False, None


def _is_entree_category(category_name: str) -> bool:
    """Return True when a Health-e Pro category represents main meal entrees."""
    normalized = category_name.casefold().replace("é", "e")
    return "entree" in normalized or "main" in normalized


def parse_day_overwrite(
    raw_entry: dict[str, Any],
    no_menu_message: str = DEFAULT_NO_MENU_MESSAGE,
) -> DayMenu | None:
    """Parse a single entry from the Health-e Pro `date_overwrites` payload."""
    day_str = raw_entry.get("day")
    if not day_str or not isinstance(day_str, str):
        return None

    try:
        parsed_date = date.fromisoformat(day_str[:10])
    except ValueError:
        _LOGGER.debug("Skipping unparseable Health-e Pro date field: %s", day_str)
        return None

    raw_setting = raw_entry.get("setting")
    setting: dict[str, Any] = {}
    if isinstance(raw_setting, str) and raw_setting.strip():
        try:
            loaded = json.loads(raw_setting)
            if isinstance(loaded, dict):
                setting = loaded
        except json.JSONDecodeError:
            _LOGGER.warning("Failed to decode setting JSON for %s", day_str)
            return make_empty_day_menu(parsed_date, no_menu_message)
    elif isinstance(raw_setting, dict):
        setting = raw_setting

    is_day_off, off_reason = _extract_day_off_reason(setting.get("days_off"))
    if is_day_off:
        return make_empty_day_menu(parsed_date, no_menu_message, reason=off_reason)

    current_display = setting.get("current_display")
    if not isinstance(current_display, list) or not current_display:
        return make_empty_day_menu(parsed_date, no_menu_message)

    categories: dict[str, list[str]] = {}
    all_items: list[str] = []
    notes: list[str] = []
    current_category = UNCATEGORIZED_HEADER

    for raw_item in current_display:
        if not isinstance(raw_item, dict):
            continue
        name = str(raw_item.get("name") or "").strip()
        if not name:
            continue
        item_type = str(raw_item.get("type") or "").strip().lower()

        if item_type == "category":
            current_category = name
            categories.setdefault(current_category, [])
        elif item_type == "text":
            if name not in notes:
                notes.append(name)
        else:
            bucket = categories.setdefault(current_category, [])
            if name not in bucket:
                bucket.append(name)
            if name not in all_items:
                all_items.append(name)

    non_empty_categories = {
        cat: tuple(items) for cat, items in categories.items() if items
    }
    if not all_items:
        return make_empty_day_menu(parsed_date, no_menu_message)

    entree_items: list[str] = []
    for cat_name, items in non_empty_categories.items():
        if _is_entree_category(cat_name):
            for item in items:
                if item not in entree_items:
                    entree_items.append(item)

    if not entree_items:
        first_category_items = next(iter(non_empty_categories.values()))
        entree_items = list(first_category_items)

    summary = ", ".join(entree_items)
    return DayMenu(
        date=parsed_date,
        has_menu=True,
        status="Available",
        summary=summary,
        entrees=tuple(entree_items),
        categories=non_empty_categories,
        all_items=tuple(all_items),
        notes=tuple(notes),
    )


def parse_month_overwrites(
    payload: dict[str, Any] | list[Any],
    no_menu_message: str = DEFAULT_NO_MENU_MESSAGE,
) -> dict[date, DayMenu]:
    """Parse a full monthly `date_overwrites` JSON payload indexed by `datetime.date`."""
    entries = payload.get("data", []) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return {}

    parsed: dict[date, DayMenu] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        day_menu = parse_day_overwrite(entry, no_menu_message=no_menu_message)
        if day_menu is not None:
            parsed[day_menu.date] = day_menu
    return parsed


class HealthEProApiClient:
    """Async client for Health-e Pro school menu endpoints."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str = API_BASE_URL,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._base_url = base_url.rstrip("/")

    async def _async_get_json(self, path: str) -> Any:
        """Perform an HTTP GET and decode JSON with unified error translation."""
        url = f"{self._base_url}{path}"
        try:
            async with self._session.get(url, timeout=DEFAULT_REQUEST_TIMEOUT) as resp:
                if resp.status >= 400:
                    raise HealthEProApiError(
                        f"HTTP {resp.status} fetching {url}"
                    )
                return await resp.json(content_type=None)
        except HealthEProApiError:
            raise
        except (TimeoutError, asyncio.TimeoutError, aiohttp.ClientError) as err:
            raise HealthEProConnectionError(
                f"Connection error communicating with {url}: {err}"
            ) from err
        except ValueError as err:
            raise HealthEProApiError(f"Invalid JSON payload from {url}: {err}") from err

    async def async_get_organizations(
        self, query: str | None = None
    ) -> list[Organization]:
        """List all school districts or search by query string."""
        cleaned = (query or "").strip()
        if cleaned:
            path = f"/organizations/?query={quote(cleaned)}"
        else:
            path = "/organizations"

        payload = await self._async_get_json(path)
        raw_data = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(raw_data, list):
            return []

        seen_ids: set[int] = set()
        organizations: list[Organization] = []

        for group_or_org in raw_data:
            if not isinstance(group_or_org, dict):
                continue

            nested_orgs = group_or_org.get("organizations")
            if isinstance(nested_orgs, list):
                group_state = str(group_or_org.get("name") or "").strip() or None
                for org in nested_orgs:
                    if not isinstance(org, dict) or "id" not in org:
                        continue
                    org_id = int(org["id"])
                    if org_id in seen_ids:
                        continue
                    seen_ids.add(org_id)
                    state = str(org.get("state") or group_state or "").strip() or None
                    organizations.append(
                        Organization(
                            id=org_id,
                            name=str(org.get("name") or f"Organization {org_id}").strip(),
                            state=state,
                        )
                    )
            elif "id" in group_or_org:
                org_id = int(group_or_org["id"])
                if org_id in seen_ids:
                    continue
                seen_ids.add(org_id)
                state = str(group_or_org.get("state") or "").strip() or None
                organizations.append(
                    Organization(
                        id=org_id,
                        name=str(
                            group_or_org.get("name") or f"Organization {org_id}"
                        ).strip(),
                        state=state,
                    )
                )

        organizations.sort(key=lambda o: (o.name.casefold(), (o.state or "").casefold()))
        return organizations

    async def async_get_schools(self, organization_id: int) -> list[School]:
        """List all schools (sites) within a given school district."""
        payload = await self._async_get_json(
            f"/organizations/{organization_id}/sites/list"
        )
        raw_data = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(raw_data, list):
            return []

        schools = [
            School(
                id=int(item["id"]),
                name=str(item.get("name") or f"School {item['id']}").strip(),
            )
            for item in raw_data
            if isinstance(item, dict) and "id" in item
        ]
        schools.sort(key=lambda s: s.name.casefold())
        return schools

    async def async_get_menus(
        self, organization_id: int, school_id: int
    ) -> list[SchoolMenu]:
        """List published menus for a specific school."""
        payload = await self._async_get_json(
            f"/organizations/{organization_id}/sites/{school_id}/menus/"
        )
        raw_data = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(raw_data, list):
            return []

        menus: list[SchoolMenu] = []
        for item in raw_data:
            if not isinstance(item, dict) and "id" not in item:
                continue
            if not isinstance(item, dict) or "id" not in item:
                continue
            menu_id = int(item["id"])
            display_name = str(
                item.get("public_name")
                or item.get("custom_name")
                or item.get("name")
                or f"Menu {menu_id}"
            ).strip()
            raw_meal_type = item.get("meal_type_id")
            meal_type_id = int(raw_meal_type) if raw_meal_type is not None else None
            raw_months = item.get("published_months")
            published_months = (
                tuple(str(m) for m in raw_months)
                if isinstance(raw_months, list)
                else ()
            )
            menus.append(
                SchoolMenu(
                    id=menu_id,
                    name=display_name,
                    meal_type_id=meal_type_id,
                    published_months=published_months,
                )
            )
        return menus

    async def async_get_month_menu(
        self,
        organization_id: int,
        menu_id: int,
        year: int,
        month: int,
        no_menu_message: str = DEFAULT_NO_MENU_MESSAGE,
    ) -> dict[date, DayMenu]:
        """Fetch and parse a full one-month menu from `date_overwrites`."""
        path = (
            f"/organizations/{organization_id}/menus/{menu_id}"
            f"/year/{year:04d}/month/{month:02d}/date_overwrites"
        )
        payload = await self._async_get_json(path)
        return parse_month_overwrites(payload, no_menu_message=no_menu_message)

# Health-e Pro School Menus for Home Assistant

A custom Home Assistant integration (`custom_components/healthepro`) that pulls monthly school breakfast and lunch menus from Health-e Pro (`menus.healthepro.com`), exposes per-day sensor and calendar entities, and registers a WebSocket and service interface for dashboards, automations, and external displays.

## Features

### Automatic Polling & Midnight Day Rollover
- Background API polling runs automatically via Home Assistant's `DataUpdateCoordinator` every 6 hours by default (configurable between `1` and `24` hours during initial setup or later under Configure).
- A local-midnight listener (`00:00:05` in Home Assistant's timezone) triggers an automatic refresh right after midnight so `Today`, `Tomorrow`, `Yesterday`, and all `-7` to `+7` day entities roll over immediately when the date changes rather than waiting until the next polling cycle.

### Multi-Step UI Configuration & Reconfiguration
Add the integration from Settings -> Devices & Services -> Add Integration -> Health-e Pro School Menus:
1. Search school districts using `/api/organizations/?query=<QUERY>` (or leave blank to load `/api/organizations`), handling state-grouped district responses automatically.
2. Select one or more schools within that district from `/api/organizations/<ORGANIZATION_ID>/sites/list`.
3. Select one or more menus across the chosen schools from `/api/organizations/<ORGANIZATION_ID>/sites/<SCHOOL_ID>/menus/`.
4. Reconfigure schools, menus, refresh frequency, or the empty-day message anytime via the Configure button (`OptionsFlow`).

### Entities for Today, Tomorrow, and a Rolling 15-Day Window (`-7` to `+7` Days)
Each selected `(school, menu)` pair is registered as its own Home Assistant device with distinct entities:
- `calendar.<school>_<menu>`: Native Home Assistant `CalendarEntity` supporting weekly, monthly, and list calendar cards across any month.
- `sensor.<school>_<menu>_today`: Today's entree summary, plus full categorized items, notes, and a `window_days` attribute containing all 15 days (`-7` through `+7`).
- `sensor.<school>_<menu>_tomorrow`: Tomorrow's entree summary and full categorized attributes.
- `sensor.<school>_<menu>_yesterday`, `sensor.<school>_<menu>_minus_2_days` .. `minus_7_days`, and `sensor.<school>_<menu>_plus_2_days` .. `plus_7_days`: Individual per-day entities covering every day in the past 7 days and next 7 days.

### Explicit Non-Blank Empty Days
Weekends, school breaks omitted from `date_overwrites`, and holidays marked in `days_off` never return an empty string. Days without menu items return `"No school"` (or your configured message), and named holidays include the reason when provided by the district, such as `"No school (Labor Day)"`.

### WebSocket API & Service Interface
Query menus directly over Home Assistant's WebSocket interface (`/api/websocket` or `hass.callWS(...)` in custom cards) or via the `healthepro.get_menus` action:
- Omit `date` to get today's menus automatically in Home Assistant's configured timezone.
- Provide `date: "YYYY-MM-DD"` for a specific day, or `start_date` and `end_date` for a multi-day range.
- Optionally pass `menu_id`, `school_id`, or `organization_id` to narrow the response to a single menu or school.

## Installing via HACS Custom Repository (Recommended)

 Note that Home Assistant's built-in Settings -> Add-ons -> Repositories menu only supports containerized OS Add-ons, whereas custom Python integrations (`custom_components/...`) are installed and updated through HACS:

1. Push this directory to the root of a public GitHub repository (including `hacs.json`, `README.md`, `LICENSE`, and `custom_components/healthepro/`), and update `documentation`, `issue_tracker`, and `codeowners` in `custom_components/healthepro/manifest.json` to match your GitHub username and repo name.
2. Create a GitHub Release tag matching the `version` in `manifest.json` (for example, `v1.0.1`). Whenever you push updates later, bump `version` in `manifest.json` and publish a new GitHub Release tag so Home Assistant notifies you with a one-click update button.
3. In Home Assistant, open HACS -> top-right menu (`⋮`) -> Custom repositories.
4. Paste your GitHub repository URL (`https://github.com/<your-username>/<your-repo>`), select Category `Integration`, and click Add.
5. Download `Health-e Pro School Menus` in HACS, restart Home Assistant, then open Settings -> Devices & Services -> Add Integration and search for `Health-e Pro School Menus`.

## Manual Installation

1. Copy the `custom_components/healthepro` folder into your Home Assistant `config/custom_components/` directory so that `config/custom_components/healthepro/manifest.json` exists.
2. Restart Home Assistant.
3. Open Settings -> Devices & Services -> Add Integration and search for `Health-e Pro School Menus`.

## WebSocket Usage Examples

### 1. List Configured Menus
```json
{
  "id": 1,
  "type": "healthepro/list_menus"
}
```

### 2. Get Today's Menus (Default Date)
```json
{
  "id": 2,
  "type": "healthepro/get_menus"
}
```

### 3. Get a Single Menu on a Specific Date
```json
{
  "id": 3,
  "type": "healthepro/get_menus",
  "date": "2026-10-20",
  "menu_id": 137989
}
```

### 4. Get a 7-Day Window for One School Menu
```json
{
  "id": 4,
  "type": "healthepro/get_menus",
  "start_date": "2026-10-19",
  "end_date": "2026-10-25",
  "school_id": 2991,
  "menu_id": 137989
}
```

## Running Tests Locally

```bash
python3 -m unittest discover -s tests -v
```

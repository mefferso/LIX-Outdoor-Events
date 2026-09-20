# Event Sources

This application is an IDSS support layer, not an exhaustive entertainment calendar.

## Automated source registry

The current registry includes these discovery and authoritative sources:

| Source | Role | Typical coverage |
|---|---|---|
| NewOrleans.com | tourism/event calendar | New Orleans festivals and public events |
| Visit Baton Rouge | tourism/event calendar | Baton Rouge metro events |
| Louisiana Northshore | tourism/event calendar | St. Tammany/Northshore events |
| Explore Houma | tourism/event calendar | Houma/Terrebonne events |
| Coastal Mississippi / Gulf Coast tourism calendars | tourism/event calendar | Mississippi Gulf Coast events, spatially limited to the LIX CWA |
| Mardi Gras New Orleans | parade schedule | New Orleans-area and Northshore Mardi Gras parades |
| Downtown Baton Rouge | downtown event calendar | Baton Rouge downtown events; strict outdoor/IDSS filtering required |
| Tangipahoa Parish Convention & Visitors Bureau | fairs/festivals calendar | Tangipahoa Parish festivals, fairs, airshows and large public events |
| Sun Herald Events | regional discovery | Mississippi Gulf Coast event discovery |
| LSU Athletics | official athletics | major LSU home outdoor sports |
| Tulane Athletics | official athletics | Tulane home football |
| Nicholls Athletics | official athletics | Nicholls home football |
| Southeastern Louisiana Athletics | official athletics | Southeastern home football |
| Southern University Athletics | official athletics | Southern home football |

Every published record retains source provenance. Appearing on a calendar is not sufficient for publication: the event must pass outdoor exposure, IDSS relevance, date-window, location-confidence, LIX-CWA, and deduplication gates.

## Curated safety net

`data/manual-events.json` remains as a curated safety net for major events and sources that are not yet reliably automated. This prevents a temporary source failure or site redesign from wiping known high-value events from the operational map.

## Source status notes

- **Mardi Gras New Orleans:** high-priority source. Its parade schedule is useful and largely static; a dedicated parser will provide better yield than generic JSON-LD extraction.
- **Downtown Baton Rouge:** readable event listings, but many are indoor. The strict outdoor/IDSS gate is intentional.
- **Tangipahoa Tourism:** high-value source for fairs and festivals. A dedicated static-page parser is appropriate because the event details are embedded directly on the page.
- **Coastal Mississippi:** official tourism calendar, but the listing is JavaScript-driven and may require a dedicated adapter.
- **Sun Herald:** retained as a secondary regional discovery source; automated access may be restricted or dynamic.
- **Gambit calendar:** candidate secondary discovery source at `https://www.nola.com/gambit/calendar/#/`. Do not treat it as a primary operational source until a stable automated-access path and provenance behavior are verified.

## Original/organizer preference

When the same event appears in several places, prefer the organizer, venue, government/tourism authority, or official athletics/parade source over a secondary media calendar. Secondary sources are useful for discovery, but deduplication should preserve the strongest provenance available.

See the approved design and implementation plan under `docs/superpowers/`.

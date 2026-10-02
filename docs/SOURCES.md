# Event Sources

This application is an IDSS support layer, not an exhaustive entertainment calendar.

## Automated source registry

The current registry includes these discovery and authoritative sources:

| Source | Role | Typical coverage |
|---|---|---|
| NewOrleans.com | tourism/event calendar | New Orleans festivals and public events |
| Visit Baton Rouge | tourism/event calendar | Baton Rouge metro events |
| Visit The Northshore | browser-rendered tourism/event calendar | St. Tammany/Northshore events |
| Explore Houma | tourism/event calendar | Houma/Terrebonne events |
| Coastal Mississippi | browser-rendered tourism/event calendar | Mississippi Gulf Coast events, spatially limited to the LIX CWA |
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

- **Mardi Gras New Orleans:** high-priority source parsed directly from visible schedule text; no longer depends on JSON-LD.
- **Downtown Baton Rouge:** readable event listings, but many are indoor. The strict outdoor/IDSS gate is intentional.
- **Tangipahoa Tourism:** high-value fairs/festivals source parsed directly from the static page's visible date blocks.
- **Visit Baton Rouge, Visit The Northshore, Coastal Mississippi:** JavaScript-driven tourism calendars collected through the rendered-listing adapter and hydrated from event detail pages.
- **Downtown Baton Rouge:** detail pages fall back to visible-text parsing when Event JSON-LD is absent.\n- **LSU Athletics:** uses a dedicated generic football schedule parser rather than relying on Event JSON-LD.\n- **Sun Herald:** retained as a secondary regional discovery source using its CitySpark-specific adapter.
- **Gambit calendar:** candidate secondary discovery source at `https://www.nola.com/gambit/calendar/#/`. Do not treat it as a primary operational source until a stable automated-access path and provenance behavior are verified.

## Original/organizer preference

When the same event appears in several places, prefer the organizer, venue, government/tourism authority, or official athletics/parade source over a secondary media calendar. Secondary sources are useful for discovery, but deduplication should preserve the strongest provenance available.

See the approved design and implementation plan under `docs/superpowers/`.

## Source health behavior

Sources marked `zero_is_failure` are treated as failed when collection returns zero event records. This is intentionally stricter than a successful HTTP response: a calendar that loads but yields no records should be visible as an ingestion failure instead of silently appearing healthy/degraded.

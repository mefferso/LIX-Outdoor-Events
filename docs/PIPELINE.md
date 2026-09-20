# Automated event pipeline

`Refresh Outdoor Events` runs every six hours and can also be started manually.

## Flow

1. Read enabled sources from `config/sources.json`.
2. Fetch each event-listing page independently.
3. Follow a bounded number of event-detail links and extract `schema.org/Event` JSON-LD.
4. Normalize dates, locations and source provenance.
5. Resolve known venues from `config/venues.json`; geocode only unresolved locations and cache the result.
6. Keep only events overlapping Today–Day 7.
7. Require outdoor or partially outdoor confidence and an IDSS-significant event type.
8. Reject points outside the authoritative NWS LIX CWA polygon.
9. Deduplicate across sources.
10. Merge the automated feed with `data/manual-events.json`, which acts as a curated safety net for major events and sources not yet automated.
11. Publish `web/data/events.json` and `web/data/build-metadata.json`.

Each source is isolated. A failed source is logged and the rest continue. If every enabled automated source fails, the job exits before overwriting the published dataset.

## Source onboarding

Prefer sources with event-detail pages containing `schema.org/Event` JSON-LD. Add the listing URL to `config/sources.json`. For a new source, start with a small `max_detail_pages`, manually inspect accepted events, then increase coverage.

Unknown indoor/outdoor events are excluded rather than guessed into the map.

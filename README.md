# LIX Outdoor Events

Operational situational-awareness map for significant outdoor events across the NWS New Orleans/Baton Rouge (LIX) County Warning Area.

**Purpose:** answer the IDSS question: *Where and when will meaningful concentrations of people be exposed to weather during the next eight calendar days?*

## Current state

The repository contains a deployed GitHub Pages application under `web/` backed by an automated multi-source Python collection pipeline.

Current capabilities include:

- Today through Day 7 in **America/Chicago**
- NOAA/NWS LIX CWA spatial filtering
- clustered event markers with event-type icons
- event list synchronized to the selected day
- category filters for sports, festivals/concerts, races/parades, coastal/marine, and other events
- event date/time, venue, parish/county, outdoor status, location confidence, and source provenance
- source-health status in the UI
- responsive desktop/mobile layout
- visible dataset freshness
- automated source refresh every six hours
- cached geocoding and deduplication across sources
- curated manual-event safety net

## Automated sources

The source registry is maintained in `config/sources.json` and currently includes tourism/event calendars, official college-football schedules, Mardi Gras/parade schedules, and regional event-discovery sources across the LIX CWA.

See `docs/SOURCES.md` for the current source list and `docs/PIPELINE.md` for collection and filtering logic.

## Run locally

From the repository root:

```bash
python -m http.server 8000 --directory web
```

Then open `http://localhost:8000`.

## Deployment

- `Refresh Outdoor Events` runs every six hours and on relevant source/config/code changes.
- The refresh workflow runs unit tests, rebuilds the event dataset, validates generated JSON, and commits refreshed data when it changes.
- `Deploy GitHub Pages` publishes the `web/` directory after successful refreshes and relevant web changes.
- Refresh runs are serialized to avoid concurrent data commits racing each other.

## Data policy

This is an **IDSS support layer**, not an exhaustive entertainment calendar. Routine small events, indoor events, events with unclear outdoor exposure, and events outside the LIX CWA are excluded by default. Unknown attendance is not fabricated.

Each published event retains source provenance. Automated sources are isolated so one failing source does not prevent healthy sources from refreshing. If every automated source fails, the pipeline protects the last-known-good published dataset.

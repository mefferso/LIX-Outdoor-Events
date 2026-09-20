# LIX Outdoor Events

Operational situational-awareness map for significant outdoor events across the NWS New Orleans/Baton Rouge (LIX) County Warning Area.

**Purpose:** answer the IDSS question: *Where and when will meaningful concentrations of people be exposed to weather during the next eight calendar days?*

## Current state

The repository now contains a deployable MVP under `web/`:

- Today through Day 7 in **America/Chicago**
- NOAA/NWS LIX CWA boundary
- clustered event markers
- event list synchronized to the selected day
- category filters plus **Major only**
- importance, outdoor status, location confidence, exposure notes, and source links
- responsive desktop/mobile layout
- visible dataset freshness

The initial dataset is deliberately small and evidence-backed so the interface can be evaluated before the automated collection pipeline starts feeding it.

## Run locally

From the repository root:

```bash
python -m http.server 8000 --directory web
```

Then open `http://localhost:8000`.

## Deployment

GitHub Pages deployment is handled by `.github/workflows/deploy-pages.yml`. The workflow publishes the `web/` directory whenever `main` changes.

## Data policy

This is an **IDSS support layer**, not an entertainment calendar. Routine small events, indoor events, and events with unclear outdoor exposure are excluded by default. Unknown attendance is not fabricated.

## Initial verified events

The seed dataset includes representative real events for the current operational window, including Celebración Latina, International Arts Festival: NOLA, BlackAmericana Fest, L.O.C.A.L.S. Fest, and LSU vs. Texas A&M.

This is a bootstrap dataset, **not** the final source architecture.

## Next implementation stage

The approved implementation plan remains in:

- `docs/superpowers/specs/2026-09-19-lix-outdoor-events-design.md`
- `docs/superpowers/plans/2026-09-19-lix-outdoor-events.md`

Next priority is the scheduled Python collector and source registry so the map is automatically refreshed from tourism calendars, official athletics schedules, organizers, venues, and government sources while preserving provenance and last-known-good data.

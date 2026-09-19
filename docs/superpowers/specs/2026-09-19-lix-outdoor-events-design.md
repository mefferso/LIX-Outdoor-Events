# LIX Outdoor Events — Design Specification

**Date:** 2026-09-19  
**Repository:** `mefferso/LIX-Outdoor-Events`  
**Status:** Approved design for implementation planning

## 1. Purpose

Build an operational situational-awareness application for NWS New Orleans/Baton Rouge (LIX) forecasters. The application will show significant outdoor events occurring today through seven days ahead within the LIX County Warning Area (CWA).

The product is an IDSS support layer, not a public entertainment calendar. Its primary question is:

> Where and when will meaningful concentrations of people be exposed to weather during the next eight calendar days?

Version 1 prioritizes event discovery, provenance, outdoor relevance, location accuracy, deduplication, and a fast map. It deliberately does not perform event/forecast or event/hazard intersections.

## 2. Success Criteria

Version 1 is successful when it:

1. Runs entirely from GitHub Pages and GitHub Actions without a personal server.
2. Shows today by default and supports Today through Day 7 in the `America/Chicago` time zone.
3. Displays only events confirmed or strongly supported as at least partly outdoors.
4. Uses the authoritative NWS LIX CWA polygon for spatial filtering.
5. Combines multiple independent sources and continues updating when an individual source fails.
6. Retains discovery and authoritative-source provenance for every event.
7. Places events at a known venue or event location whenever possible, not a city centroid.
8. Deduplicates overlapping listings while preserving all useful source references.
9. Makes data age, uncertainty, and source quality visible rather than inventing missing details.
10. Can add a new source through configuration plus an isolated adapter without changing the rest of the pipeline.
11. Loads quickly and remains readable on an operational desktop, tablet, and phone.
12. Includes real upcoming events and automated tests covering the critical data-quality rules.

## 3. Architecture Decision

### Selected approach

Use a Python collection and normalization pipeline scheduled through GitHub Actions. Commit or publish the generated JSON/GeoJSON and source-health metadata consumed by a static Leaflet frontend hosted on GitHub Pages.

### Why this approach

- GitHub Actions supplies scheduled compute without a personal server.
- GitHub Pages serves the last successful dataset even when a later collection run fails.
- Python has mature libraries for feeds, HTML parsing, dates, fuzzy matching, geometry, and tests.
- A static frontend avoids credentials, CORS-dependent live collection, databases, and runtime infrastructure.
- Isolated adapters keep fragile source-specific parsing away from shared normalization logic.

### Rejected alternatives

- **Browser-side collection:** exposes credentials, is restricted by CORS, repeats work for every user, and fails unpredictably when any source is slow.
- **Hosted API and database:** useful at larger scale, but unnecessary infrastructure for the eight-day version-1 product.
- **Single aggregator:** simpler initially but cannot provide adequate geographic coverage, authority, or resilience.

## 4. Repository Structure

```text
.
├── .github/workflows/
│   ├── refresh-events.yml
│   ├── deploy-pages.yml
│   └── test.yml
├── config/
│   ├── sources.yaml
│   ├── venues.yaml
│   ├── manual-events.yaml
│   └── scoring.yaml
├── data/
│   ├── boundaries/
│   │   ├── lix-cwa.geojson
│   │   └── counties-parishes.geojson
│   ├── cache/
│   │   └── geocoding.json
│   └── generated/
│       ├── events.geojson
│       ├── events.json
│       ├── source-status.json
│       └── build-metadata.json
├── docs/
│   ├── DATA_SCHEMA.md
│   ├── SOURCES.md
│   └── superpowers/specs/
├── scripts/
│   ├── refresh_events.py
│   └── update_boundaries.py
├── src/
│   └── lix_events/
│       ├── adapters/
│       ├── models.py
│       ├── normalize.py
│       ├── classify.py
│       ├── score.py
│       ├── deduplicate.py
│       ├── geocode.py
│       ├── spatial.py
│       ├── provenance.py
│       └── publish.py
├── tests/
│   ├── fixtures/
│   ├── test_adapters.py
│   ├── test_classification.py
│   ├── test_deduplication.py
│   ├── test_geolocation.py
│   ├── test_scoring.py
│   ├── test_spatial_filter.py
│   └── test_schema.py
├── web/
│   ├── index.html
│   ├── css/app.css
│   ├── js/app.js
│   ├── js/data.js
│   ├── js/map.js
│   ├── js/filters.js
│   └── js/popup.js
├── pyproject.toml
└── README.md
```

Small changes to filenames are acceptable during implementation when they improve clarity, but module responsibilities must remain separated.

## 5. Data Sources and Registry

`config/sources.yaml` is the source of truth for collection configuration. Every registry entry contains:

- stable source ID and display name
- source URL
- source type
- geographic coverage
- event categories
- ingestion method and adapter name
- authority level and priority
- refresh interval
- active status
- whether it is a discovery or authoritative source
- timeout and retry policy
- notes and known limitations

Initial coverage will include, where technically accessible:

- broad discovery calendars for New Orleans, Baton Rouge, the Northshore, Tangipahoa/Hammond, Houma/Thibodaux, the River Parishes, and the Mississippi portion of the CWA
- official athletics schedules for LSU, Southern, Tulane, UNO, Southeastern Louisiana, and Nicholls
- official city, parish, venue, race, parade, festival, park, and coastal/marine organizers
- maintainable manual overrides for important events lacking a stable public feed

Broad tourism or ticketing calendars are discovery sources. An organizer, venue, university athletics department, or government page becomes the authoritative source when available. Absence of an authoritative page does not automatically discard a credible candidate, but lowers confidence and preserves the discovery source as primary provenance.

Source-specific code lives in `src/lix_events/adapters/`. An adapter returns candidate records in one shared intermediate format. It does not perform global scoring, deduplication, geocoding, or CWA filtering.

## 6. Collection and Publication Flow

The scheduled pipeline follows this order:

1. Load and validate configuration.
2. Determine the collection window in `America/Chicago`.
3. Run active source adapters independently.
4. Record source success, failure, latency, and candidate count.
5. Normalize candidate fields and localize times.
6. Remove expired or explicitly cancelled occurrences.
7. Classify category and outdoor status.
8. Apply IDSS inclusion rules and relevance scoring.
9. Resolve known venues and coordinates.
10. Geocode unresolved exact addresses with caching and rate limiting.
11. Filter points against the LIX CWA polygon.
12. Detect and merge duplicate occurrences.
13. Select primary authoritative provenance while retaining all source references.
14. Validate every final record against the published schema.
15. Write deterministic JSON and GeoJSON outputs.
16. Publish only when validation succeeds.

Collection may look 30–45 days ahead to obtain stable recurring and multi-day information, but the frontend presents only Today through Day 7. Generated records from prior successful runs may be retained briefly for reconciliation, while expired events are never shown.

A failed adapter is logged and skipped. A failed validation or empty result caused by a systemic problem does not overwrite the last known-good published dataset.

## 7. Normalized Event Schema

Each final event supports:

- `id`: deterministic identifier for the normalized occurrence
- `name`
- `start` and `end`: ISO 8601 timestamps with UTC offsets
- `timezone`
- `all_day`
- `latitude` and `longitude`
- `geometry_type`: `point` in version 1
- `venue`
- `address`
- `city`
- `county_parish`
- `state`
- `category`
- `outdoor_status`: `outdoor` or `partial`
- `importance`: `major`, `moderate`, or `local`
- `idss_score`
- `attendance_estimate`: numeric only when sourced
- `attendance_category`: `very_large`, `large`, `medium`, `small`, or `unknown`
- `description`
- `weather_exposure_notes`
- `discovery_source`
- `authoritative_source`
- `source_url`
- `sources`: all contributing provenance records
- `location_method`
- `location_confidence`
- `outdoor_confidence`
- `attendance_confidence`
- `first_seen`
- `last_checked`
- `status`

Unknown attendance remains unknown. Version 1 never manufactures a numeric estimate. Routes and polygons are reserved schema extensions; area events use a representative point.

## 8. Outdoor Classification and IDSS Relevance

### Outdoor gate

The final map includes only `outdoor` and `partial` events. Evidence can come from structured source fields, venue metadata, organizer descriptions, event-category rules, or a reviewed manual override.

An event with genuinely unknown indoor/outdoor status remains a candidate but is excluded from the public dataset until evidence supports outdoor exposure. Confidence is recorded and shown in details when less than high.

### Scoring factors

The configurable relevance score considers:

- attendance category
- duration of outdoor exposure
- traffic or access impacts
- weather vulnerability
- event prominence
- geographic concentration
- special operational significance

The score produces `major`, `moderate`, or `local`. It is not a rigid attendance cutoff. Category rules can elevate weather-sensitive races, parades, marine events, air shows, and similar gatherings. Explicit `always_include` and `always_exclude` overrides are supported and documented.

Routine youth sports, individual high-school games, small recurring markets, indoor events, restaurant entertainment, classes, clubs, and neighborhood-scale gatherings are excluded by default. A source listing alone is not sufficient for inclusion.

The numerical weights and thresholds live in `config/scoring.yaml`, with tests demonstrating representative inclusion and exclusion decisions.

## 9. Geolocation and Boundaries

Coordinate resolution uses this priority:

1. source-provided event coordinates
2. curated exact venue coordinates from `config/venues.yaml`
3. event-specific verified location
4. normalized street address geocoding
5. city centroid only as an explicit low-confidence fallback

Geocoding results are cached in the repository output so unchanged locations are not repeatedly queried. Requests use a descriptive user agent, rate limiting, retries, and provider attribution. Low-confidence city-centroid records are visually and textually identified.

The CWA boundary is derived from the official NWS County Warning Area dataset and reduced to the `LIX` feature. The repository stores the source URL, source valid date, retrieval time, and checksum. A boundary maintenance script updates the committed GeoJSON when NWS publishes a replacement.

County and parish boundaries come from an authoritative public boundary dataset, are clipped/simplified for display, and do not replace the CWA polygon for inclusion decisions.

## 10. Deduplication and Provenance

Deduplication first blocks plausible matches by overlapping local date/time and geographic proximity. It then compares normalized names, venue names, city, and start time.

A high-confidence duplicate is merged when the records represent the same occurrence. The merge:

- favors authoritative and higher-priority values
- retains the most precise location
- retains the most specific time
- preserves every source record and URL
- keeps field-level confidence
- records the merge decision for diagnostics

Multi-day festivals become daily occurrences or a clearly defined span without producing overlapping duplicate markers. Separate sessions or games at the same venue remain distinct.

Ambiguous cases are not silently merged. They remain separate and are written to diagnostics for later rule or manual-override improvement.

## 11. Frontend Design

The static frontend uses Leaflet with a light basemap and a clustering plugin.

### Primary layout

- compact operational header with product title and data-freshness indicator
- clearly selected Today through Day 7 date strip
- restrained filters for All, Major, Sports, Festivals/Concerts, Races/Parades, Coastal/Marine, and Other
- map occupying the primary workspace
- compact visible count for the selected day and active filters

### Map behavior

- initial extent fits the LIX CWA
- CWA boundary is prominent but does not obscure the basemap
- parish/county boundaries are lighter secondary context
- nearby events cluster geographically at broad zoom levels
- cluster selection zooms or expands the contained events
- individual markers appear at close zoom levels
- marker appearance primarily communicates importance, with restrained category cues
- overlapping same-venue events remain individually accessible

### Event details

A marker popup or responsive detail card shows:

- event name and importance
- local date and time
- venue, city, and parish/county
- category and outdoor/partial designation
- attendance information when sourced
- exposure notes
- authoritative or best available source link
- relevant confidence qualifiers
- last checked time

The interface is desktop-first, keyboard accessible, touch usable, and responsive. It avoids dashboards, charts, animations, and decorative controls that do not improve operational awareness.

## 12. Refresh, Deployment, and Secrets

A scheduled GitHub Actions workflow refreshes event data approximately every six hours at off-peak UTC minutes and supports manual dispatch. Source registry refresh intervals prevent unnecessary requests to slower-changing sources.

GitHub Pages deploys the static frontend plus generated data. Deployment occurs only after tests and schema validation pass.

Version 1 prefers sources and geocoders that require no secret. If a valuable source requires credentials, the adapter reads them only from GitHub Actions Secrets, disables itself with a clear status when the secret is absent, and never exposes the secret to generated files, logs, or browser code.

## 13. Failure Handling and Observability

`source-status.json` records, per source:

- last attempt and last success
- status
- candidate and accepted counts
- elapsed time
- sanitized error summary

`build-metadata.json` records dataset generation time, event count, collection window, boundary version, pipeline version, and stale-data state.

The frontend distinguishes:

- current data
- stale but usable last-known-good data
- unavailable data

It never presents stale data as current. Source failures are visible in metadata without filling the map interface with engineering diagnostics.

## 14. Testing and Verification

Automated tests cover:

- source-registry validation
- adapter fixture parsing
- time-zone and multi-day handling
- cancellation and expiration
- outdoor classification
- representative IDSS scoring decisions
- venue lookup and geocoding cache behavior
- LIX polygon inclusion and exclusion
- duplicate merging and non-merging edge cases
- schema validation and deterministic output
- frontend data loading, date selection, filtering, clustering initialization, and popup rendering

Network-dependent adapter checks are separated from deterministic fixture tests. CI never depends solely on live third-party pages.

Before version 1 is declared complete:

1. Run the full test suite.
2. Run a real collection against active sources.
3. Inspect the generated event and source-health datasets.
4. Launch the site locally and exercise all eight dates and filters.
5. Verify representative events against their official source pages and map locations.
6. Inspect desktop and mobile layouts.
7. Verify the deployed GitHub Pages site and scheduled workflow.
8. Fix obvious display, data, console, workflow, and broken-link problems.

## 15. Manual Fallback and Maintenance

`config/manual-events.yaml` accepts schema-validated additions, corrections, exclusions, venue overrides, and source-verification notes. Every entry requires provenance, a reviewer note, and an expiration date or event end.

Manual data supplements automation; it does not become the routine primary feed. Expired overrides are automatically rejected.

The README and `docs/SOURCES.md` explain:

- current sources and geographic coverage
- discovery versus authoritative roles
- ingestion methods
- refresh frequency
- known gaps
- adding, disabling, or repairing a source
- adding a venue
- entering a manual event or override
- required secrets
- deployment and troubleshooting

## 16. Non-Goals for Version 1

Version 1 will not include:

- forecast grids, hazard polygons, watches, warnings, or lightning probabilities
- automated weather-impact scoring
- notifications or alerting
- event organizer accounts or browser editing
- full parade/race route geometry
- a hosted database or private server
- exhaustive small-event coverage
- attendance numbers inferred without a source

The event schema and modular pipeline leave room for later weather/event intersection without coupling version 1 to that work.

## 17. Version-1 Acceptance Checklist

Implementation is complete only when:

- [ ] GitHub Pages serves the operational map.
- [ ] Today through Day 7 work in Central Time.
- [ ] The LIX CWA and county/parish context render correctly.
- [ ] Individual markers and zoom-dependent clusters work.
- [ ] Popups provide the required event details and provenance.
- [ ] Useful operational filters work without clutter.
- [ ] Multiple active source adapters feed real events.
- [ ] One source failure does not abort publication.
- [ ] Outdoor gating, scoring, spatial filtering, and deduplication pass tests.
- [ ] Generated records validate against the documented schema.
- [ ] Location confidence and data freshness are visible.
- [ ] Scheduled refresh and manual dispatch work.
- [ ] No credentials appear in the repository or frontend.
- [ ] README and source documentation are complete.
- [ ] The deployed application has been checked directly.

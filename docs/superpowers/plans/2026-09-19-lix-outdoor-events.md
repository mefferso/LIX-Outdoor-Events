# LIX Outdoor Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a GitHub-hosted operational map of significant outdoor events occurring today through Day 7 within the NWS LIX CWA.

**Architecture:** A scheduled Python pipeline collects candidates from independent public-source adapters, normalizes and filters them, resolves locations, deduplicates occurrences, and publishes validated JSON/GeoJSON. A static Leaflet frontend reads those artifacts from GitHub Pages and provides Central-Time date selection, clustering, filtering, event details, and freshness information without a personal server.

**Tech Stack:** Python 3.12, Pydantic 2, httpx, PyYAML, Beautiful Soup 4, icalendar, RapidFuzz, Shapely, pyshp, pyproj, pytest, respx, vanilla ES modules, Leaflet 1.9.4, Leaflet.markercluster 1.5.3, Node 22 test runner, Playwright, GitHub Actions, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-09-19-lix-outdoor-events-design.md`

## Global Constraints

- Run entirely on GitHub Pages and GitHub Actions; do not introduce a personal server, hosted database, or runtime API.
- Treat `America/Chicago` as the operational timezone and expose Today through Day 7 inclusive.
- Publish only confirmed or strongly supported `outdoor` or `partial` events; exclude genuinely unknown outdoor status.
- Use the authoritative NWS LIX CWA polygon for spatial inclusion, not a parish or city allowlist.
- Never fabricate attendance, time, location, or authority; represent unknown values and confidence explicitly.
- Preserve all contributing sources while preferring official organizer, venue, government, or athletics data.
- One source failure must not abort collection or overwrite the last known-good dataset.
- Store no credentials in repository files, generated data, frontend code, or logs.
- Keep the frontend operational and restrained; do not add weather overlays, notifications, editing, charts, or decorative controls in version 1.
- Production frontend code remains static and build-free; npm packages are test-only.

## Review Focus

- **DST boundary:** events around spring-forward and fall-back must land on the correct Central-Time calendar day; Task 5 pins this behavior.
- **Malformed source:** one adapter returning invalid dates or HTML must produce a failed source status without blocking valid sources; Tasks 3 and 8 test this.
- **Same-name false duplicate:** separate sessions or games at the same venue must remain distinct when start times do not overlap; Task 7 tests this.
- **Boundary edge:** a point on the LIX boundary counts as inside, while a nearby point outside does not; Task 2 tests `covers`, not `contains`.
- **Stale publication:** a failed or suspiciously empty run must retain the prior artifacts and display their age honestly; Tasks 8 and 10 test this.

---

## File Responsibility Map

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Python package metadata, pinned dependency ranges, and pytest settings |
| `src/lix_events/models.py` | Shared enums and Pydantic data contracts |
| `src/lix_events/config.py` | YAML loading and configuration validation |
| `src/lix_events/adapters/base.py` | Adapter protocol and collection context |
| `src/lix_events/adapters/manual.py` | Schema-validated manual fallback records |
| `src/lix_events/adapters/ics.py` | Standards-based iCalendar ingestion |
| `src/lix_events/adapters/jsonld.py` | Listing discovery plus schema.org event-detail ingestion |
| `src/lix_events/adapters/sidearm.py` | Official university athletics calendar ingestion |
| `src/lix_events/collector.py` | Independent adapter execution and source-health accounting |
| `src/lix_events/normalize.py` | Text, datetime, category, and occurrence normalization |
| `src/lix_events/classify.py` | Outdoor evidence rules and exclusion decisions |
| `src/lix_events/score.py` | Configurable IDSS relevance score and importance band |
| `src/lix_events/geocode.py` | Venue lookup, Census address geocoding, cache, and centroid fallback |
| `src/lix_events/spatial.py` | LIX polygon loading and point filtering |
| `src/lix_events/deduplicate.py` | Duplicate candidate blocking, comparison, and merge |
| `src/lix_events/provenance.py` | Source ranking and field-selection policy |
| `src/lix_events/publish.py` | Deterministic schema validation and JSON/GeoJSON output |
| `src/lix_events/pipeline.py` | End-to-end orchestration and last-known-good safeguards |
| `scripts/refresh_events.py` | CLI entry point for scheduled/manual collection |
| `scripts/update_boundaries.py` | Download and convert current official boundaries |
| `scripts/probe_sources.py` | Inspect configured live sources and save sanitized fixtures |
| `config/*.yaml` | Registry, venue/centroid knowledge, scoring rules, manual records |
| `data/boundaries/*.geojson` | Versioned authoritative LIX and contextual county/parish geometry |
| `data/generated/*` | Browser-consumed events and health/freshness metadata |
| `web/js/date.js` | Central-Time date keys and Day 0–7 model |
| `web/js/filters.js` | Pure event/date/category filtering |
| `web/js/data.js` | Artifact loading and freshness state |
| `web/js/popup.js` | Safe event-detail markup |
| `web/js/map.js` | Leaflet layers, markers, clustering, and extent behavior |
| `web/js/app.js` | UI state and module coordination |
| `.github/workflows/*.yml` | CI, six-hour refresh, artifact deployment, and Pages release |

### Task 1: Package Foundation and Data Contracts

**Files:**
- Create: `pyproject.toml`
- Create: `src/lix_events/__init__.py`
- Create: `src/lix_events/models.py`
- Create: `src/lix_events/config.py`
- Create: `tests/test_models.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: YAML files and plain dictionaries.
- Produces: `SourceConfig`, `SourceRef`, `CandidateEvent`, `WorkingEvent`, `NormalizedEvent`, `SourceStatus`, `BuildMetadata`, and `load_source_registry(path: Path) -> list[SourceConfig]`.

- [ ] **Step 1: Add failing model and registry tests**

```python
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from lix_events.config import load_source_registry
from lix_events.models import CandidateEvent, OutdoorStatus


def test_candidate_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        CandidateEvent(
            source_id="official_test",
            source_event_id="42",
            name="Outdoor Festival",
            start=datetime(2026, 9, 20, 10, 0),
            source_url="https://example.gov/events/42",
        )


def test_registry_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - {id: dup, name: One, url: 'https://a.example', adapter: manual, active: true, authority: discovery, priority: 50, coverage: [lix], categories: [other], refresh_hours: 24}\n"
        "  - {id: dup, name: Two, url: 'https://b.example', adapter: manual, active: true, authority: official, priority: 90, coverage: [lix], categories: [sports], refresh_hours: 24}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate source id: dup"):
        load_source_registry(path)


def test_outdoor_enum_has_no_unknown_publish_state() -> None:
    assert {item.value for item in OutdoorStatus} == {"outdoor", "partial"}
```

- [ ] **Step 2: Run the tests and confirm the imports fail**

Run: `python -m pytest tests/test_models.py tests/test_config.py -q`

Expected: FAIL because `lix_events.models` and `lix_events.config` do not exist.

- [ ] **Step 3: Add package metadata and the typed contracts**

```toml
[project]
name = "lix-outdoor-events"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "beautifulsoup4>=4.12,<5",
  "httpx>=0.27,<1",
  "icalendar>=6,<7",
  "pyproj>=3.7,<4",
  "pyshp>=2.3,<3",
  "pydantic>=2.9,<3",
  "python-dateutil>=2.9,<3",
  "PyYAML>=6,<7",
  "rapidfuzz>=3.9,<4",
  "shapely>=2.0,<3",
]

[project.optional-dependencies]
test = ["pytest>=8,<9", "pytest-asyncio>=0.24,<1", "respx>=0.21,<1"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
asyncio_mode = "auto"
```

```python
class OutdoorStatus(StrEnum):
    OUTDOOR = "outdoor"
    PARTIAL = "partial"


class CandidateEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    source_event_id: str
    name: str
    start: datetime
    end: datetime | None = None
    venue: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    description: str | None = None
    source_url: HttpUrl
    raw_category: str | None = None

    @field_validator("start", "end")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("datetime must include a UTC offset")
        return value
```

Implement every field listed in the design schema on `NormalizedEvent`; use constrained latitude/longitude, confidence values from `0.0` to `1.0`, and timezone-aware datetimes. Implement registry uniqueness and URL validation in `load_source_registry`.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_models.py tests/test_config.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the foundation**

```bash
git add pyproject.toml src/lix_events tests/test_models.py tests/test_config.py
git commit -m "feat: add event data contracts and configuration validation"
```

### Task 2: Authoritative LIX Boundary and Spatial Filtering

**Files:**
- Create: `scripts/update_boundaries.py`
- Create: `src/lix_events/spatial.py`
- Create: `data/boundaries/lix-cwa.geojson`
- Create: `data/boundaries/counties-parishes.geojson`
- Create: `data/boundaries/metadata.json`
- Create: `tests/test_spatial.py`

**Interfaces:**
- Consumes: NWS CWA GeoJSON and event coordinates.
- Produces: `load_polygon(path: Path) -> BaseGeometry`, `point_is_in_cwa(latitude: float, longitude: float, polygon: BaseGeometry) -> bool`, and `filter_to_cwa(events, polygon) -> tuple[list[NormalizedEvent], list[NormalizedEvent]]`.

- [ ] **Step 1: Write spatial tests with known inside, outside, and edge points**

```python
from pathlib import Path

from shapely.geometry import Polygon

from lix_events.spatial import load_polygon, point_is_in_cwa


def test_known_lix_and_non_lix_points() -> None:
    polygon = load_polygon(Path("data/boundaries/lix-cwa.geojson"))
    assert point_is_in_cwa(29.9511, -90.0715, polygon)  # New Orleans
    assert point_is_in_cwa(30.4515, -91.1871, polygon)  # Baton Rouge
    assert point_is_in_cwa(30.5255, -89.6795, polygon)  # Picayune
    assert not point_is_in_cwa(30.2266, -93.2174, polygon)  # Lake Charles


def test_boundary_point_counts_as_inside() -> None:
    polygon = Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])
    assert point_is_in_cwa(0.5, 0.0, polygon)
```

- [ ] **Step 2: Run the tests and confirm missing boundary/module failures**

Run: `python -m pytest tests/test_spatial.py -q`

Expected: FAIL because the boundary files and `spatial.py` are absent.

- [ ] **Step 3: Implement boundary retrieval and spatial logic**

`update_boundaries.py` must fetch `https://www.weather.gov/gis/CWABounds`, select the newest official download whose valid date is not in the future, verify the downloaded checksum when supplied, extract the `LIX` feature, reproject to WGS84, simplify only the display copy, and write source URL, valid date, retrieval time, and SHA-256 to `metadata.json`. Use Census cartographic county boundaries for the clipped contextual layer.

```python
def point_is_in_cwa(latitude: float, longitude: float, polygon: BaseGeometry) -> bool:
    point = Point(longitude, latitude)
    return bool(polygon.covers(point))


def load_polygon(path: Path) -> BaseGeometry:
    payload = json.loads(path.read_text(encoding="utf-8"))
    geometries = [shape(feature["geometry"]) for feature in payload["features"]]
    return unary_union(geometries)
```

- [ ] **Step 4: Generate boundaries and run tests**

Run: `python scripts/update_boundaries.py`

Run: `python -m pytest tests/test_spatial.py -q`

Expected: boundary metadata names NWS as source; all tests PASS.

- [ ] **Step 5: Commit boundaries and spatial filtering**

```bash
git add scripts/update_boundaries.py src/lix_events/spatial.py data/boundaries tests/test_spatial.py
git commit -m "feat: add authoritative LIX boundary filtering"
```

### Task 3: Adapter Protocol, Manual Fallback, and Failure Isolation

**Files:**
- Create: `src/lix_events/adapters/__init__.py`
- Create: `src/lix_events/adapters/base.py`
- Create: `src/lix_events/adapters/manual.py`
- Create: `src/lix_events/collector.py`
- Create: `config/manual-events.yaml`
- Create: `tests/test_collector.py`
- Create: `tests/test_manual_adapter.py`

**Interfaces:**
- Consumes: `SourceConfig`, collection window, shared `httpx.AsyncClient`.
- Produces: `AdapterContext`, `SourceAdapter.fetch(source: SourceConfig, context: AdapterContext) -> list[CandidateEvent]`, and `collect_sources(configs, adapters, context) -> CollectionResult`.

- [ ] **Step 1: Write failure-isolation and manual-expiration tests**

```python
@pytest.mark.asyncio
async def test_failed_adapter_does_not_discard_successful_candidates() -> None:
    result = await collect_sources(
        configs=[good_config(), bad_config()],
        adapters={"good": GoodAdapter(), "bad": BrokenAdapter()},
        context=test_context(),
    )
    assert [event.name for event in result.candidates] == ["Riverfront Race"]
    assert result.statuses["good"].status == "success"
    assert result.statuses["bad"].status == "failed"
    assert "secret" not in (result.statuses["bad"].error or "")


def test_manual_adapter_rejects_expired_override(tmp_path: Path) -> None:
    path = write_manual_file(tmp_path, end="2026-09-18T20:00:00-05:00")
    adapter = ManualAdapter(path)
    assert adapter.load(now=datetime(2026, 9, 19, tzinfo=ZoneInfo("America/Chicago"))) == []
```

- [ ] **Step 2: Run tests and verify missing interfaces**

Run: `python -m pytest tests/test_collector.py tests/test_manual_adapter.py -q`

Expected: FAIL because adapter and collector modules do not exist.

- [ ] **Step 3: Implement the adapter contract and sanitized status accounting**

```python
@dataclass(frozen=True)
class AdapterContext:
    client: httpx.AsyncClient
    window_start: datetime
    window_end: datetime
    timezone: ZoneInfo


class SourceAdapter(Protocol):
    async def fetch(self, source: SourceConfig, context: AdapterContext) -> list[CandidateEvent]:
        pass


@dataclass
class CollectionResult:
    candidates: list[CandidateEvent]
    statuses: dict[str, SourceStatus]
```

Run adapters independently with per-source timeouts. Sanitize query strings and exception text before storing errors. Validate manual records, provenance, reviewer note, and expiration before returning candidates.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_collector.py tests/test_manual_adapter.py -q`

Expected: PASS.

- [ ] **Step 5: Commit adapter infrastructure**

```bash
git add src/lix_events/adapters src/lix_events/collector.py config/manual-events.yaml tests/test_collector.py tests/test_manual_adapter.py
git commit -m "feat: add resilient source adapter framework"
```

### Task 4: Automated Public-Source Discovery and Official Calendars

**Files:**
- Create: `src/lix_events/adapters/ics.py`
- Create: `src/lix_events/adapters/jsonld.py`
- Create: `src/lix_events/adapters/sidearm.py`
- Create: `scripts/probe_sources.py`
- Create: `config/sources.yaml`
- Create: `tests/fixtures/ics/official-calendar.ics`
- Create: `tests/fixtures/jsonld/tourism-listing.html`
- Create: `tests/fixtures/jsonld/event-detail.html`
- Create: `tests/fixtures/sidearm/calendar.html`
- Create: `tests/test_ics_adapter.py`
- Create: `tests/test_jsonld_adapter.py`
- Create: `tests/test_sidearm_adapter.py`

**Interfaces:**
- Consumes: public iCal feeds, list/detail HTML, schema.org `Event` JSON-LD, and Sidearm calendar HTML/links.
- Produces: timezone-aware `CandidateEvent` lists through the Task 3 protocol.

- [ ] **Step 1: Capture sanitized fixtures from the official source pages**

Configure these initial registry URLs before probing:

- `https://www.neworleans.com/events/`
- `https://www.visitbatonrouge.com/events/`
- `https://www.louisiananorthshore.com/events/`
- `https://explorehouma.com/events/`
- `https://www.gulfcoast.org/events/`
- `https://lsusports.net/calendar/`
- `https://tulanegreenwave.com/calendar`
- `https://gojagsports.com/calendar`
- `https://lionsports.net/calendar`
- `https://geauxcolonels.com/calendar`
- `https://unoprivateers.com/calendar`

Run: `python scripts/probe_sources.py --registry config/sources.yaml --output tests/fixtures/live-probe`

The probe reports HTTP status, content type, discovered iCal links, JSON-LD event count, event-detail links, and Sidearm signatures. It strips scripts unrelated to structured data, tracking parameters, cookies, and personal data before fixture storage.

- [ ] **Step 2: Write adapter tests against fixed fixtures**

```python
@pytest.mark.asyncio
async def test_ics_expands_occurrences_and_localizes_times() -> None:
    events = await fixture_adapter("official-calendar.ics").fetch(source_config(), context())
    assert events[0].name == "Bayou Road Race"
    assert events[0].start.isoformat() == "2026-09-20T07:00:00-05:00"


@pytest.mark.asyncio
async def test_jsonld_follows_only_same_source_event_links() -> None:
    events = await jsonld_fixture_adapter().fetch(source_config(), context())
    assert {event.name for event in events} == {"Outdoor Arts Festival"}
    assert all(str(event.source_url).startswith("https://events.example.org/") for event in events)


@pytest.mark.asyncio
async def test_sidearm_keeps_only_home_outdoor_sports() -> None:
    events = await sidearm_fixture_adapter().fetch(source_config(), context())
    assert [(event.name, event.venue) for event in events] == [("LSU Baseball vs. Tulane", "Alex Box Stadium")]
```

- [ ] **Step 3: Run adapter tests and confirm failures**

Run: `python -m pytest tests/test_ics_adapter.py tests/test_jsonld_adapter.py tests/test_sidearm_adapter.py -q`

Expected: FAIL because the three adapters are absent.

- [ ] **Step 4: Implement bounded, cache-friendly adapters**

The iCal adapter expands recurrences only through the configured collection window. The JSON-LD adapter visits only same-host links matching configured event-link selectors, caps detail requests per run, and parses schema.org `Event`, `SportsEvent`, `Festival`, and `MusicEvent`. The Sidearm adapter extracts home schedule entries and rejects explicitly away/neutral events outside the LIX polygon pipeline.

```python
SUPPORTED_JSONLD_TYPES = {"Event", "SportsEvent", "Festival", "MusicEvent"}


def iter_event_nodes(payload: object) -> Iterator[dict[str, object]]:
    nodes = payload if isinstance(payload, list) else [payload]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        graph = node.get("@graph")
        if isinstance(graph, list):
            yield from iter_event_nodes(graph)
        node_type = node.get("@type")
        types = {node_type} if isinstance(node_type, str) else set(node_type or [])
        if types & SUPPORTED_JSONLD_TYPES:
            yield node
```

Add registry entries with explicit adapter, authority, priority, coverage, categories, refresh interval, request cap, and known limitations. Keep sources inactive only when the probe proves they block automated access; document the exact fallback source for each inactive registry entry.

- [ ] **Step 5: Run fixture tests and one bounded live probe**

Run: `python -m pytest tests/test_ics_adapter.py tests/test_jsonld_adapter.py tests/test_sidearm_adapter.py -q`

Run: `python scripts/probe_sources.py --registry config/sources.yaml --active-only --no-save`

Expected: tests PASS; probe exits zero when at least two broad discovery sources and two official athletics sources are reachable, while reporting individual failures without aborting.

- [ ] **Step 6: Commit source discovery**

```bash
git add src/lix_events/adapters scripts/probe_sources.py config/sources.yaml tests/fixtures tests/test_ics_adapter.py tests/test_jsonld_adapter.py tests/test_sidearm_adapter.py
git commit -m "feat: ingest regional calendars and official athletics"
```

### Task 5: Normalization, Outdoor Classification, and IDSS Scoring

**Files:**
- Create: `src/lix_events/normalize.py`
- Create: `src/lix_events/classify.py`
- Create: `src/lix_events/score.py`
- Create: `config/scoring.yaml`
- Create: `tests/test_normalize.py`
- Create: `tests/test_classification.py`
- Create: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `CandidateEvent` and scoring configuration.
- Produces: `normalize_candidate(candidate, timezone) -> WorkingEvent`, `classify_outdoor(event, rules) -> OutdoorDecision`, and `score_event(event, rules) -> ScoreDecision`.

- [ ] **Step 1: Write decision tests, including DST and operational exceptions**

```python
def test_fall_back_occurrences_keep_distinct_offsets_and_same_local_day() -> None:
    first = parse_source_datetime("2026-11-01T01:30:00-05:00")
    second = parse_source_datetime("2026-11-01T01:30:00-06:00")
    assert first.utcoffset() != second.utcoffset()
    assert local_date_key(first) == local_date_key(second) == "2026-11-01"


@pytest.mark.parametrize(
    ("name", "description", "venue_outdoor", "included"),
    [
        ("City Marathon", "26.2 mile road race", False, True),
        ("Weekly Book Club", "meeting in conference room", False, False),
        ("Live After Five", "outdoor concert series", False, True),
        ("Basketball Game", "arena game", False, False),
    ],
)
def test_outdoor_gate(name: str, description: str, venue_outdoor: bool, included: bool) -> None:
    decision = classify_outdoor(working_event(name, description, venue_outdoor), rules())
    assert decision.publish is included


def test_small_heat_sensitive_race_outranks_large_indoor_event() -> None:
    race = score_event(working_race(attendance_category="medium"), rules())
    arena = score_event(working_indoor_concert(attendance_category="very_large"), rules())
    assert race.score > arena.score
    assert race.include is True
    assert arena.include is False
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_normalize.py tests/test_classification.py tests/test_scoring.py -q`

Expected: FAIL because decision modules are missing.

- [ ] **Step 3: Implement deterministic rules and reasons**

```yaml
importance_thresholds:
  major: 10
  moderate: 6
  local: 4
factors:
  attendance: {unknown: 0, small: 0, medium: 2, large: 3, very_large: 4}
  outdoor_duration: {under_2h: 0, 2_to_4h: 1, over_4h: 2, multi_day: 2}
  traffic_impact: {none: 0, localized: 1, regional: 2}
  weather_vulnerability: {normal: 0, elevated: 2, high: 3}
  prominence: {local: 0, regional: 1, major: 2}
category_adjustments:
  race: 2
  parade: 2
  coastal_marine: 2
  air_show: 3
default_exclusions:
  - youth_sports
  - high_school_game
  - indoor
  - restaurant_entertainment
  - routine_class
  - small_recurring_market
```

Every decision returns machine-readable reasons. Normalize whitespace, event names, categories, end times, all-day semantics, and `America/Chicago` offsets without discarding original provenance.

- [ ] **Step 4: Run decision tests**

Run: `python -m pytest tests/test_normalize.py tests/test_classification.py tests/test_scoring.py -q`

Expected: PASS.

- [ ] **Step 5: Commit decision logic**

```bash
git add src/lix_events/normalize.py src/lix_events/classify.py src/lix_events/score.py config/scoring.yaml tests/test_normalize.py tests/test_classification.py tests/test_scoring.py
git commit -m "feat: classify outdoor exposure and IDSS relevance"
```

### Task 6: Venue Resolution, Address Geocoding, and Confidence

**Files:**
- Create: `src/lix_events/geocode.py`
- Create: `config/venues.yaml`
- Create: `config/city-centroids.yaml`
- Create: `data/cache/geocoding.json`
- Create: `tests/test_geocode.py`

**Interfaces:**
- Consumes: `WorkingEvent`, venue registry, local cache, and the public U.S. Census geocoder.
- Produces: `LocationResolver.resolve(event: WorkingEvent) -> LocationDecision` with method and confidence.

- [ ] **Step 1: Write priority and cache tests**

```python
def test_source_coordinates_beat_venue_and_geocoder() -> None:
    decision = resolver().resolve(event(latitude=30.1, longitude=-90.2, venue="Tiger Stadium"))
    assert decision.method == "source_coordinates"
    assert (decision.latitude, decision.longitude) == (30.1, -90.2)


def test_known_venue_avoids_network_request() -> None:
    client = MockGeocoder()
    decision = resolver(client=client).resolve(event(venue="Tiger Stadium", city="Baton Rouge"))
    assert decision.method == "venue_registry"
    assert decision.confidence >= 0.95
    assert client.calls == []


def test_cached_address_avoids_repeat_geocoding() -> None:
    first = resolver().resolve(event(address="1 Government St, Baton Rouge, LA"))
    second = resolver(network_forbidden=True).resolve(event(address="1 Government St, Baton Rouge, LA"))
    assert second == first
```

- [ ] **Step 2: Run tests and verify missing resolver**

Run: `python -m pytest tests/test_geocode.py -q`

Expected: FAIL because `geocode.py` is missing.

- [ ] **Step 3: Implement strict resolution order and Census lookup**

```python
RESOLUTION_CONFIDENCE = {
    "source_coordinates": 1.0,
    "venue_registry": 0.98,
    "verified_event_location": 0.95,
    "census_address": 0.85,
    "city_centroid": 0.35,
}


def address_cache_key(address: str) -> str:
    normalized = " ".join(address.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
```

Seed `venues.yaml` with major outdoor venues and recurring event grounds across Baton Rouge, New Orleans, Northshore, Bayou Region, River Parishes, coastal communities, and the Mississippi portion of LIX. Seed city centroids only for final fallback. Census requests use `https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress`, a descriptive user agent, timeout, retry, and repository cache.

- [ ] **Step 4: Run geolocation tests**

Run: `python -m pytest tests/test_geocode.py -q`

Expected: PASS without live network access.

- [ ] **Step 5: Commit location resolution**

```bash
git add src/lix_events/geocode.py config/venues.yaml config/city-centroids.yaml data/cache/geocoding.json tests/test_geocode.py
git commit -m "feat: resolve event locations with confidence"
```

### Task 7: Deduplication, Source Priority, and Provenance Merge

**Files:**
- Create: `src/lix_events/deduplicate.py`
- Create: `src/lix_events/provenance.py`
- Create: `tests/test_deduplication.py`
- Create: `tests/test_provenance.py`

**Interfaces:**
- Consumes: located, classified `WorkingEvent` records.
- Produces: `deduplicate(events) -> DeduplicationResult`, `duplicate_score(left, right) -> float`, and `merge_occurrences(group) -> NormalizedEvent`.

- [ ] **Step 1: Write true-duplicate and false-duplicate tests**

```python
def test_merges_tourism_and_official_listing_but_keeps_both_sources() -> None:
    result = deduplicate([tourism_festival(), official_festival()])
    assert len(result.events) == 1
    merged = result.events[0]
    assert merged.authoritative_source == "festival_organizer"
    assert {source.source_id for source in merged.sources} == {"visit_baton_rouge", "festival_organizer"}


def test_same_venue_same_name_separate_sessions_do_not_merge() -> None:
    morning = game(start="2026-09-20T10:00:00-05:00", end="2026-09-20T12:00:00-05:00")
    evening = game(start="2026-09-20T18:00:00-05:00", end="2026-09-20T20:00:00-05:00")
    assert len(deduplicate([morning, evening]).events) == 2


def test_multi_day_event_remains_one_span() -> None:
    result = deduplicate([festival_span(), festival_second_source()])
    assert len(result.events) == 1
    assert result.events[0].start.date().isoformat() == "2026-09-19"
    assert result.events[0].end.date().isoformat() == "2026-09-21"
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m pytest tests/test_deduplication.py tests/test_provenance.py -q`

Expected: FAIL because merge modules do not exist.

- [ ] **Step 3: Implement blocked fuzzy matching and deterministic merge rules**

Block comparisons to events whose local date spans overlap or are adjacent for cross-midnight cases and whose coordinates are within 5 km. Require a weighted score from normalized name, venue, time overlap, and location. Never merge two records solely because venue and date match.

```python
def duplicate_score(left: WorkingEvent, right: WorkingEvent) -> float:
    name = fuzz.token_set_ratio(left.normalized_name, right.normalized_name) / 100
    venue = fuzz.token_set_ratio(left.normalized_venue, right.normalized_venue) / 100
    time = time_overlap_score(left.start, left.end, right.start, right.end)
    distance = distance_score(left.latitude, left.longitude, right.latitude, right.longitude)
    return round(0.50 * name + 0.20 * venue + 0.20 * time + 0.10 * distance, 4)
```

Use source priority, authority level, field specificity, and location confidence to select primary fields. Preserve all `SourceRef` entries in stable priority order and produce diagnostics for scores in the review band.

- [ ] **Step 4: Run merge tests**

Run: `python -m pytest tests/test_deduplication.py tests/test_provenance.py -q`

Expected: PASS.

- [ ] **Step 5: Commit merge logic**

```bash
git add src/lix_events/deduplicate.py src/lix_events/provenance.py tests/test_deduplication.py tests/test_provenance.py
git commit -m "feat: deduplicate events and preserve provenance"
```

### Task 8: Deterministic Publication and Last-Known-Good Pipeline

**Files:**
- Create: `src/lix_events/publish.py`
- Create: `src/lix_events/pipeline.py`
- Create: `scripts/refresh_events.py`
- Create: `docs/DATA_SCHEMA.md`
- Create: `data/generated/events.json`
- Create: `data/generated/events.geojson`
- Create: `data/generated/source-status.json`
- Create: `data/generated/build-metadata.json`
- Create: `tests/test_publish.py`
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: source registry, adapters, rules, boundaries, location registries, and prior generated artifacts.
- Produces: `run_pipeline(settings) -> PipelineResult` and atomic browser artifacts.

- [ ] **Step 1: Write deterministic output and stale-data protection tests**

```python
def test_publish_is_deterministic(tmp_path: Path) -> None:
    first = publish_dataset([event_b(), event_a()], metadata(), tmp_path / "one")
    second = publish_dataset([event_a(), event_b()], metadata(), tmp_path / "two")
    assert (first / "events.json").read_bytes() == (second / "events.json").read_bytes()


def test_empty_systemic_failure_keeps_last_known_good(tmp_path: Path) -> None:
    seed_generated_files(tmp_path, event_count=5)
    result = run_pipeline(settings(tmp_path), collector=all_sources_failed())
    assert result.published is False
    assert json.loads((tmp_path / "events.json").read_text())["events"]
    assert result.metadata.stale is True


def test_valid_zero_event_day_is_publishable(tmp_path: Path) -> None:
    result = run_pipeline(settings(tmp_path), collector=successful_empty_sources(count=4))
    assert result.published is True
    assert result.metadata.event_count == 0
```

- [ ] **Step 2: Run publication tests and verify failure**

Run: `python -m pytest tests/test_publish.py tests/test_pipeline.py -q`

Expected: FAIL because publication and orchestration are absent.

- [ ] **Step 3: Implement ordered orchestration and atomic writes**

```python
PIPELINE_STAGES = (
    "collect",
    "normalize",
    "outdoor_gate",
    "score",
    "locate",
    "spatial_filter",
    "deduplicate",
    "validate",
    "publish",
)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
```

Systemic failure is: no source succeeds, schema validation fails, the boundary cannot load, or the resulting count drops by more than 90% while every broad discovery source failed. A successful empty run is allowed when at least two broad sources and two official sources succeed and independently return no included events. Write timestamps and datetimes in stable ISO format, sort records by start/name/id, and document every published field in `DATA_SCHEMA.md`.

- [ ] **Step 4: Run pipeline tests and generate a local dataset**

Run: `python -m pytest tests/test_publish.py tests/test_pipeline.py -q`

Run: `python scripts/refresh_events.py --offline-fixtures tests/fixtures --now 2026-09-19T12:00:00-05:00`

Expected: tests PASS; four valid generated files exist and contain no expired event.

- [ ] **Step 5: Commit the publication pipeline**

```bash
git add src/lix_events/publish.py src/lix_events/pipeline.py scripts/refresh_events.py docs/DATA_SCHEMA.md data/generated tests/test_publish.py tests/test_pipeline.py
git commit -m "feat: publish validated last-known-good event data"
```

### Task 9: Frontend Date Model, Filters, Data Freshness, and Safe Details

**Files:**
- Create: `package.json`
- Create: `web/js/date.js`
- Create: `web/js/filters.js`
- Create: `web/js/data.js`
- Create: `web/js/popup.js`
- Create: `tests/web/date.test.mjs`
- Create: `tests/web/filters.test.mjs`
- Create: `tests/web/data.test.mjs`
- Create: `tests/web/popup.test.mjs`

**Interfaces:**
- Consumes: generated event/metadata JSON.
- Produces: `dayOptions(now)`, `eventOverlapsDay(event, key)`, `filterEvents(events, state)`, `freshnessState(metadata, now)`, and `renderEventDetails(event)`.

- [ ] **Step 1: Add pure frontend behavior tests**

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { dayOptions, eventOverlapsDay } from "../../web/js/date.js";

test("builds Today through Day 7 in America/Chicago near UTC rollover", () => {
  const options = dayOptions(new Date("2026-09-20T03:30:00Z"));
  assert.equal(options[0].key, "2026-09-19");
  assert.equal(options[0].label, "Today");
  assert.equal(options[7].key, "2026-09-26");
});

test("multi-day event appears on every overlapping local day", () => {
  const event = { start: "2026-09-19T10:00:00-05:00", end: "2026-09-21T18:00:00-05:00" };
  assert.equal(eventOverlapsDay(event, "2026-09-20"), true);
});
```

Add tests proving category/importance filters compose, stale metadata becomes `stale`, unavailable fetch becomes `unavailable`, and HTML in an event name is escaped rather than executed.

- [ ] **Step 2: Run Node tests and confirm missing modules**

Run: `npm test`

Expected: FAIL because frontend modules do not exist.

- [ ] **Step 3: Implement pure modules without browser-global coupling**

```json
{
  "private": true,
  "type": "module",
  "scripts": {
    "test": "node --test tests/web/*.test.mjs",
    "test:e2e": "playwright test"
  },
  "devDependencies": {
    "@playwright/test": "^1.55.0",
    "jsdom": "^26.1.0"
  }
}
```

```javascript
export const APP_TIME_ZONE = "America/Chicago";

export function eventOverlapsDay(event, dayKey) {
  const startKey = centralDateKey(new Date(event.start));
  const endKey = centralDateKey(new Date(event.end ?? event.start));
  return startKey <= dayKey && dayKey <= endKey;
}
```

Freshness is `current` through 12 hours after generation, `stale` afterward, and `unavailable` only when no valid artifacts can load. Popup markup uses DOM text nodes or a dedicated escape function for every source field.

- [ ] **Step 4: Run frontend unit tests**

Run: `npm test`

Expected: PASS.

- [ ] **Step 5: Commit frontend logic**

```bash
git add package.json package-lock.json web/js tests/web
git commit -m "feat: add event date filtering and freshness logic"
```

### Task 10: Operational Leaflet Interface and Marker Clustering

**Files:**
- Create: `web/index.html`
- Create: `web/css/app.css`
- Create: `web/js/map.js`
- Create: `web/js/app.js`
- Create: `web/vendor/ATTRIBUTION.md`
- Create: `playwright.config.mjs`
- Create: `tests/e2e/app.spec.mjs`

**Interfaces:**
- Consumes: Task 9 modules, generated artifacts, CWA GeoJSON, county/parish GeoJSON, Leaflet, and Leaflet.markercluster.
- Produces: initialized map, date/filter controls, clustered markers, event popups/cards, counts, and freshness banner.

- [ ] **Step 1: Write the browser smoke test**

```javascript
import { test, expect } from "@playwright/test";

test("loads Today, clusters events, and opens event details", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "LIX Outdoor Events" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Today/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".leaflet-marker-icon, .marker-cluster").first()).toBeVisible();
  await page.locator(".leaflet-marker-icon, .marker-cluster").first().click();
  await expect(page.locator(".event-details, .leaflet-popup").first()).toBeVisible();
});

test("layout has no horizontal overflow at tablet width", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.goto("/");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});
```

- [ ] **Step 2: Run the smoke test and confirm the site is absent**

Run: `npx playwright install chromium && npm run test:e2e`

Expected: FAIL because `web/index.html` and application modules are missing.

- [ ] **Step 3: Build the restrained operational shell**

Use Leaflet 1.9.4 and Leaflet.markercluster 1.5.3 with integrity hashes. Use a light attributed basemap, initial fit to the LIX boundary, strong CWA outline, subdued county/parish lines, importance-led marker styling, and cluster counts. Header contains only title, freshness, selected-day count, Today–Day 7 strip, and specified filters.

```javascript
export function createEventLayer(map, onSelect) {
  const cluster = L.markerClusterGroup({
    showCoverageOnHover: false,
    spiderfyOnMaxZoom: true,
    disableClusteringAtZoom: 12,
    maxClusterRadius: 55,
  });
  cluster.on("click", (event) => onSelect(event.layer?.options?.eventId ?? null));
  map.addLayer(cluster);
  return cluster;
}
```

Ensure date buttons are keyboard operable with `aria-pressed`, filters use visible labels, marker details provide an official/best-source link, low-confidence locations are labeled, and same-location markers spiderfy at close zoom.

- [ ] **Step 4: Run unit and browser tests, then inspect two viewports**

Run: `npm test && npm run test:e2e`

Expected: PASS at Chromium desktop and tablet viewports with no console errors.

- [ ] **Step 5: Commit the map interface**

```bash
git add web playwright.config.mjs tests/e2e
git commit -m "feat: build operational clustered event map"
```

### Task 11: Continuous Testing, Scheduled Refresh, and GitHub Pages Deployment

**Files:**
- Create: `.github/workflows/test.yml`
- Create: `.github/workflows/refresh-events.yml`
- Create: `.github/workflows/deploy-pages.yml`
- Create: `tests/test_workflows.py`

**Interfaces:**
- Consumes: repository code, GitHub Actions runner, optional Actions secrets.
- Produces: required CI status, six-hour refresh, committed generated data, and deployed Pages artifact.

- [ ] **Step 1: Add workflow-policy tests**

```python
def test_refresh_has_schedule_dispatch_permissions_and_concurrency() -> None:
    workflow = load_workflow(".github/workflows/refresh-events.yml")
    assert workflow[True]["schedule"][0]["cron"] == "17 */6 * * *"
    assert "workflow_dispatch" in workflow[True]
    assert workflow["permissions"]["contents"] == "write"
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_pages_deploy_uses_official_actions_pinned_to_major_versions() -> None:
    text = Path(".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
    assert "actions/upload-pages-artifact@v3" in text
    assert "actions/deploy-pages@v4" in text
```

- [ ] **Step 2: Run policy tests and verify missing workflows**

Run: `python -m pytest tests/test_workflows.py -q`

Expected: FAIL because workflows do not exist.

- [ ] **Step 3: Implement CI, refresh, and deployment workflows**

`test.yml` runs Python and Node tests on pushes and pull requests. `refresh-events.yml` runs at `17 */6 * * *` and manual dispatch, installs locked dependencies, runs live collection, validates outputs, commits only changed generated/cache files with the Actions bot identity, uploads a Pages artifact, and deploys that artifact in the same workflow so bot commits do not need to trigger a second workflow. `deploy-pages.yml` deploys normal `main` pushes after tests.

```yaml
permissions:
  contents: write
  pages: write
  id-token: write

concurrency:
  group: lix-events-refresh
  cancel-in-progress: false
```

Assemble the Pages artifact in a temporary directory containing `web/`, `data/generated/`, and `data/boundaries/` at the relative paths expected by the frontend. Add explicit timeouts and retain probe/status artifacts on failure.

- [ ] **Step 4: Validate workflow syntax and run the full local suite**

Run: `python -m pytest tests/test_workflows.py -q && python -m pytest -q && npm test && npm run test:e2e`

Expected: PASS.

- [ ] **Step 5: Commit automation**

```bash
git add .github/workflows tests/test_workflows.py
git commit -m "ci: automate event refresh and Pages deployment"
```

### Task 12: Documentation, Live Data Verification, and Production Acceptance

**Files:**
- Modify: `README.md`
- Create: `docs/SOURCES.md`
- Create: `docs/OPERATIONS.md`
- Create: `docs/verification/2026-09-19-v1-check.md`
- Modify: `config/sources.yaml`
- Modify: `config/venues.yaml`
- Modify: `data/generated/*`

**Interfaces:**
- Consumes: completed repository, live public sources, GitHub workflow results, and deployed Pages URL.
- Produces: maintainable operator documentation and evidence that version 1 meets the acceptance checklist.

- [ ] **Step 1: Replace the one-line README with operational documentation**

Document purpose, architecture, local setup, data flow, update cadence, source roles, schema links, adding a source, adding a venue, manual fallback, required/optional secrets, GitHub Pages configuration, troubleshooting, limitations, and future weather integration boundary.

`docs/SOURCES.md` must include one row per registry source with coverage, category, authority, adapter, refresh interval, active state, last verified date, and limitation. `docs/OPERATIONS.md` must explain manual dispatch, interpreting source health, stale-data recovery, boundary updates, and safe rollback.

- [ ] **Step 2: Run a real collection and inspect source health**

Run: `python scripts/refresh_events.py --live --verbose`

Run: `python -m json.tool data/generated/build-metadata.json`

Run: `python -m json.tool data/generated/source-status.json`

Expected: at least two broad discovery sources and two official sources succeed; an individual failure is recorded without aborting; every published event falls inside LIX and has outdoor evidence plus provenance.

- [ ] **Step 3: Verify representative records against authoritative pages**

Select at least one sports event, one festival/concert, and one race/parade/coastal event when present. Record in `docs/verification/2026-09-19-v1-check.md` the published ID, authoritative URL, verified time, venue-coordinate result, outdoor evidence, and deduplication result. If a category has no event in the eight-day window, record the successful fixture test that covers it rather than inventing a live example.

- [ ] **Step 4: Run all automated verification**

Run: `python -m pytest -q`

Run: `npm test`

Run: `npm run test:e2e`

Run: `python scripts/refresh_events.py --live --check-only`

Expected: every command exits zero; no schema, console, broken-link, secret-scan, or stale-metadata error remains.

- [ ] **Step 5: Deploy and inspect the live application**

Trigger `deploy-pages.yml` on `main`. Open `https://mefferso.github.io/LIX-Outdoor-Events/` and verify all eight date buttons, each filter, clustering and spiderfying, representative popup links, data freshness, CWA fit, desktop layout, and tablet/mobile overflow. Record the workflow run URL and deployed commit SHA in the verification document.

- [ ] **Step 6: Commit documentation and verified data**

```bash
git add README.md docs config/sources.yaml config/venues.yaml data/generated
git commit -m "docs: complete source registry and production verification"
```

- [ ] **Step 7: Final acceptance check**

Compare the deployed app and verification record against every checkbox in Section 17 of the design specification. Mark only evidence-backed items complete; fix and recommit any failed item before declaring version 1 complete.

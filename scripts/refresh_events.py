#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/Chicago")
USER_AGENT = "LIX-Outdoor-Events/1.0 (+https://github.com/mefferso/LIX-Outdoor-Events)"
BOUNDARY_URL = (
    "https://mapservices.weather.noaa.gov/static/rest/services/nws_reference_maps/"
    "nws_reference_map/FeatureServer/1/query?"
    "where=cwa%3D%27LIX%27&outFields=cwa&returnGeometry=true&outSR=4326&f=geojson"
)
SOURCE_CONFIG = ROOT / "config" / "sources.json"
VENUE_CONFIG = ROOT / "config" / "venues.json"
MANUAL_EVENTS = ROOT / "data" / "manual-events.json"
BOUNDARY_CACHE = ROOT / "data" / "lix-boundary.geojson"
GEOCODE_CACHE = ROOT / "data" / "geocode-cache.json"
OUTPUT_EVENTS = ROOT / "web" / "data" / "events.json"
OUTPUT_META = ROOT / "web" / "data" / "build-metadata.json"

OUTDOOR_POSITIVE = (
    "outdoor", "outside", "open-air", "open air", "park", "parade", "race", "5k", "10k",
    "marathon", "street fest", "block party", "tailgate", "stadium",
    "waterfront", "lakefront", "beach", "pier", "marina", "boat", "fishing", "golf",
    "walk", "run", "bike", "cycling", "field"
)
INDOOR_NEGATIVE = (
    "museum", "theater", "theatre", "ballroom", "conference room", "auditorium",
    "indoor", "gallery", "library", "cinema", "arena", "convention center",
    "event center", "events center", "alario center"
)
SIGNIFICANT_POSITIVE = (
    "festival", "fest", "parade", "marathon", "half marathon", "10k", "5k", "race",
    "football", "soccer", "baseball", "softball", "golf", "regatta", "boat show",
    "air show", "fair", "concert series", "live after 5", "block party", "celebration",
    "tailgate", "market", "rodeo", "carnival"
)
LOW_VALUE = (
    "class", "workshop", "book club", "storytime", "story time", "happy hour",
    "trivia", "karaoke", "tour", "exhibit", "exhibition", "gallery opening",
    "wine tasting", "brunch", "dinner", "seminar", "lecture"
)
CATEGORY_RULES = [
    ("race_parade", ("parade", "marathon", "half marathon", "5k", "10k", "race", "run", "walk", "cycling", "bike")),
    ("sports", ("football", "soccer", "baseball", "softball", "golf", "rugby", "lacrosse", "track", "cross country")),
    ("coastal_marine", ("regatta", "boat", "fishing", "marina", "sailing", "paddle", "kayak", "waterfront")),
    ("festival", ("festival", "fest", "fair", "concert", "music", "celebration", "market", "carnival")),
]
MAJOR_HINTS = (
    "lsu football", "saints", "superdome", "tiger stadium", "marathon", "major festival",
    "national", "state fair", "air show", "fried chicken festival", "crescent city classic"
)

def now_local() -> datetime:
    override = os.environ.get("LIX_EVENTS_NOW")
    if override:
        dt = datetime.fromisoformat(override)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    return datetime.now(TZ)

def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    value = re.sub(r"<[^>]+>", " ", str(value))
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()

def slugify(value: str) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    return re.sub(r"[-\s]+", "-", value).strip("-")[:80]

def normalized_name(value: str) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"\b(opening night|day \d+|night \d+|presented by .+)$", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def fetch_text(
    url: str,
    timeout: int = 25,
    attempts: int = 2,
    extra_headers: dict[str, str] | None = None,
) -> str:
    last: Exception | None = None
    safe_url = quote(url, safe=":/?&=%#[]@!()*+,;-._~")
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"}
    if extra_headers:
        headers.update(extra_headers)
    for attempt in range(attempts):
        try:
            req = Request(safe_url, headers=headers)
            with urlopen(req, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except (HTTPError, URLError, TimeoutError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.0 + attempt)
    raise RuntimeError(f"fetch failed for {url}: {last}")

class EventHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self._in_jsonld = False
        self._jsonld_buf: list[str] = []
        self.jsonld_blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag.lower() == "a" and attr.get("href"):
            self.links.append(attr["href"] or "")
        if tag.lower() == "script" and (attr.get("type") or "").lower() == "application/ld+json":
            self._in_jsonld = True
            self._jsonld_buf = []

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._jsonld_buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_jsonld:
            self.jsonld_blocks.append("".join(self._jsonld_buf))
            self._in_jsonld = False
            self._jsonld_buf = []

def parse_html(text: str) -> EventHTMLParser:
    parser = EventHTMLParser()
    parser.feed(text)
    return parser

def iter_jsonld_events(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, list):
        for item in obj:
            yield from iter_jsonld_events(item)
    elif isinstance(obj, dict):
        type_value = obj.get("@type")
        types = type_value if isinstance(type_value, list) else [type_value]
        if any(str(t).lower().endswith("event") for t in types if t):
            yield obj
        for key in ("@graph", "itemListElement"):
            if key in obj:
                yield from iter_jsonld_events(obj[key])
        if "item" in obj:
            yield from iter_jsonld_events(obj["item"])

def extract_jsonld_events(text: str) -> list[dict[str, Any]]:
    parser = parse_html(text)
    events: list[dict[str, Any]] = []
    for block in parser.jsonld_blocks:
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        events.extend(iter_jsonld_events(parsed))
    return events

@dataclass
class SourceResult:
    key: str
    name: str
    success: bool
    discovered: int = 0
    accepted: int = 0
    detail_links: int = 0
    error: str | None = None




class HTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            text = clean_text(data)
            if text:
                self._cell.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(clean_text(" ".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

def parse_sidearm_text_football(text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    parser = HTMLTableParser()
    parser.feed(text)
    output: list[dict[str, Any]] = []
    year = int(source.get("season", now_local().year))
    team = clean_text(source.get("team_name") or source.get("name") or "College")
    venue = clean_text(source.get("home_venue"))
    city = clean_text(source.get("home_city"))
    state = clean_text(source.get("home_state") or "LA")

    for row in parser.rows:
        if len(row) < 5:
            continue
        date_cell, time_cell, at_cell, opponent_cell, location_cell = row[:5]
        if at_cell.lower() != "home":
            continue
        dm = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2})\b", date_cell, re.I)
        if not dm:
            continue
        event_date = date(year, MONTH_ABBR[dm.group(1).lower()], int(dm.group(2)))
        opponent = re.sub(r"\s*\([^)]*\)\s*$", "", clean_text(opponent_cell)).strip() or "Opponent TBA"
        clock_text = time_cell.replace("a.m.", "AM").replace("p.m.", "PM").replace("a.m", "AM").replace("p.m", "PM")
        clock = parse_clock(clock_text)
        start = (
            datetime(event_date.year, event_date.month, event_date.day, clock[0], clock[1], tzinfo=TZ).isoformat()
            if clock else event_date.isoformat()
        )
        output.append({
            "@type": "Event",
            "name": f"{team} Football vs. {opponent}",
            "startDate": start,
            "description": f"Outdoor home football game at {venue}.",
            "location": {
                "@type": "Place",
                "name": venue,
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": city,
                    "addressRegion": state,
                }
            },
            "url": source["url"],
        })
    return output

class SidearmScheduleParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.games: list[dict[str, Any]] = []
        self._depth = 0
        self._attrs: dict[str, str] | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}
        classes = attr.get("class", "")
        if self._depth == 0 and "sidearm-schedule-game" in classes:
            self._depth = 1
            self._attrs = attr
            self._parts = []
            return
        if self._depth:
            if tag.lower() not in self.VOID_TAGS:
                self._depth += 1
            if tag.lower() == "br":
                self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._depth:
            text = clean_text(data)
            if text:
                self._parts.append(text)
                self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if tag.lower() not in self.VOID_TAGS:
            self._depth -= 1
        if self._depth == 0:
            lines = [clean_text(x) for x in "".join(self._parts).splitlines() if clean_text(x)]
            self.games.append({"attrs": self._attrs or {}, "lines": lines})
            self._attrs = None
            self._parts = []

MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

def parse_sidearm_football(text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    parser = SidearmScheduleParser()
    parser.feed(text)
    output: list[dict[str, Any]] = []
    year = int(source.get("season", now_local().year))
    team = clean_text(source.get("team_name") or source.get("name") or "College")
    venue = clean_text(source.get("home_venue"))
    city = clean_text(source.get("home_city"))
    state = clean_text(source.get("home_state") or "LA")

    for block in parser.games:
        lines = block["lines"]
        joined = " ".join(lines)
        classes = block["attrs"].get("class", "").lower()
        is_home = "sidearm-schedule-home-game" in classes or any(line.lower().strip(".") == "vs" for line in lines)
        if not is_home:
            continue

        date_match = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2})\b", joined, re.I)
        if not date_match:
            continue
        month = MONTH_ABBR[date_match.group(1).lower()]
        day = int(date_match.group(2))
        event_date = date(year, month, day)

        opponent = ""
        for i, line in enumerate(lines):
            if line.lower().strip(".") == "vs":
                for candidate in lines[i + 1:i + 5]:
                    low = candidate.lower()
                    if low in {"tickets", "history", "watch", "listen", "live stats"}:
                        continue
                    if re.search(r"\b[A-Z]{2}\b", candidate) and "," in candidate:
                        continue
                    opponent = candidate
                    break
                if opponent:
                    break
        if not opponent:
            inline = re.search(r"\bvs\.?\s+(.+?)(?:\s{2,}|$)", joined, re.I)
            if inline:
                opponent = clean_text(inline.group(1))
        if not opponent:
            opponent = "Opponent TBA"

        clock = parse_clock(joined.replace("a.m.", "AM").replace("p.m.", "PM").replace("a.m", "AM").replace("p.m", "PM"))
        if clock:
            start = datetime(event_date.year, event_date.month, event_date.day, clock[0], clock[1], tzinfo=TZ).isoformat()
        else:
            start = event_date.isoformat()

        output.append({
            "@type": "Event",
            "name": f"{team} Football vs. {opponent}",
            "startDate": start,
            "description": f"Outdoor home football game at {venue}.",
            "location": {
                "@type": "Place",
                "name": venue,
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": city,
                    "addressRegion": state,
                }
            },
            "url": source["url"],
        })
    return output

class VisibleTextParser(HTMLParser):
    BLOCK_TAGS = {"p", "div", "section", "article", "h1", "h2", "h3", "li", "br", "dt", "dd"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.h1: list[str] = []
        self._h1_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "h1":
            self._h1_depth += 1
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "h1" and self._h1_depth:
            self._h1_depth -= 1
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        text = clean_text(data)
        if not text:
            return
        self.parts.append(text)
        if self._h1_depth:
            self.h1.append(text)

    def lines(self) -> list[str]:
        text = " ".join(self.parts)
        text = re.sub(r"\s*\n\s*", "\n", text)
        return [clean_text(x) for x in text.splitlines() if clean_text(x)]

MONTHS = {
    name.lower(): number for number, name in enumerate(
        ["", "January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"]
    ) if number
}

def parse_human_date_range(text: str) -> tuple[str | None, str | None]:
    text = clean_text(text).replace("–", "-").replace("—", "-")

    # September 18-20, 2026
    range_match = re.search(
        r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})\s*-\s*(\d{1,2}),\s*(20\d{2})\b",
        text, re.I
    )
    if range_match:
        month = MONTHS[range_match.group(1).lower()]
        start = date(int(range_match.group(4)), month, int(range_match.group(2)))
        end = date(int(range_match.group(4)), month, int(range_match.group(3)))
        return start.isoformat(), end.isoformat()

    # September 26, 2026
    single = re.search(
        r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2}),\s*(20\d{2})\b",
        text, re.I
    )
    if not single:
        return None, None
    month = MONTHS[single.group(1).lower()]
    d = date(int(single.group(3)), month, int(single.group(2)))
    return d.isoformat(), d.isoformat()

def parse_clock(text: str) -> tuple[int, int] | None:
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", text, re.I)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    if m.group(3).upper() == "PM" and hour != 12:
        hour += 12
    if m.group(3).upper() == "AM" and hour == 12:
        hour = 0
    return hour, minute

def parse_houma_event(text: str, detail_url: str) -> dict[str, Any] | None:
    parser = VisibleTextParser()
    parser.feed(text)
    lines = parser.lines()
    name = clean_text(" ".join(parser.h1))
    if not name:
        return None

    name_index = next((i for i, line in enumerate(lines) if normalized_name(line) == normalized_name(name)), 0)
    body = lines[name_index + 1:]

    start_date = end_date = None
    date_index = None
    for i, line in enumerate(body[:20]):
        start_date, end_date = parse_human_date_range(line)
        if start_date:
            date_index = i
            break
    if not start_date:
        return None

    # Prefer a clock shown in the DATE section.
    start_clock = None
    for line in body[(date_index or 0): (date_index or 0) + 15]:
        start_clock = parse_clock(line)
        if start_clock:
            break

    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=TZ)
    if start_clock:
        start_dt = start_dt.replace(hour=start_clock[0], minute=start_clock[1])
    end_dt = datetime.fromisoformat(end_date or start_date).replace(tzinfo=TZ)
    if end_date == start_date and start_clock:
        end_dt = start_dt

    location_index = next((i for i, line in enumerate(body) if line.upper() == "LOCATION" or line.upper().endswith(" LOCATION")), None)
    location_lines: list[str] = []
    if location_index is not None:
        for line in body[location_index + 1: location_index + 8]:
            upper = line.upper()
            if upper in {"PRICE", "INFO", "REGISTRATION"} or upper.endswith(" PRICE") or upper.endswith(" INFO") or line.lower().startswith("view all events"):
                break
            location_lines.append(line)

    venue = location_lines[0] if location_lines else ""
    address_lines = location_lines[1:] if len(location_lines) > 1 else []
    city = state = ""
    for line in address_lines:
        m = re.search(r"^(.+?),\s*(LA|MS)\b", line, re.I)
        if m:
            city = clean_text(m.group(1))
            state = m.group(2).upper()

    description_stop = location_index if location_index is not None else min(len(body), 35)
    description = " ".join(body[:description_stop])
    address = ", ".join(address_lines)

    return {
        "@type": "Event",
        "name": name,
        "startDate": start_dt.isoformat() if start_clock else start_date,
        "endDate": end_dt.isoformat() if start_clock else (end_date or start_date),
        "description": description,
        "location": {
            "@type": "Place",
            "name": venue,
            "address": {
                "@type": "PostalAddress",
                "streetAddress": address_lines[0] if address_lines else "",
                "addressLocality": city,
                "addressRegion": state,
                "postalCode": next((x for x in address_lines if re.fullmatch(r"\d{5}", x)), ""),
            }
        },
        "url": detail_url,
    }

def evvnt_event_to_schema(event: dict[str, Any], source: dict[str, Any]) -> dict[str, Any] | None:
    title = clean_text(event.get("title"))
    start = event.get("start_time") or event.get("start_date")
    if not title or not start:
        return None

    venue = event.get("venue") if isinstance(event.get("venue"), dict) else {}
    geoloc = event.get("_geoloc") if isinstance(event.get("_geoloc"), dict) else {}

    lat = venue.get("latitude")
    lon = venue.get("longitude")
    if lat is None:
        lat = geoloc.get("lat")
    if lon is None:
        lon = geoloc.get("lng")

    address = {
        "@type": "PostalAddress",
        "streetAddress": clean_text(venue.get("address_1") or venue.get("address")),
        "addressLocality": clean_text(venue.get("town") or venue.get("city")),
        "addressRegion": clean_text(venue.get("region") or venue.get("state")),
        "postalCode": clean_text(venue.get("postcode") or venue.get("postal_code")),
    }
    location: dict[str, Any] = {
        "@type": "Place",
        "name": clean_text(venue.get("name") or venue.get("title")),
        "address": address,
    }
    if lat is not None and lon is not None:
        location["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": lat,
            "longitude": lon,
        }

    source_url = clean_text(event.get("source_broadcast_url"))
    if not source_url:
        links = event.get("links") or event.get("original_links") or {}
        if isinstance(links, dict):
            for key in ("Website", "More Info", "Tickets"):
                value = links.get(key)
                if isinstance(value, dict):
                    value = value.get("url")
                if isinstance(value, str) and value.startswith("http"):
                    source_url = value
                    break
        elif isinstance(links, list):
            for item in links:
                if not isinstance(item, dict):
                    continue
                value = item.get("url")
                if isinstance(value, str) and value.startswith("http"):
                    source_url = value
                    break

    return {
        "@type": "Event",
        "name": title,
        "startDate": start,
        "endDate": event.get("end_time"),
        "description": clean_text(event.get("summary") or event.get("description")),
        "location": location,
        "url": source_url or source.get("calendar_url") or source.get("url"),
    }


def collect_evvnt_discovery(source: dict[str, Any]) -> list[dict[str, Any]]:
    publisher_id = source.get("publisher_id")
    if publisher_id in (None, ""):
        raise RuntimeError("Evvnt source missing publisher_id")

    hits = int(source.get("hits_per_page", 100))
    max_pages = int(source.get("max_pages", 5))
    api_base = source.get("api_base", "https://discovery.evvnt.com")
    endpoint = f"{api_base.rstrip('/')}/api/publisher/{publisher_id}/home_page_events"

    output: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page in range(max_pages):
        params = {
            "hitsPerPage": hits,
            "multipleEventInstances": "true",
            "page": page,
            "publisher_id": publisher_id,
        }
        if source.get("api_key"):
            params["api_key"] = source["api_key"]

        payload = json.loads(fetch_text(f"{endpoint}?{urlencode(params)}"))
        featured = payload.get("rawFeaturedEvents") or []
        events = payload.get("rawEvents") or []

        for event in [*featured, *events]:
            if not isinstance(event, dict):
                continue
            stable = str(
                event.get("objectID")
                or event.get("source_id")
                or f'{event.get("title", "")}|{event.get("start_time") or event.get("start_date") or ""}'
            )
            if stable in seen:
                continue
            seen.add(stable)
            normalized = evvnt_event_to_schema(event, source)
            if normalized:
                output.append(normalized)

        if len(events) < hits:
            break

    return output


CITYSPARK_DETAIL_RE = re.compile(
    r"https?://(?:www\.)?sunherald\.com/events/#/details/[^)\s]+/(\d+)/(\d{4}-\d{2}-\d{2}T\d{2})"
)

def parse_cityspark_widget_payload(text: str) -> dict[str, Any] | None:
    """Extract the JSON object passed to window.csCard() from CitySpark widget HTML."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # CitySpark's CDN sometimes serves the same response JSONP-wrapped,
        # even when no callback was requested. Decode the first JSON object.
        brace = text.find("{")
        if brace < 0:
            return None
        try:
            payload, _ = json.JSONDecoder().raw_decode(text[brace:])
        except json.JSONDecodeError:
            return None
    content = payload.get("Content")
    if not isinstance(content, str):
        return None
    marker = "window.csCard("
    pos = content.find(marker)
    if pos < 0:
        return None
    comma = content.find(",", pos + len(marker))
    if comma < 0:
        return None
    brace = content.find("{", comma)
    if brace < 0:
        return None
    try:
        card, _ = json.JSONDecoder().raw_decode(content[brace:])
    except json.JSONDecodeError:
        return None
    return card if isinstance(card, dict) else None

def cityspark_card_to_schema(
    card: dict[str, Any],
    occurrence: str,
    detail_url: str,
) -> dict[str, Any] | None:
    event = card.get("Event")
    if not isinstance(event, dict):
        return None
    name = clean_text(event.get("Name"))
    if not name:
        return None

    city_state = clean_text(event.get("CityState"))
    city, state = city_state, ""
    if "," in city_state:
        city, state = [clean_text(x) for x in city_state.rsplit(",", 1)]

    # CitySpark's widget payload labels local wall-clock values with Z. The
    # calendar route itself carries the intended local occurrence hour, so
    # build a timezone-aware local timestamp instead of interpreting that Z
    # as true UTC.
    occ_match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})T(\d{2})", occurrence)
    all_day = bool(event.get("AllDay")) or not bool(event.get("HasTime"))
    start_date: str
    if all_day:
        start_date = occ_match.group(1) if occ_match else occurrence[:10]
    else:
        base = event.get("DateStart") or ""
        minute_match = re.search(r"T\d{2}:(\d{2})", str(base))
        minute = int(minute_match.group(1)) if minute_match else 0
        if occ_match:
            d = date.fromisoformat(occ_match.group(1))
            start_date = datetime(
                d.year, d.month, d.day, int(occ_match.group(2)), minute, tzinfo=TZ
            ).isoformat()
        else:
            parsed = parse_dt(base)
            if not parsed:
                return None
            start_date = parsed.isoformat()

    end_date = None
    raw_end = event.get("DateEnd")
    if raw_end and not all_day:
        try:
            naive = datetime.fromisoformat(str(raw_end).replace("Z", ""))
            end_date = naive.replace(tzinfo=TZ).isoformat()
        except ValueError:
            end_date = None

    location: dict[str, Any] = {
        "@type": "Place",
        "name": clean_text(event.get("Venue")),
        "address": {
            "@type": "PostalAddress",
            "streetAddress": clean_text(event.get("Address")),
            "addressLocality": city,
            "addressRegion": state,
            "postalCode": clean_text(event.get("Zip")),
        },
    }
    try:
        lat = float(event.get("latitude"))
        lon = float(event.get("longitude"))
        location["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": lat,
            "longitude": lon,
        }
    except (TypeError, ValueError):
        pass

    return {
        "@type": "Event",
        "name": name,
        "startDate": start_date,
        "endDate": end_date,
        "description": clean_text(event.get("Description")),
        "location": location,
        "url": detail_url,
    }

def collect_cityspark_rendered(
    source: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """Discover Sun Herald CitySpark events, then hydrate via public widget JSON."""
    calendar_url = source.get("calendar_url") or source.get("url")
    portal = clean_text(source.get("portal") or "SunHerald")
    if not calendar_url:
        raise RuntimeError("CitySpark source missing calendar_url")

    start = now_local().date()
    render_headers = {
        "X-Respond-Timing": "mutation-idle",
        "X-Engine": "browser",
        "X-Timeout": "60",
    }
    renderer = str(source.get("renderer_base") or "https://r.jina.ai/").rstrip("/") + "/"

    targets = [
        renderer + "https://www.sunherald.com/events/",
        renderer
        + "https://www.sunherald.com/events/%23/show?start="
        + (start + timedelta(days=5)).isoformat(),
    ]

    occurrences: dict[tuple[str, str], str] = {}
    for target in targets:
        rendered = fetch_text(
            target,
            timeout=int(source.get("render_timeout", 75)),
            attempts=2,
            extra_headers=render_headers,
        )
        for match in CITYSPARK_DETAIL_RE.finditer(rendered):
            event_id, occurrence = match.group(1), match.group(2)
            occurrences[(event_id, occurrence)] = match.group(0)

    max_details = int(source.get("max_detail_pages", 100))
    output: list[dict[str, Any]] = []
    hydrated = 0
    for (event_id, occurrence), detail_url in list(occurrences.items())[:max_details]:
        widget_url = f"https://cdn-p.cityspark.com/wid/{portal}_{event_id}.jsx"
        try:
            widget_text = fetch_text(widget_url, timeout=20, attempts=2)
            c…10478 tokens truncated…t/landing-page canonical URL over the
                # detail page we actually fetched.
                event["url"] = detail_url
                if legacy.clean_text(event.get("name")).lower() in {
                    legacy.clean_text(x).lower() for x in source.get("reject_names", [])
                }:
                    continue
                raw.append(event)
        except Exception as exc:
            print(f"[source:{source.get('key')}] enhanced detail skipped {detail_url}: {exc}", file=sys.stderr)
    return raw, len(links)


def parse_lsu_football(text: str, source: dict):
    parser = VisibleTextParser()
    parser.feed(text)
    lines = [legacy.clean_text(x) for x in parser.text.splitlines() if legacy.clean_text(x)]
    rows = []
    season = int(source.get("season", legacy.now_local().year))
    date_re = re.compile(
        r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?\s*"
        r"(Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s*(\d{1,2})$",
        re.I,
    )

    for i, line in enumerate(lines):
        dm = date_re.match(line)
        if not dm:
            continue
        month = MONTHS[dm.group(1).lower().rstrip(".")]
        start = datetime(season, month, int(dm.group(2)), tzinfo=legacy.TZ)
        block_lines = lines[i + 1:i + 18]
        block = " ".join(block_lines)

        # A home game must explicitly resolve to Tiger Stadium / Baton Rouge.
        if not re.search(r"Tiger Stadium|Baton Rouge", block, re.I):
            continue

        opponent = ""
        for candidate in block_lines:
            om = re.match(r"^vs\.?\s*(?:#\d+\s*)?(.+?)$", candidate, re.I)
            if om:
                value = legacy.clean_text(om.group(1))
                if value and value not in {".", "-", "vs", "vs."} and not date_re.match(value):
                    opponent = value
                    break
        if not opponent:
            continue

        tm = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\s*CT\b", block, re.I)
        if tm:
            hour = int(tm.group(1)) % 12 + (12 if tm.group(3).upper() == "PM" else 0)
            start = start.replace(hour=hour, minute=int(tm.group(2) or 0))

        rows.append({
            "name": f"LSU Football vs {opponent}",
            "startDate": start.isoformat(),
            "location": {
                "name": "Tiger Stadium",
                "address": {"addressLocality": "Baton Rouge", "addressRegion": "LA"},
            },
            "description": "LSU home football game at outdoor Tiger Stadium.",
            "url": source["url"],
        })

    dedup = {}
    for row in rows:
        dedup[(row["name"].lower(), row["startDate"])] = row
    return list(dedup.values())

def parse_tangipahoa_fairs(text: str, source: dict):
    parser = VisibleTextParser()
    parser.feed(text)
    lines = [legacy.clean_text(x) for x in parser.text.splitlines() if legacy.clean_text(x)]
    raw = []
    for i, line in enumerate(lines):
        if not re.search(r"\b(fair|festival|airshow|rodeo|parade)\b", line, re.I):
            continue
        block = " ".join(lines[max(0, i-3): min(len(lines), i+12)])
        start, end = parse_date_range(block)
        if not start:
            continue
        city, state = infer_city_state(block)
        raw.append({
            "name": line,
            "startDate": start.date().isoformat(),
            "endDate": end.date().isoformat() if end else None,
            "location": {
                "name": "",
                "address": {"addressLocality": city, "addressRegion": state or "LA"},
            },
            "description": block + " Outdoor fair or festival.",
            "url": source["url"],
        })
    dedup = {}
    for r in raw:
        dedup[(r["name"].lower(), r["startDate"])] = r
    return list(dedup.values())



def parse_mardi_gras(text: str, source: dict):
    parser = VisibleTextParser()
    parser.feed(text)
    lines = [legacy.clean_text(x) for x in parser.text.splitlines() if legacy.clean_text(x)]
    raw = []
    current_date = None
    current_area = ""
    area_map = {
        "French Quarter": "New Orleans", "Uptown New Orleans": "New Orleans",
        "Marigny": "New Orleans", "Mid-City": "New Orleans", "New Orleans East": "New Orleans",
        "Westbank": "Gretna", "Metairie": "Metairie", "Kenner": "Kenner",
        "Slidell": "Slidell", "Pearl River": "Pearl River", "Mandeville": "Mandeville",
        "Madisonville": "Madisonville", "Covington": "Covington", "Abita Springs": "Abita Springs",
        "Bush": "Bush", "Folsom": "Folsom", "Chalmette": "Chalmette",
    }
    date_re = re.compile(
        r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2})\s+(\d{4})",
        re.I,
    )
    for line in lines:
        dm = date_re.search(line)
        if dm:
            current_date = datetime(
                int(dm.group(3)), MONTHS[dm.group(1).lower().rstrip(".")], int(dm.group(2)),
                tzinfo=legacy.TZ
            )
            current_area = ""
            continue
        if line in area_map:
            current_area = line
            continue
        if not current_date or not current_area:
            continue
        tm = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", line, re.I)
        if not tm:
            continue
        title = re.sub(r"\s+\d{1,2}(?::\d{2})?\s*(?:am|pm).*?$", "", line, flags=re.I)
        title = re.sub(r"\s+(?:view\s*map|more\s*info).*$", "", title, flags=re.I)
        title = legacy.clean_text(title)
        if len(title) < 3:
            continue
        hour = int(tm.group(1)) % 12 + (12 if tm.group(3).lower() == "pm" else 0)
        minute = int(tm.group(2) or 0)
        start = current_date.replace(hour=hour, minute=minute)
        city = area_map[current_area]
        raw.append({
            "name": title,
            "startDate": start.isoformat(),
            "location": {
                "name": current_area,
                "address": {"addressLocality": city, "addressRegion": "LA"},
            },
            "description": f"Outdoor Mardi Gras parade in {current_area}.",
            "url": source["url"],
        })
    dedup = {}
    for r in raw:
        dedup[(r["name"].lower(), r["startDate"])] = r
    return list(dedup.values())


def collect_source_v2(source: dict):
    collector = source.get("collector")
    result = legacy.SourceResult(key=source["key"], name=source["name"], success=False)
    try:
        if collector == "enhanced_listing":
            raw, link_count = collect_enhanced_listing(source)
            result.detail_links = link_count
        elif collector == "lsu_football":
            text = legacy.fetch_text(source["url"])
            raw = parse_lsu_football(text, source)
            result.detail_links = 0
        elif collector == "tangipahoa_fairs":
            text = legacy.fetch_text(source["url"])
            raw = parse_tangipahoa_fairs(text, source)
            result.detail_links = 0
        elif collector == "mardi_gras":
            text = legacy.fetch_text(source["url"])
            raw = parse_mardi_gras(text, source)
            result.detail_links = 0
        else:
            return legacy_collect_source(source)
        result.success = True
        result.discovered = len(raw)
        if source.get("zero_is_failure") and not raw:
            result.success = False
            result.error = "source returned zero events"
        return raw, result
    except Exception as exc:
        result.error = str(exc)
        return [], result


# Tighten source health without changing the downstream event model.
legacy.collect_source = collect_source_v2

if __name__ == "__main__":
    raise SystemExit(legacy.main())

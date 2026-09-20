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

def fetch_text(url: str, timeout: int = 25, attempts: int = 2) -> str:
    last: Exception | None = None
    safe_url = quote(url, safe=":/?&=%#[]@!            with urlopen(req, timeout=timeout) as response:
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

def collect_source(source: dict[str, Any]) -> tuple[list[dict[str, Any]], SourceResult]:
    key = source["key"]
    name = source["name"]
    result = SourceResult(key=key, name=name, success=False)
    raw: list[dict[str, Any]] = []
    try:
        listing_url = source["url"]
        listing_text = fetch_text(listing_url)
        raw.extend(extract_jsonld_events(listing_text))
        if source.get("collector") == "sidearm_football":
            raw.extend(parse_sidearm_football(listing_text, source))
        elif source.get("collector") == "sidearm_text_football":
            raw.extend(parse_sidearm_text_football(listing_text, source))

        if source.get("collector") in {"listing_jsonld", "listing_houma"}:
            parser = parse_html(listing_text)
            contains_any = source.get("href_contains_any")
            if not contains_any:
                contains_any = [source.get("href_contains", "/event/")]
            domain = urlparse(listing_url).netloc.lower().removeprefix("www.")
            links: list[str] = []
            seen: set[str] = set()
            for href in parser.links:
                absolute = urljoin(listing_url, href)
                parsed = urlparse(absolute)
                link_domain = parsed.netloc.lower().removeprefix("www.")
                if link_domain != domain or not any(token in parsed.path for token in contains_any):
                    continue
                canonical = absolute.split("#", 1)[0]
                if canonical in seen:
                    continue
                seen.add(canonical)
                links.append(canonical)
            result.detail_links = len(links)
            for detail_url in links[: int(source.get("max_detail_pages", 30))]:
                try:
                    detail_text = fetch_text(detail_url)
                    detail_events = extract_jsonld_events(detail_text)
                    if not detail_events and source.get("collector") == "listing_houma":
                        fallback = parse_houma_event(detail_text, detail_url)
                        if fallback:
                            detail_events = [fallback]
                    for event in detail_events:
                        event.setdefault("url", detail_url)
                        raw.append(event)
                except Exception as exc:
                    print(f"[source:{key}] detail skipped {detail_url}: {exc}", file=sys.stderr)

        result.success = True
        result.discovered = len(raw)
        return raw, result
    except Exception as exc:
        result.error = str(exc)
        return [], result

def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.fromisoformat(text).replace(tzinfo=TZ)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except ValueError:
        return None

def address_parts(location: Any) -> tuple[str, str, str, str, float | None, float | None]:
    venue = address = city = state = ""
    lat = lon = None
    if isinstance(location, list) and location:
        location = location[0]
    if isinstance(location, str):
        venue = clean_text(location)
        return venue, address, city, state, lat, lon
    if not isinstance(location, dict):
        return venue, address, city, state, lat, lon
    venue = clean_text(location.get("name"))
    addr = location.get("address")
    if isinstance(addr, str):
        address = clean_text(addr)
    elif isinstance(addr, dict):
        street = clean_text(addr.get("streetAddress"))
        city = clean_text(addr.get("addressLocality"))
        state = clean_text(addr.get("addressRegion"))
        postal = clean_text(addr.get("postalCode"))
        address = ", ".join(x for x in (street, city, state + (f" {postal}" if postal else "")) if x)
    geo = location.get("geo")
    if isinstance(geo, dict):
        try:
            lat = float(geo.get("latitude"))
            lon = float(geo.get("longitude"))
        except (TypeError, ValueError):
            lat = lon = None
    return venue, address, city, state, lat, lon

def venue_index() -> dict[str, dict[str, Any]]:
    venues = load_json(VENUE_CONFIG, [])
    idx: dict[str, dict[str, Any]] = {}
    for venue in venues:
        names = [venue.get("name", "")] + venue.get("aliases", [])
        for name in names:
            if name:
                idx[normalized_name(name)] = venue
    return idx

def resolve_known_venue(event: dict[str, Any], venues: dict[str, dict[str, Any]]) -> bool:
    for candidate in (event.get("venue"), event.get("address")):
        key = normalized_name(candidate or "")
        if not key:
            continue
        venue = venues.get(key)
        if venue:
            event["venue"] = event.get("venue") or venue["name"]
            event["address"] = event.get("address") or venue.get("address", "")
            event["city"] = event.get("city") or venue.get("city", "")
            event["state"] = event.get("state") or venue.get("state", "")
            if event.get("latitude") is None:
                event["latitude"] = venue["latitude"]
            if event.get("longitude") is None:
                event["longitude"] = venue["longitude"]
            event["location_confidence"] = max(float(event.get("location_confidence", 0)), 0.99)
            if venue.get("outdoor_status"):
                event["_venue_outdoor_status"] = venue["outdoor_status"]
            if venue.get("importance"):
                event["_venue_importance"] = venue["importance"]
            return True
    return False

def geocode(event: dict[str, Any], cache: dict[str, Any]) -> bool:
    query = event.get("address") or ", ".join(x for x in (event.get("venue"), event.get("city"), event.get("state")) if x)
    query = clean_text(query)
    if not query:
        return False
    key = query.lower()
    if key in cache:
        item = cache[key]
        if not item:
            return False
        event["latitude"] = item["latitude"]
        event["longitude"] = item["longitude"]
        event["location_confidence"] = 0.78
        return True
    params = urlencode({"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us"})
    try:
        text = fetch_text(f"https://nominatim.openstreetmap.org/search?{params}", attempts=1)
        rows = json.loads(text)
        if not rows:
            cache[key] = None
            return False
        event["latitude"] = float(rows[0]["lat"])
        event["longitude"] = float(rows[0]["lon"])
        event["location_confidence"] = 0.72
        cache[key] = {"latitude": event["latitude"], "longitude": event["longitude"], "display_name": rows[0].get("display_name")}
        time.sleep(1.05)
        return True
    except Exception as exc:
        print(f"[geocode] {query}: {exc}", file=sys.stderr)
        return False

def normalize_schema_event(obj: dict[str, Any], source: dict[str, Any]) -> dict[str, Any] | None:
    name = clean_text(obj.get("name") or obj.get("headline"))
    start = parse_dt(obj.get("startDate"))
    end = parse_dt(obj.get("endDate"))
    if not name or not start:
        return None
    venue, address, city, state, lat, lon = address_parts(obj.get("location"))
    description = clean_text(obj.get("description"))
    source_url = clean_text(obj.get("url")) or source["url"]
    if source_url.startswith("/"):
        source_url = urljoin(source["url"], source_url)
    return {
        "name": name,
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "all_day": bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(obj.get("startDate") or ""))),
        "latitude": lat,
        "longitude": lon,
        "venue": venue,
        "address": address,
        "city": city,
        "state": state,
        "description": description,
        "source_name": source["name"],
        "source_url": source_url,
        "_source_key": source["key"],
    }

def event_dates(start: datetime, end: datetime | None) -> list[str]:
    final = (end or start).date()
    current = start.date()
    dates: list[str] = []
    while current <= final and len(dates) < 31:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates

def in_window(event: dict[str, Any], window_start: date, window_end: date) -> bool:
    start = parse_dt(event.get("start"))
    end = parse_dt(event.get("end")) or start
    if not start:
        return False
    return start.date() <= window_end and end.date() >= window_start

def contains_term(text: str, term: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", text.lower()) is not None

CITY_CONTEXT = {
    "new orleans": ("Orleans Parish", "New Orleans Metro"),
    "metairie": ("Jefferson Parish", "New Orleans Metro"),
    "kenner": ("Jefferson Parish", "New Orleans Metro"),
    "jefferson": ("Jefferson Parish", "New Orleans Metro"),
    "gretna": ("Jefferson Parish", "New Orleans Metro"),
    "harvey": ("Jefferson Parish", "New Orleans Metro"),
    "marrero": ("Jefferson Parish", "New Orleans Metro"),
    "westwego": ("Jefferson Parish", "New Orleans Metro"),
    "baton rouge": ("East Baton Rouge Parish", "Baton Rouge Metro"),
    "zachary": ("East Baton Rouge Parish", "Baton Rouge Metro"),
    "baker": ("East Baton Rouge Parish", "Baton Rouge Metro"),
    "mandeville": ("St. Tammany Parish", "Northshore"),
    "covington": ("St. Tammany Parish", "Northshore"),
    "slidell": ("St. Tammany Parish", "Northshore"),
    "madisonville": ("St. Tammany Parish", "Northshore"),
    "hammond": ("Tangipahoa Parish", "Northshore"),
    "ponchatoula": ("Tangipahoa Parish", "Northshore"),
    "amite": ("Tangipahoa Parish", "Northshore"),
    "houma": ("Terrebonne Parish", "Bayou Parishes"),
    "thibodaux": ("Lafourche Parish", "Bayou Parishes"),
    "cut off": ("Lafourche Parish", "Bayou Parishes"),
    "galliano": ("Lafourche Parish", "Bayou Parishes"),
    "raceland": ("Lafourche Parish", "Bayou Parishes"),
    "laplace": ("St. John the Baptist Parish", "River Parishes"),
    "reserve": ("St. John the Baptist Parish", "River Parishes"),
    "destrehan": ("St. Charles Parish", "River Parishes"),
    "luling": ("St. Charles Parish", "River Parishes"),
    "gramercy": ("St. James Parish", "River Parishes"),
    "gulfport": ("Harrison County", "Mississippi Coast"),
    "biloxi": ("Harrison County", "Mississippi Coast"),
    "long beach": ("Harrison County", "Mississippi Coast"),
    "pass christian": ("Harrison County", "Mississippi Coast"),
    "bay st. louis": ("Hancock County", "Mississippi Coast"),
    "bay saint louis": ("Hancock County", "Mississippi Coast"),
    "waveland": ("Hancock County", "Mississippi Coast"),
    "picayune": ("Pearl River County", "Southwest Mississippi"),
}

def derive_operational_context(event: dict[str, Any]) -> None:
    city = clean_text(event.get("city")).lower()
    parish_county, area = CITY_CONTEXT.get(city, ("", ""))
    if not area:
        try:
            lat, lon = float(event["latitude"]), float(event["longitude"])
            if lat < 30.15 and lon > -90.45:
                area = "New Orleans Metro"
            elif lat >= 30.25 and lon < -90.85:
                area = "Baton Rouge Metro"
            elif lat >= 30.2 and -90.85 <= lon <= -89.65:
                area = "Northshore"
            elif lat < 30.2 and lon <= -90.45:
                area = "Bayou Parishes"
            elif event.get("state") == "MS":
                area = "Mississippi Coast"
        except (KeyError, TypeError, ValueError):
            pass
    event["parish_county"] = parish_county
    event["idss_area"] = area

def classify_event(event: dict[str, Any]) -> None:
    text = " ".join(clean_text(event.get(k)) for k in ("name", "description", "venue", "address")).lower()
    name_text = clean_text(event.get("name")).lower()
    category = "other"
    if str(event.get("_source_key", "")).endswith("_football"):
        category = "sports"
    elif any(contains_term(name_text, word) for word in ("festival", "fest", "fair", "carnival")):
        category = "festival"
    else:
        for label, words in CATEGORY_RULES:
            if any(contains_term(text, word) for word in words):
                category = label
                break
    event["category"] = category

    venue_status = event.pop("_venue_outdoor_status", None)
    has_outdoor = any(contains_term(text, word) for word in OUTDOOR_POSITIVE)
    has_indoor = any(contains_term(text, word) for word in INDOOR_NEGATIVE)
    if venue_status:
        outdoor = venue_status
        confidence = 0.99
    elif has_outdoor and has_indoor:
        outdoor, confidence = "partial", 0.72
    elif has_outdoor:
        outdoor, confidence = "outdoor", 0.78
    else:
        outdoor, confidence = "unknown", 0.35
    event["outdoor_status"] = outdoor
    event["outdoor_confidence"] = confidence

    venue_importance = event.pop("_venue_importance", None)
    if venue_importance:
        importance = venue_importance
    elif any(contains_term(text, hint) for hint in MAJOR_HINTS):
        importance = "major"
    else:
        importance = "moderate"
    event["importance"] = importance

def is_idss_relevant(event: dict[str, Any]) -> bool:
    if event.get("outdoor_status") not in {"outdoor", "partial"}:
        return False
    text = " ".join(clean_text(event.get(k)) for k in ("name", "description", "venue")).lower()
    if any(contains_term(text, term) for term in LOW_VALUE) and not any(contains_term(text, term) for term in SIGNIFICANT_POSITIVE):
        return False
    if event.get("importance") == "major":
        return True
    return any(contains_term(text, term) for term in SIGNIFICANT_POSITIVE)

def load_boundary() -> dict[str, Any]:
    try:
        data = json.loads(fetch_text(BOUNDARY_URL))
        if data.get("features"):
            write_json(BOUNDARY_CACHE, data)
            return data
    except Exception as exc:
        print(f"[boundary] live fetch failed: {exc}", file=sys.stderr)
    cached = load_json(BOUNDARY_CACHE, None)
    if cached and cached.get("features"):
        return cached
    raise RuntimeError("LIX CWA boundary unavailable and no cached boundary exists")

def point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi):
            inside = not inside
        j = i
    return inside

def point_in_polygon(x: float, y: float, polygon: list[list[list[float]]]) -> bool:
    if not polygon or not point_in_ring(x, y, polygon[0]):
        return False
    return not any(point_in_ring(x, y, hole) for hole in polygon[1:])

def point_in_boundary(lon: float, lat: float, boundary: dict[str, Any]) -> bool:
    for feature in boundary.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") == "Polygon" and point_in_polygon(lon, lat, geom.get("coordinates", [])):
            return True
        if geom.get("type") == "MultiPolygon":
            if any(point_in_polygon(lon, lat, poly) for poly in geom.get("coordinates", [])):
                return True
    return False

def haversine_miles(a: dict[str, Any], b: dict[str, Any]) -> float:
    try:
        lat1, lon1 = math.radians(float(a["latitude"])), math.radians(float(a["longitude"]))
        lat2, lon2 = math.radians(float(b["latitude"])), math.radians(float(b["longitude"]))
    except (KeyError, TypeError, ValueError):
        return 999.0
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(min(1.0, math.sqrt(h)))

def is_duplicate(candidate: dict[str, Any], existing: dict[str, Any]) -> bool:
    if not set(candidate.get("dates", [])) & set(existing.get("dates", [])):
        return False
    similarity = SequenceMatcher(None, normalized_name(candidate["name"]), normalized_name(existing["name"])).ratio()
    if similarity < 0.72:
        return False
    return haversine_miles(candidate, existing) <= 1.5

def finalize(event: dict[str, Any]) -> dict[str, Any]:
    start = parse_dt(event.get("start"))
    end = parse_dt(event.get("end"))
    assert start is not None
    event["dates"] = event_dates(start, end)
    stable = f'{normalized_name(event["name"])}|{event["dates"][0]}|{round(float(event["latitude"]), 3)}|{round(float(event["longitude"]), 3)}'
    event["id"] = f'{slugify(event["name"])}-{event["dates"][0]}-{hashlib.sha1(stable.encode()).hexdigest()[:7]}'
    event.setdefault("weather_exposure_notes", "Outdoor or partially outdoor event retained for weather-sensitive operational awareness.")
    derive_operational_context(event)
    event.setdefault("origin", "automated")
    event.pop("description", None)
    event.pop("_source_key", None)
    ordered = {
        "id": event["id"], "name": event["name"], "dates": event["dates"], "start": event.get("start"),
        "end": event.get("end"), "all_day": bool(event.get("all_day", False)),
        "latitude": round(float(event["latitude"]), 6), "longitude": round(float(event["longitude"]), 6),
        "venue": event.get("venue") or "Location not listed", "address": event.get("address") or "",
        "city": event.get("city") or "", "state": event.get("state") or "",
        "parish_county": event.get("parish_county") or "", "idss_area": event.get("idss_area") or "",
        "category": event.get("category") or "other", "outdoor_status": event.get("outdoor_status") or "unknown",
        "origin": event.get("origin") or "automated",
        "importance": event.get("importance") or "moderate",
        "location_confidence": round(float(event.get("location_confidence", 0.5)), 2),
        "outdoor_confidence": round(float(event.get("outdoor_confidence", 0.5)), 2),
        "weather_exposure_notes": event.get("weather_exposure_notes") or "",
        "source_name": event.get("source_name") or "", "source_url": event.get("source_url") or "",
    }
    return ordered

def manual_in_window(window_start: date, window_end: date, boundary: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for event in load_json(MANUAL_EVENTS, []):
        if not in_window(event, window_start, window_end):
            continue
        try:
            if not point_in_boundary(float(event["longitude"]), float(event["latitude"]), boundary):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        output.append(event)
    return output

def main() -> int:
    now = now_local()
    window_start = now.date()
    window_end = window_start + timedelta(days=7)
    config = load_json(SOURCE_CONFIG, {"sources": []})
    venues = venue_index()
    geocode_cache = load_json(GEOCODE_CACHE, {})
    boundary = load_boundary()

    results: list[SourceResult] = []
    accepted_auto: list[dict[str, Any]] = []

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue
        raw_events, status = collect_source(source)
        for raw in raw_events:
            event = normalize_schema_event(raw, source)
            if not event or not in_window(event, window_start, window_end):
                continue

            if event.get("latitude") is not None and event.get("longitude") is not None:
                event["location_confidence"] = 0.96

            # Trusted venue records enrich outdoor status/importance even when
            # the source already supplies accurate coordinates.
            resolve_known_venue(event, venues)

            if event.get("latitude") is None and config.get("geocoding", {}).get("enabled", True):
                geocode(event, geocode_cache)

            if event.get("latitude") is None or event.get("longitude") is None:
                continue
            if not point_in_boundary(float(event["longitude"]), float(event["latitude"]), boundary):
                continue

            classify_event(event)
            if not is_idss_relevant(event):
                continue

            accepted_auto.append(finalize(event))
            status.accepted += 1
        results.append(status)
        print(f'[source:{status.key}] success={status.success} detail_links={status.detail_links} discovered={status.discovered} accepted={status.accepted} error={status.error or "-"}')

    write_json(GEOCODE_CACHE, geocode_cache)

    if results and not any(r.success for r in results):
        raise RuntimeError("All enabled automated sources failed; preserving last-known-good published dataset")

    # Automated records are authoritative when available. Manual records are
    # fallback/override safety-net entries and are retired automatically when
    # the same event is collected successfully.
    merged: list[dict[str, Any]] = []
    for event in sorted(accepted_auto, key=lambda e: (e["dates"][0], e["name"].lower())):
        if any(is_duplicate(event, current) for current in merged):
            continue
        merged.append(event)

    for event in manual_in_window(window_start, window_end, boundary):
        manual = dict(event)
        manual["origin"] = "manual"
        derive_operational_context(manual)
        if any(is_duplicate(manual, current) for current in merged):
            continue
        merged.append(manual)

    merged.sort(key=lambda e: (e["dates"][0] if e.get("dates") else "9999-99-99", e.get("start") or "", e["name"].lower()))

    # Protect against a parser collapse that still returns successful HTTP
    # responses. A severe automated-yield drop preserves the last-good data.
    previous_meta = load_json(OUTPUT_META, {})
    previous_auto = int(previous_meta.get("automated_candidate_count") or 0)
    if previous_auto >= 3 and len(accepted_auto) < max(1, math.ceil(previous_auto * 0.4)):
        raise RuntimeError(
            f"Automated candidate yield collapsed from {previous_auto} to {len(accepted_auto)}; "
            "preserving last-known-good published dataset"
        )

    write_json(OUTPUT_EVENTS, merged)
    meta = {
        "generated_at": now.isoformat(timespec="seconds"),
        "event_count": len(merged),
        "manual_event_count": sum(1 for e in merged if e.get("origin") == "manual"),
        "automated_event_count": sum(1 for e in merged if e.get("origin") == "automated"),
        "automated_candidate_count": len(accepted_auto),
        "collection_window_start": window_start.isoformat(),
        "collection_window_end": window_end.isoformat(),
        "timezone": "America/Chicago",
        "boundary_source": "NOAA/NWS reference map FeatureServer",
        "pipeline_state": "automated-multi-source-v1",
        "sources": [
            {
                "key": r.key, "name": r.name, "success": r.success,
                "health": (
                    "failed" if not r.success else
                    "degraded" if r.discovered == 0 else
                    "healthy"
                ),
                "detail_links": r.detail_links, "discovered": r.discovered,
                "accepted": r.accepted, "error": r.error,
            }
            for r in results
        ],
        "source_health": {
            "healthy": sum(1 for r in results if r.success and r.discovered > 0),
            "degraded": sum(1 for r in results if r.success and r.discovered == 0),
            "failed": sum(1 for r in results if not r.success),
            "total": len(results),
        },
        "notes": "Automated source collection is merged with a curated safety-net file. Unknown indoor/outdoor events and points outside the LIX CWA are excluded.",
    }
    write_json(OUTPUT_META, meta)

    print(f"[publish] {len(merged)} events for {window_start} through {window_end}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
()*+,;-._~")
    for attempt in range(attempts):
        try:
            req = Request(safe_url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"})
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

def collect_source(source: dict[str, Any]) -> tuple[list[dict[str, Any]], SourceResult]:
    key = source["key"]
    name = source["name"]
    result = SourceResult(key=key, name=name, success=False)
    raw: list[dict[str, Any]] = []
    try:
        listing_url = source["url"]
        listing_text = fetch_text(listing_url)
        raw.extend(extract_jsonld_events(listing_text))
        if source.get("collector") == "sidearm_football":
            raw.extend(parse_sidearm_football(listing_text, source))
        elif source.get("collector") == "sidearm_text_football":
            raw.extend(parse_sidearm_text_football(listing_text, source))

        if source.get("collector") in {"listing_jsonld", "listing_houma"}:
            parser = parse_html(listing_text)
            contains_any = source.get("href_contains_any")
            if not contains_any:
                contains_any = [source.get("href_contains", "/event/")]
            domain = urlparse(listing_url).netloc.lower().removeprefix("www.")
            links: list[str] = []
            seen: set[str] = set()
            for href in parser.links:
                absolute = urljoin(listing_url, href)
                parsed = urlparse(absolute)
                link_domain = parsed.netloc.lower().removeprefix("www.")
                if link_domain != domain or not any(token in parsed.path for token in contains_any):
                    continue
                canonical = absolute.split("#", 1)[0]
                if canonical in seen:
                    continue
                seen.add(canonical)
                links.append(canonical)
            result.detail_links = len(links)
            for detail_url in links[: int(source.get("max_detail_pages", 30))]:
                try:
                    detail_text = fetch_text(detail_url)
                    detail_events = extract_jsonld_events(detail_text)
                    if not detail_events and source.get("collector") == "listing_houma":
                        fallback = parse_houma_event(detail_text, detail_url)
                        if fallback:
                            detail_events = [fallback]
                    for event in detail_events:
                        event.setdefault("url", detail_url)
                        raw.append(event)
                except Exception as exc:
                    print(f"[source:{key}] detail skipped {detail_url}: {exc}", file=sys.stderr)

        result.success = True
        result.discovered = len(raw)
        return raw, result
    except Exception as exc:
        result.error = str(exc)
        return [], result

def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.fromisoformat(text).replace(tzinfo=TZ)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except ValueError:
        return None

def address_parts(location: Any) -> tuple[str, str, str, str, float | None, float | None]:
    venue = address = city = state = ""
    lat = lon = None
    if isinstance(location, list) and location:
        location = location[0]
    if isinstance(location, str):
        venue = clean_text(location)
        return venue, address, city, state, lat, lon
    if not isinstance(location, dict):
        return venue, address, city, state, lat, lon
    venue = clean_text(location.get("name"))
    addr = location.get("address")
    if isinstance(addr, str):
        address = clean_text(addr)
    elif isinstance(addr, dict):
        street = clean_text(addr.get("streetAddress"))
        city = clean_text(addr.get("addressLocality"))
        state = clean_text(addr.get("addressRegion"))
        postal = clean_text(addr.get("postalCode"))
        address = ", ".join(x for x in (street, city, state + (f" {postal}" if postal else "")) if x)
    geo = location.get("geo")
    if isinstance(geo, dict):
        try:
            lat = float(geo.get("latitude"))
            lon = float(geo.get("longitude"))
        except (TypeError, ValueError):
            lat = lon = None
    return venue, address, city, state, lat, lon

def venue_index() -> dict[str, dict[str, Any]]:
    venues = load_json(VENUE_CONFIG, [])
    idx: dict[str, dict[str, Any]] = {}
    for venue in venues:
        names = [venue.get("name", "")] + venue.get("aliases", [])
        for name in names:
            if name:
                idx[normalized_name(name)] = venue
    return idx

def resolve_known_venue(event: dict[str, Any], venues: dict[str, dict[str, Any]]) -> bool:
    for candidate in (event.get("venue"), event.get("address")):
        key = normalized_name(candidate or "")
        if not key:
            continue
        venue = venues.get(key)
        if venue:
            event["venue"] = event.get("venue") or venue["name"]
            event["address"] = event.get("address") or venue.get("address", "")
            event["city"] = event.get("city") or venue.get("city", "")
            event["state"] = event.get("state") or venue.get("state", "")
            if event.get("latitude") is None:
                event["latitude"] = venue["latitude"]
            if event.get("longitude") is None:
                event["longitude"] = venue["longitude"]
            event["location_confidence"] = max(float(event.get("location_confidence", 0)), 0.99)
            if venue.get("outdoor_status"):
                event["_venue_outdoor_status"] = venue["outdoor_status"]
            if venue.get("importance"):
                event["_venue_importance"] = venue["importance"]
            return True
    return False

def geocode(event: dict[str, Any], cache: dict[str, Any]) -> bool:
    query = event.get("address") or ", ".join(x for x in (event.get("venue"), event.get("city"), event.get("state")) if x)
    query = clean_text(query)
    if not query:
        return False
    key = query.lower()
    if key in cache:
        item = cache[key]
        if not item:
            return False
        event["latitude"] = item["latitude"]
        event["longitude"] = item["longitude"]
        event["location_confidence"] = 0.78
        return True
    params = urlencode({"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us"})
    try:
        text = fetch_text(f"https://nominatim.openstreetmap.org/search?{params}", attempts=1)
        rows = json.loads(text)
        if not rows:
            cache[key] = None
            return False
        event["latitude"] = float(rows[0]["lat"])
        event["longitude"] = float(rows[0]["lon"])
        event["location_confidence"] = 0.72
        cache[key] = {"latitude": event["latitude"], "longitude": event["longitude"], "display_name": rows[0].get("display_name")}
        time.sleep(1.05)
        return True
    except Exception as exc:
        print(f"[geocode] {query}: {exc}", file=sys.stderr)
        return False

def normalize_schema_event(obj: dict[str, Any], source: dict[str, Any]) -> dict[str, Any] | None:
    name = clean_text(obj.get("name") or obj.get("headline"))
    start = parse_dt(obj.get("startDate"))
    end = parse_dt(obj.get("endDate"))
    if not name or not start:
        return None
    venue, address, city, state, lat, lon = address_parts(obj.get("location"))
    description = clean_text(obj.get("description"))
    source_url = clean_text(obj.get("url")) or source["url"]
    if source_url.startswith("/"):
        source_url = urljoin(source["url"], source_url)
    return {
        "name": name,
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "all_day": bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(obj.get("startDate") or ""))),
        "latitude": lat,
        "longitude": lon,
        "venue": venue,
        "address": address,
        "city": city,
        "state": state,
        "description": description,
        "source_name": source["name"],
        "source_url": source_url,
        "_source_key": source["key"],
    }

def event_dates(start: datetime, end: datetime | None) -> list[str]:
    final = (end or start).date()
    current = start.date()
    dates: list[str] = []
    while current <= final and len(dates) < 31:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates

def in_window(event: dict[str, Any], window_start: date, window_end: date) -> bool:
    start = parse_dt(event.get("start"))
    end = parse_dt(event.get("end")) or start
    if not start:
        return False
    return start.date() <= window_end and end.date() >= window_start

def contains_term(text: str, term: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", text.lower()) is not None

CITY_CONTEXT = {
    "new orleans": ("Orleans Parish", "New Orleans Metro"),
    "metairie": ("Jefferson Parish", "New Orleans Metro"),
    "kenner": ("Jefferson Parish", "New Orleans Metro"),
    "jefferson": ("Jefferson Parish", "New Orleans Metro"),
    "gretna": ("Jefferson Parish", "New Orleans Metro"),
    "harvey": ("Jefferson Parish", "New Orleans Metro"),
    "marrero": ("Jefferson Parish", "New Orleans Metro"),
    "westwego": ("Jefferson Parish", "New Orleans Metro"),
    "baton rouge": ("East Baton Rouge Parish", "Baton Rouge Metro"),
    "zachary": ("East Baton Rouge Parish", "Baton Rouge Metro"),
    "baker": ("East Baton Rouge Parish", "Baton Rouge Metro"),
    "mandeville": ("St. Tammany Parish", "Northshore"),
    "covington": ("St. Tammany Parish", "Northshore"),
    "slidell": ("St. Tammany Parish", "Northshore"),
    "madisonville": ("St. Tammany Parish", "Northshore"),
    "hammond": ("Tangipahoa Parish", "Northshore"),
    "ponchatoula": ("Tangipahoa Parish", "Northshore"),
    "amite": ("Tangipahoa Parish", "Northshore"),
    "houma": ("Terrebonne Parish", "Bayou Parishes"),
    "thibodaux": ("Lafourche Parish", "Bayou Parishes"),
    "cut off": ("Lafourche Parish", "Bayou Parishes"),
    "galliano": ("Lafourche Parish", "Bayou Parishes"),
    "raceland": ("Lafourche Parish", "Bayou Parishes"),
    "laplace": ("St. John the Baptist Parish", "River Parishes"),
    "reserve": ("St. John the Baptist Parish", "River Parishes"),
    "destrehan": ("St. Charles Parish", "River Parishes"),
    "luling": ("St. Charles Parish", "River Parishes"),
    "gramercy": ("St. James Parish", "River Parishes"),
    "gulfport": ("Harrison County", "Mississippi Coast"),
    "biloxi": ("Harrison County", "Mississippi Coast"),
    "long beach": ("Harrison County", "Mississippi Coast"),
    "pass christian": ("Harrison County", "Mississippi Coast"),
    "bay st. louis": ("Hancock County", "Mississippi Coast"),
    "bay saint louis": ("Hancock County", "Mississippi Coast"),
    "waveland": ("Hancock County", "Mississippi Coast"),
    "picayune": ("Pearl River County", "Southwest Mississippi"),
}

def derive_operational_context(event: dict[str, Any]) -> None:
    city = clean_text(event.get("city")).lower()
    parish_county, area = CITY_CONTEXT.get(city, ("", ""))
    if not area:
        try:
            lat, lon = float(event["latitude"]), float(event["longitude"])
            if lat < 30.15 and lon > -90.45:
                area = "New Orleans Metro"
            elif lat >= 30.25 and lon < -90.85:
                area = "Baton Rouge Metro"
            elif lat >= 30.2 and -90.85 <= lon <= -89.65:
                area = "Northshore"
            elif lat < 30.2 and lon <= -90.45:
                area = "Bayou Parishes"
            elif event.get("state") == "MS":
                area = "Mississippi Coast"
        except (KeyError, TypeError, ValueError):
            pass
    event["parish_county"] = parish_county
    event["idss_area"] = area

def classify_event(event: dict[str, Any]) -> None:
    text = " ".join(clean_text(event.get(k)) for k in ("name", "description", "venue", "address")).lower()
    name_text = clean_text(event.get("name")).lower()
    category = "other"
    if str(event.get("_source_key", "")).endswith("_football"):
        category = "sports"
    elif any(contains_term(name_text, word) for word in ("festival", "fest", "fair", "carnival")):
        category = "festival"
    else:
        for label, words in CATEGORY_RULES:
            if any(contains_term(text, word) for word in words):
                category = label
                break
    event["category"] = category

    venue_status = event.pop("_venue_outdoor_status", None)
    has_outdoor = any(contains_term(text, word) for word in OUTDOOR_POSITIVE)
    has_indoor = any(contains_term(text, word) for word in INDOOR_NEGATIVE)
    if venue_status:
        outdoor = venue_status
        confidence = 0.99
    elif has_outdoor and has_indoor:
        outdoor, confidence = "partial", 0.72
    elif has_outdoor:
        outdoor, confidence = "outdoor", 0.78
    else:
        outdoor, confidence = "unknown", 0.35
    event["outdoor_status"] = outdoor
    event["outdoor_confidence"] = confidence

    venue_importance = event.pop("_venue_importance", None)
    if venue_importance:
        importance = venue_importance
    elif any(contains_term(text, hint) for hint in MAJOR_HINTS):
        importance = "major"
    else:
        importance = "moderate"
    event["importance"] = importance

def is_idss_relevant(event: dict[str, Any]) -> bool:
    if event.get("outdoor_status") not in {"outdoor", "partial"}:
        return False
    text = " ".join(clean_text(event.get(k)) for k in ("name", "description", "venue")).lower()
    if any(contains_term(text, term) for term in LOW_VALUE) and not any(contains_term(text, term) for term in SIGNIFICANT_POSITIVE):
        return False
    if event.get("importance") == "major":
        return True
    return any(contains_term(text, term) for term in SIGNIFICANT_POSITIVE)

def load_boundary() -> dict[str, Any]:
    try:
        data = json.loads(fetch_text(BOUNDARY_URL))
        if data.get("features"):
            write_json(BOUNDARY_CACHE, data)
            return data
    except Exception as exc:
        print(f"[boundary] live fetch failed: {exc}", file=sys.stderr)
    cached = load_json(BOUNDARY_CACHE, None)
    if cached and cached.get("features"):
        return cached
    raise RuntimeError("LIX CWA boundary unavailable and no cached boundary exists")

def point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi):
            inside = not inside
        j = i
    return inside

def point_in_polygon(x: float, y: float, polygon: list[list[list[float]]]) -> bool:
    if not polygon or not point_in_ring(x, y, polygon[0]):
        return False
    return not any(point_in_ring(x, y, hole) for hole in polygon[1:])

def point_in_boundary(lon: float, lat: float, boundary: dict[str, Any]) -> bool:
    for feature in boundary.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") == "Polygon" and point_in_polygon(lon, lat, geom.get("coordinates", [])):
            return True
        if geom.get("type") == "MultiPolygon":
            if any(point_in_polygon(lon, lat, poly) for poly in geom.get("coordinates", [])):
                return True
    return False

def haversine_miles(a: dict[str, Any], b: dict[str, Any]) -> float:
    try:
        lat1, lon1 = math.radians(float(a["latitude"])), math.radians(float(a["longitude"]))
        lat2, lon2 = math.radians(float(b["latitude"])), math.radians(float(b["longitude"]))
    except (KeyError, TypeError, ValueError):
        return 999.0
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(min(1.0, math.sqrt(h)))

def is_duplicate(candidate: dict[str, Any], existing: dict[str, Any]) -> bool:
    if not set(candidate.get("dates", [])) & set(existing.get("dates", [])):
        return False
    similarity = SequenceMatcher(None, normalized_name(candidate["name"]), normalized_name(existing["name"])).ratio()
    if similarity < 0.72:
        return False
    return haversine_miles(candidate, existing) <= 1.5

def finalize(event: dict[str, Any]) -> dict[str, Any]:
    start = parse_dt(event.get("start"))
    end = parse_dt(event.get("end"))
    assert start is not None
    event["dates"] = event_dates(start, end)
    stable = f'{normalized_name(event["name"])}|{event["dates"][0]}|{round(float(event["latitude"]), 3)}|{round(float(event["longitude"]), 3)}'
    event["id"] = f'{slugify(event["name"])}-{event["dates"][0]}-{hashlib.sha1(stable.encode()).hexdigest()[:7]}'
    event.setdefault("weather_exposure_notes", "Outdoor or partially outdoor event retained for weather-sensitive operational awareness.")
    derive_operational_context(event)
    event.setdefault("origin", "automated")
    event.pop("description", None)
    event.pop("_source_key", None)
    ordered = {
        "id": event["id"], "name": event["name"], "dates": event["dates"], "start": event.get("start"),
        "end": event.get("end"), "all_day": bool(event.get("all_day", False)),
        "latitude": round(float(event["latitude"]), 6), "longitude": round(float(event["longitude"]), 6),
        "venue": event.get("venue") or "Location not listed", "address": event.get("address") or "",
        "city": event.get("city") or "", "state": event.get("state") or "",
        "parish_county": event.get("parish_county") or "", "idss_area": event.get("idss_area") or "",
        "category": event.get("category") or "other", "outdoor_status": event.get("outdoor_status") or "unknown",
        "origin": event.get("origin") or "automated",
        "importance": event.get("importance") or "moderate",
        "location_confidence": round(float(event.get("location_confidence", 0.5)), 2),
        "outdoor_confidence": round(float(event.get("outdoor_confidence", 0.5)), 2),
        "weather_exposure_notes": event.get("weather_exposure_notes") or "",
        "source_name": event.get("source_name") or "", "source_url": event.get("source_url") or "",
    }
    return ordered

def manual_in_window(window_start: date, window_end: date, boundary: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for event in load_json(MANUAL_EVENTS, []):
        if not in_window(event, window_start, window_end):
            continue
        try:
            if not point_in_boundary(float(event["longitude"]), float(event["latitude"]), boundary):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        output.append(event)
    return output

def main() -> int:
    now = now_local()
    window_start = now.date()
    window_end = window_start + timedelta(days=7)
    config = load_json(SOURCE_CONFIG, {"sources": []})
    venues = venue_index()
    geocode_cache = load_json(GEOCODE_CACHE, {})
    boundary = load_boundary()

    results: list[SourceResult] = []
    accepted_auto: list[dict[str, Any]] = []

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue
        raw_events, status = collect_source(source)
        for raw in raw_events:
            event = normalize_schema_event(raw, source)
            if not event or not in_window(event, window_start, window_end):
                continue

            if event.get("latitude") is not None and event.get("longitude") is not None:
                event["location_confidence"] = 0.96

            # Trusted venue records enrich outdoor status/importance even when
            # the source already supplies accurate coordinates.
            resolve_known_venue(event, venues)

            if event.get("latitude") is None and config.get("geocoding", {}).get("enabled", True):
                geocode(event, geocode_cache)

            if event.get("latitude") is None or event.get("longitude") is None:
                continue
            if not point_in_boundary(float(event["longitude"]), float(event["latitude"]), boundary):
                continue

            classify_event(event)
            if not is_idss_relevant(event):
                continue

            accepted_auto.append(finalize(event))
            status.accepted += 1
        results.append(status)
        print(f'[source:{status.key}] success={status.success} detail_links={status.detail_links} discovered={status.discovered} accepted={status.accepted} error={status.error or "-"}')

    write_json(GEOCODE_CACHE, geocode_cache)

    if results and not any(r.success for r in results):
        raise RuntimeError("All enabled automated sources failed; preserving last-known-good published dataset")

    # Automated records are authoritative when available. Manual records are
    # fallback/override safety-net entries and are retired automatically when
    # the same event is collected successfully.
    merged: list[dict[str, Any]] = []
    for event in sorted(accepted_auto, key=lambda e: (e["dates"][0], e["name"].lower())):
        if any(is_duplicate(event, current) for current in merged):
            continue
        merged.append(event)

    for event in manual_in_window(window_start, window_end, boundary):
        manual = dict(event)
        manual["origin"] = "manual"
        derive_operational_context(manual)
        if any(is_duplicate(manual, current) for current in merged):
            continue
        merged.append(manual)

    merged.sort(key=lambda e: (e["dates"][0] if e.get("dates") else "9999-99-99", e.get("start") or "", e["name"].lower()))

    # Protect against a parser collapse that still returns successful HTTP
    # responses. A severe automated-yield drop preserves the last-good data.
    previous_meta = load_json(OUTPUT_META, {})
    previous_auto = int(previous_meta.get("automated_candidate_count") or 0)
    if previous_auto >= 3 and len(accepted_auto) < max(1, math.ceil(previous_auto * 0.4)):
        raise RuntimeError(
            f"Automated candidate yield collapsed from {previous_auto} to {len(accepted_auto)}; "
            "preserving last-known-good published dataset"
        )

    write_json(OUTPUT_EVENTS, merged)
    meta = {
        "generated_at": now.isoformat(timespec="seconds"),
        "event_count": len(merged),
        "manual_event_count": sum(1 for e in merged if e.get("origin") == "manual"),
        "automated_event_count": sum(1 for e in merged if e.get("origin") == "automated"),
        "automated_candidate_count": len(accepted_auto),
        "collection_window_start": window_start.isoformat(),
        "collection_window_end": window_end.isoformat(),
        "timezone": "America/Chicago",
        "boundary_source": "NOAA/NWS reference map FeatureServer",
        "pipeline_state": "automated-multi-source-v1",
        "sources": [
            {
                "key": r.key, "name": r.name, "success": r.success,
                "health": (
                    "failed" if not r.success else
                    "degraded" if r.discovered == 0 else
                    "healthy"
                ),
                "detail_links": r.detail_links, "discovered": r.discovered,
                "accepted": r.accepted, "error": r.error,
            }
            for r in results
        ],
        "source_health": {
            "healthy": sum(1 for r in results if r.success and r.discovered > 0),
            "degraded": sum(1 for r in results if r.success and r.discovered == 0),
            "failed": sum(1 for r in results if not r.success),
            "total": len(results),
        },
        "notes": "Automated source collection is merged with a curated safety-net file. Unknown indoor/outdoor events and points outside the LIX CWA are excluded.",
    }
    write_json(OUTPUT_META, meta)

    print(f"[publish] {len(merged)} events for {window_start} through {window_end}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

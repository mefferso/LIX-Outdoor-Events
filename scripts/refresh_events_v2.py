#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import refresh_events as legacy

legacy_collect_source = legacy.collect_source

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._anchor: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
            return
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor = []
        if tag in {"h1","h2","h3","h4","p","li","div","section","article","time","address","br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
            return
        if tag == "a" and self._href:
            text = legacy.clean_text(" ".join(self._anchor))
            self.links.append((self._href, text))
            self._href = None
            self._anchor = []
        if tag in {"h1","h2","h3","h4","p","li","div","section","article","time","address"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        txt = legacy.clean_text(data)
        if not txt:
            return
        self.parts.append(txt)
        if self._href is not None:
            self._anchor.append(txt)

    @property
    def text(self) -> str:
        text = " ".join(self.parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s*\n\s*", "\n", text)
        return text.strip()


def parse_month_date(text: str, default_year: int | None = None):
    pat = re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|Sept|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+(\d{1,2})(?:,\s*(\d{4}))?",
        re.I,
    )
    m = pat.search(text)
    if not m:
        return None
    month = MONTHS[m.group(1).lower().rstrip(".")]
    year = int(m.group(3) or default_year or legacy.now_local().year)
    return datetime(year, month, int(m.group(2)), tzinfo=legacy.TZ)


def parse_date_range(text: str):
    # Common tourism-calendar forms:
    #   "September 30, 2026 - October 4, 2026"
    #   "Fri 02 Oct | 5:00pm"
    month_first = list(re.finditer(
        r"\b(January|February|March|April|May|June|July|August|September|Sept|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+(\d{1,2})(?:,\s*(\d{4}))?",
        text, re.I
    ))
    if month_first:
        first = parse_month_date(month_first[0].group(0))
        second = parse_month_date(month_first[1].group(0), first.year if first else None) if len(month_first) > 1 else None
        return first, second

    day_first = list(re.finditer(
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|Sept|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b(?:\s+(\d{4}))?",
        text, re.I
    ))
    if not day_first:
        return None, None

    def build(match, year=None):
        return datetime(
            int(match.group(3) or year or legacy.now_local().year),
            MONTHS[match.group(2).lower().rstrip(".")],
            int(match.group(1)),
            tzinfo=legacy.TZ,
        )

    first = build(day_first[0])
    second = build(day_first[1], first.year) if len(day_first) > 1 else None
    return first, second


def infer_city_state(text: str):
    # Prefer full street/city snippets, then city/state.
    m = re.search(r"\b([A-Za-z .'-]+),\s*(LA|MS)\s+\d{5}\b", text)
    if m:
        return legacy.clean_text(m.group(1)), m.group(2).upper()
    m = re.search(r"\b([A-Z][A-Za-z .'-]{2,40}),\s*(LA|MS)\b", text)
    if m:
        return legacy.clean_text(m.group(1)), m.group(2).upper()
    return "", ""


def infer_address(lines: list[str]):
    for line in lines:
        if re.search(r"\b\d{2,6}\s+[^\n,]{2,80},\s*[A-Za-z .'-]+,\s*(?:LA|MS)\s*\d{5}\b", line, re.I):
            return legacy.clean_text(line)
    return ""


def parse_generic_event_detail(html_text: str, detail_url: str):
    parser = VisibleTextParser()
    parser.feed(html_text)
    lines = [legacy.clean_text(x) for x in parser.text.splitlines() if legacy.clean_text(x)]
    if not lines:
        return None

    # h1 is usually the first useful line after nav noise; title tag is too noisy.
    title = ""
    h1m = re.search(r"<h1\b[^>]*>(.*?)</h1>", html_text, re.I | re.S)
    if h1m:
        title = legacy.clean_text(h1m.group(1))
    if not title:
        for line in lines[:80]:
            if 4 <= len(line) <= 140 and not re.search(r"^(events?|navigation|menu|search|skip to)", line, re.I):
                title = line
                break
    if not title:
        return None

    joined = "\n".join(lines)
    start, end = parse_date_range(joined)
    if not start:
        return None

    # Pull explicit time when present; otherwise keep date-only/all-day semantics.
    tm = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", joined, re.I)
    if tm:
        hour = int(tm.group(1)) % 12 + (12 if tm.group(3).upper() == "PM" else 0)
        minute = int(tm.group(2) or 0)
        start = start.replace(hour=hour, minute=minute)

    city, state = infer_city_state(joined)
    address = infer_address(lines)
    venue = ""
    for marker in ("Location:", "Venue:"):
        for i, line in enumerate(lines):
            if line.lower().startswith(marker.lower()):
                venue = legacy.clean_text(line[len(marker):]) or (lines[i+1] if i + 1 < len(lines) else "")
                break
        if venue:
            break

    # Keep enough descriptive text for outdoor / IDSS classification.
    description = " ".join(lines[:160])[:5000]
    return {
        "name": title,
        "startDate": start.date().isoformat() if not tm else start.isoformat(),
        "endDate": end.date().isoformat() if end else None,
        "location": {
            "name": venue,
            "address": {
                "streetAddress": address,
                "addressLocality": city,
                "addressRegion": state,
            },
        },
        "description": description,
        "url": detail_url,
    }


def markdown_links(text: str, base_url: str):
    out = []
    for label, href in re.findall(r"\[([^\]]+)\]\((https?://[^)]+|/[^)]+)\)", text):
        out.append((urljoin(base_url, href), legacy.clean_text(label)))
    return out


def is_event_detail_url(url: str, source: dict):
    path = urlparse(url).path.lower()
    if path.rstrip("/") in {"/event", "/events"}:
        return False
    generic_slugs = {
        "this-weekend", "annual-events", "annual-events-festivals", "festivals",
        "live-music", "concerts-live-music", "submit-your-event", "calendar",
        "holiday-celebrations", "free-events", "mardi-gras",
    }
    parts = [p for p in path.strip("/").split("/") if p]
    if parts and parts[0] in {"event", "events"}:
        if len(parts) < 2 or parts[1] in generic_slugs:
            return False
    tokens = source.get("detail_path_tokens") or source.get("href_contains_any") or ["/event/"]
    return any(str(t).lower() in path for t in tokens)


def discover_listing_links(source: dict):
    listing_urls = source.get("listing_urls") or [source["url"]]
    domain = urlparse(source["url"]).netloc.lower().removeprefix("www.")
    links: list[str] = []
    seen: set[str] = set()
    for listing_url in listing_urls:
        try:
            text = legacy.fetch_text(listing_url, timeout=int(source.get("timeout", 30)))
            parser = VisibleTextParser()
            parser.feed(text)
            pairs = [(urljoin(listing_url, href), label) for href, label in parser.links]
        except Exception:
            pairs = []

        if source.get("renderer_base"):
            try:
                rendered = legacy.fetch_text(
                    source["renderer_base"].rstrip("/") + "/" + listing_url,
                    timeout=int(source.get("render_timeout", 75)),
                    attempts=1,
                )
                pairs.extend(markdown_links(rendered, listing_url))
            except Exception:
                pass

        for absolute, _ in pairs:
            parsed = urlparse(absolute)
            if parsed.netloc.lower().removeprefix("www.") != domain:
                continue
            canonical = absolute.split("#", 1)[0].split("?", 1)[0]
            if canonical in seen or not is_event_detail_url(canonical, source):
                continue
            seen.add(canonical)
            links.append(canonical)
    return links


def _sitemap_urls(xml_text: str):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], []

    pages_with_dates: list[tuple[str, str]] = []
    child_maps: list[str] = []

    # Preserve sitemap-index children, but for URL sets prefer recently
    # modified pages. Tourism sites often keep thousands of historical event
    # URLs, so blindly taking the first/last N pages misses current events.
    for entry in list(root):
        loc = ""
        lastmod = ""
        for node in list(entry):
            tag = node.tag.lower()
            if tag.endswith("loc") and node.text:
                loc = node.text.strip()
            elif tag.endswith("lastmod") and node.text:
                lastmod = node.text.strip()
        if not loc:
            continue
        if loc.endswith(".xml"):
            child_maps.append(loc)
        else:
            pages_with_dates.append((loc, lastmod))

    if pages_with_dates:
        # ISO-formatted lastmod values sort correctly lexicographically.
        # Entries with no lastmod retain a stable fallback ordering.
        indexed = list(enumerate(pages_with_dates))
        indexed.sort(key=lambda item: (item[1][1] or "", item[0]), reverse=True)
        pages = [item[1][0] for item in indexed]
    else:
        pages = []

    return pages, child_maps

def discover_sitemap_links(source: dict):
    root = source.get("sitemap_url")
    if not root:
        p = urlparse(source["url"])
        root = f"{p.scheme}://{p.netloc}/sitemap.xml"
    pages: list[str] = []
    try:
        text = legacy.fetch_text(root, timeout=10, attempts=1)
        first_pages, maps = _sitemap_urls(text)
        pages.extend(first_pages)
        for child in maps[: int(source.get("max_sitemaps", 4))]:
            try:
                child_text = legacy.fetch_text(child, timeout=10, attempts=1)
                p2, _ = _sitemap_urls(child_text)
                pages.extend(p2)
            except Exception:
                continue
    except Exception:
        return []

    seen = set()
    event_pages = []
    domain = urlparse(source["url"]).netloc.lower().removeprefix("www.")
    for u in reversed(pages):  # newer URLs are commonly later in generated sitemaps
        if urlparse(u).netloc.lower().removeprefix("www.") != domain:
            continue
        if not is_event_detail_url(u, source):
            continue
        canonical = u.split("#", 1)[0].split("?", 1)[0]
        if canonical not in seen:
            seen.add(canonical)
            event_pages.append(canonical)
    return event_pages


def collect_enhanced_listing(source: dict):
    links = discover_listing_links(source)
    if len(links) < int(source.get("min_listing_links", 3)):
        for u in discover_sitemap_links(source):
            if u not in links:
                links.append(u)

    raw = []
    max_pages = int(source.get("max_detail_pages", 80))
    for detail_url in links[:max_pages]:
        try:
            detail_text = legacy.fetch_text(detail_url, timeout=int(source.get("timeout", 30)), attempts=1)
            events = legacy.extract_jsonld_events(detail_text)
            if not events:
                fallback = parse_generic_event_detail(detail_text, detail_url)
                if fallback:
                    events = [fallback]
            for event in events:
                # Never trust a widget/landing-page canonical URL over the
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

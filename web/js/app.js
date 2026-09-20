const TZ = "America/Chicago";
const EVENTS_URL = "data/events.json";
const META_URL = "data/build-metadata.json";
const CWA_URL = "https://mapservices.weather.noaa.gov/static/rest/services/nws_reference_maps/nws_reference_map/FeatureServer/1/query?where=cwa%3D%27LIX%27&outFields=cwa&returnGeometry=true&outSR=4326&f=geojson";

const state = {
  dayKey: null,
  category: "all",
  events: [],
  metadata: null,
  markersById: new Map(),
  cardsById: new Map()
};

const map = L.map("map", { zoomControl: true, preferCanvas: true }).setView([30.15, -90.55], 8);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);

const clusters = L.markerClusterGroup({
  showCoverageOnHover: false,
  maxClusterRadius: 48,
  spiderfyOnMaxZoom: true,
  disableClusteringAtZoom: 12
}).addTo(map);

function centralDateKey(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit"
  }).formatToParts(date);
  const grab = type => parts.find(p => p.type === type)?.value;
  return `${grab("year")}-${grab("month")}-${grab("day")}`;
}

function addDays(dateKey, count) {
  const [y,m,d] = dateKey.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + count, 12));
  return dt.toISOString().slice(0,10);
}

function prettyDate(dateKey) {
  const [y,m,d] = dateKey.split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", weekday: "short", timeZone: "UTC" })
    .format(new Date(Date.UTC(y,m-1,d,12)));
}

function shortDayLabel(i) {
  if (i === 0) return "TODAY";
  return `DAY ${i}`;
}

function eventOccursOn(event, dateKey) {
  return Array.isArray(event.dates) && event.dates.includes(dateKey);
}

function filteredEvents() {
  return state.events
    .filter(e => eventOccursOn(e, state.dayKey))
    .filter(e => state.category === "all" || e.category === state.category)
    .sort((a,b) => (a.start || "").localeCompare(b.start || "") || a.name.localeCompare(b.name));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;")
    .replaceAll('"',"&quot;").replaceAll("'","&#039;");
}

function displayEventName(event) {
  return String(event?.name || "").replace(/\bvs\.?\b/gi, "vs");
}

function formatTime(event) {
  if (event.all_day) return "All day / time not specified";
  const start = new Date(event.start);
  const end = event.end ? new Date(event.end) : null;
  const opts = { timeZone: TZ, hour: "numeric", minute: "2-digit" };
  const startText = new Intl.DateTimeFormat("en-US", opts).format(start);
  if (!end) return startText + " CT";
  const endText = new Intl.DateTimeFormat("en-US", opts).format(end);
  return `${startText}–${endText} CT`;
}

function categoryLabel(category) {
  return ({
    sports: "Sports",
    festival: "Festival / concert",
    race_parade: "Race / parade",
    coastal_marine: "Coastal / marine",
    other: "Other"
  })[category] || category;
}
function eventSymbolType(event) {
  const text = `${event.name || ""} ${event.venue || ""}`.toLowerCase();
  if (event.category === "sports") {
    if (/football|tiger stadium|yulman|guidry stadium|strawberry stadium|mumford stadium/.test(text)) return "football";
    return "sports";
  }
  if (event.category === "race_parade") {
    if (/parade|mardi gras|krewe|carnival/.test(text)) return "parade";
    return "race";
  }
  if (event.category === "festival") return "festival";
  if (event.category === "coastal_marine") return "marine";
  return "other";
}

function eventIconGlyph(event) {
  const type = eventSymbolType(event);
  const text = `${event.name || ""} ${event.venue || ""}`.toLowerCase();

  if (type === "football") return "🏈";
  if (type === "parade") return "⚜️";
  if (type === "race") return "🏃";
  if (type === "festival") return "🎵";
  if (type === "marine") return "⚓";

  if (type === "sports") {
    if (/baseball/.test(text)) return "⚾";
    if (/softball/.test(text)) return "🥎";
    if (/soccer/.test(text)) return "⚽";
    if (/golf/.test(text)) return "⛳";
    if (/rugby/.test(text)) return "🏉";
    return "🏟️";
  }

  return "📅";
}


function popupHtml(event) {
  return `
    <div class="popup-card">
      <div class="popup-title">
        <span class="event-glyph popup-glyph" aria-hidden="true">${eventIconGlyph(event)}</span>
        <span>${escapeHtml(displayEventName(event))}</span>
      </div>

      <div class="popup-detail-list">
        <div class="popup-detail-row">
          <span class="popup-detail-label">Event Type</span>
          <span class="popup-detail-value">${escapeHtml(categoryLabel(event.category))}</span>
        </div>
        <div class="popup-detail-row">
          <span class="popup-detail-label">Date</span>
          <span class="popup-detail-value">${escapeHtml(prettyDate(state.dayKey))}</span>
        </div>
        <div class="popup-detail-row">
          <span class="popup-detail-label">Time</span>
          <span class="popup-detail-value">${escapeHtml(formatTime(event))}</span>
        </div>
        <div class="popup-detail-row">
          <span class="popup-detail-label">Venue</span>
          <span class="popup-detail-value">${escapeHtml(event.venue || "Not listed")}</span>
        </div>
        ${event.city ? `
          <div class="popup-detail-row">
            <span class="popup-detail-label">City</span>
            <span class="popup-detail-value">${escapeHtml(event.city)}</span>
          </div>
        ` : ""}
        ${event.parish_county ? `
          <div class="popup-detail-row">
            <span class="popup-detail-label">Parish / County</span>
            <span class="popup-detail-value">${escapeHtml(event.parish_county)}</span>
          </div>
        ` : ""}
        <div class="popup-detail-row">
          <span class="popup-detail-label">Outdoor Status</span>
          <span class="popup-detail-value">${escapeHtml(event.outdoor_status === "partial" ? "Partial" : "Outdoors")}</span>
        </div>
        <div class="popup-detail-row">
          <span class="popup-detail-label">Location Confidence</span>
          <span class="popup-detail-value">${Math.round((event.location_confidence || 0) * 100)}%</span>
        </div>
        <div class="popup-detail-row">
          <span class="popup-detail-label">Source</span>
          <span class="popup-detail-value">
            ${event.source_url
              ? `<a class="popup-source-value-link" href="${escapeHtml(event.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(event.source_name || "Source")} ↗</a>`
              : escapeHtml(event.source_name || "Unknown")}
          </span>
        </div>
      </div>

      ${event.weather_exposure_notes ? `
        <div class="popup-note">${escapeHtml(event.weather_exposure_notes)}</div>
      ` : ""}

    </div>
  `;
}

function markerIcon(event) {
  return L.divIcon({
    className: "event-marker-icon",
    html: `<div class="map-event-glyph" aria-hidden="true">${eventIconGlyph(event)}</div>`,
    iconSize: [38,38],
    iconAnchor: [19,19],
    popupAnchor: [0,-17]
  });
}

function renderDates() {
  const strip = document.getElementById("dateStrip");
  strip.innerHTML = "";
  const today = centralDateKey();
  for (let i = 0; i < 8; i++) {
    const key = addDays(today, i);
    const dayCount = state.events.filter(e => eventOccursOn(e, key)).length;
    const btn = document.createElement("button");
    btn.className = "day-button" + (state.dayKey === key ? " active" : "") + (dayCount === 0 ? " zero" : "");
    btn.dataset.date = key;
    btn.innerHTML = `<span class="day-label">${shortDayLabel(i)} <span class="day-count">${dayCount}</span></span><span class="day-date">${prettyDate(key)}</span>`;
    btn.addEventListener("click", () => {
      state.dayKey = key;
      renderDates();
      renderEvents();
    });
    strip.appendChild(btn);
  }
}

function clearFocusedEvent() {
  document.querySelectorAll(".event-card.active").forEach(el => el.classList.remove("active"));
  for (const marker of state.markersById.values()) marker.setZIndexOffset(0);
}

function focusEvent(eventId, { scroll = false } = {}) {
  clearFocusedEvent();
  const card = state.cardsById.get(eventId);
  const marker = state.markersById.get(eventId);
  if (card) {
    card.classList.add("active");
    if (scroll) card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  if (marker) marker.setZIndexOffset(1000);
}

function renderSourceHealth() {
  const btn = document.getElementById("sourceHealth");
  const panel = document.getElementById("sourceHealthPanel");
  if (!btn || !panel) return;
  const sources = state.metadata?.sources || [];
  if (!sources.length) {
    btn.textContent = "Source health unavailable";
    return;
  }
  const health = state.metadata?.source_health || {
    healthy: sources.filter(s => s.health === "healthy" || (s.success && s.discovered > 0)).length,
    degraded: sources.filter(s => s.health === "degraded" || (s.success && s.discovered === 0)).length,
    failed: sources.filter(s => s.health === "failed" || !s.success).length,
    total: sources.length
  };
  const problemCount = health.degraded + health.failed;
  btn.className = "source-health " + (health.failed ? "bad" : problemCount ? "warn" : "good");
  btn.textContent = `Sources: ${health.healthy}/${health.total} healthy`;
  panel.innerHTML = sources.map(src => {
    const status = src.health || (!src.success ? "failed" : src.discovered > 0 ? "healthy" : "degraded");
    const detail = src.error ? "failed" : `${src.discovered ?? 0} found · ${src.accepted ?? 0} mapped`;
    return `<div class="source-health-row"><span class="health-dot ${escapeHtml(status)}"></span><span>${escapeHtml(src.name)}</span><span class="health-detail">${escapeHtml(detail)}</span></div>`;
  }).join("");
  btn.addEventListener("click", () => {
    const opening = panel.hidden;
    panel.hidden = !opening;
    btn.setAttribute("aria-expanded", String(opening));
  });
  document.addEventListener("click", e => {
    if (!panel.hidden && !panel.contains(e.target) && e.target !== btn) {
      panel.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    }
  });
}

function renderEvents() {
  const events = filteredEvents();
  clusters.clearLayers();
  state.markersById.clear();
  state.cardsById.clear();

  for (const event of events) {
    const marker = L.marker([event.latitude, event.longitude], { icon: markerIcon(event) })
      .bindPopup(popupHtml(event), { maxWidth: 340 });
    marker.on("click", () => focusEvent(event.id, { scroll: true }));
    marker.on("mouseover", () => focusEvent(event.id));
    marker.on("mouseout", () => clearFocusedEvent());
    clusters.addLayer(marker);
    state.markersById.set(event.id, marker);
  }

  const list = document.getElementById("eventList");
  const count = document.getElementById("eventCount");
  count.textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;
  list.innerHTML = "";

  if (!events.length) {
    list.appendChild(document.getElementById("emptyTemplate").content.cloneNode(true));
    return;
  }

  for (const event of events) {
    const card = document.createElement("article");
    card.className = `event-card ${event.importance}`;
    card.innerHTML = `
      <h2><span class="event-glyph card-glyph" aria-hidden="true">${eventIconGlyph(event)}</span><span>${escapeHtml(displayEventName(event))}</span></h2>
      <div class="event-detail-list">
        <div class="event-detail-row">
          <span class="event-detail-label">Date:</span>
          <span class="event-detail-value">${escapeHtml(prettyDate(state.dayKey))}</span>
        </div>
        <div class="event-detail-row">
          <span class="event-detail-label">Time:</span>
          <span class="event-detail-value">${escapeHtml(formatTime(event))}</span>
        </div>
        <div class="event-detail-row">
          <span class="event-detail-label">Venue:</span>
          <span class="event-detail-value">${escapeHtml(event.venue || "Not listed")}</span>
        </div>
        ${event.city ? `
          <div class="event-detail-row">
            <span class="event-detail-label">City:</span>
            <span class="event-detail-value">${escapeHtml(event.city)}</span>
          </div>
        ` : ""}
        ${event.parish_county ? `
          <div class="event-detail-row">
            <span class="event-detail-label">Parish / County:</span>
            <span class="event-detail-value">${escapeHtml(event.parish_county)}</span>
          </div>
        ` : ""}
        <div class="event-detail-row">
          <span class="event-detail-label">Source:</span>
          <span class="event-detail-value">${escapeHtml(event.source_name || "Unknown")}</span>
        </div>
      </div>
      <div class="badges">
        <span class="badge">${escapeHtml(categoryLabel(event.category))}</span>
        <span class="badge">${escapeHtml(event.outdoor_status)}</span>
      </div>
    `;
    card.addEventListener("mouseenter", () => focusEvent(event.id));
    card.addEventListener("mouseleave", () => clearFocusedEvent());
    card.addEventListener("click", () => {
      const marker = state.markersById.get(event.id);
      if (!marker) return;
      focusEvent(event.id);
      map.setView(marker.getLatLng(), Math.max(map.getZoom(), 13), { animate: true });
      marker.openPopup();
    });
    state.cardsById.set(event.id, card);
    list.appendChild(card);
  }
}

async function loadCwa() {
  try {
    const res = await fetch(CWA_URL);
    if (!res.ok) throw new Error(`CWA HTTP ${res.status}`);
    const geojson = await res.json();
    const layer = L.geoJSON(geojson, {
      style: { color: "#334f63", weight: 2.2, opacity: .9, fillColor: "#5f8ca8", fillOpacity: .035 }
    }).addTo(map);
    const bounds = layer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds.pad(.03));
  } catch (err) {
    console.warn("CWA boundary unavailable", err);
    map.fitBounds([[28.9,-91.9],[31.35,-89.15]]);
  }
}

function renderFreshness() {
  const el = document.getElementById("freshness");
  if (!state.metadata?.generated_at) {
    el.textContent = "Data age unavailable";
    return;
  }
  const generated = new Date(state.metadata.generated_at);
  const ageHours = (Date.now() - generated.getTime()) / 36e5;
  const stamp = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ, month: "short", day: "numeric", hour: "numeric", minute: "2-digit"
  }).format(generated);
  el.textContent = `Updated ${stamp} CT · ${state.metadata.event_count ?? state.events.length} mapped events`;
  if (ageHours > 12) el.classList.add("stale");
}

function bindFilters() {
  document.querySelectorAll(".filter").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".filter").forEach(x => x.classList.remove("active"));
      btn.classList.add("active");
      state.category = btn.dataset.category;
      renderEvents();
    });
  });
}

async function boot() {
  state.dayKey = centralDateKey();
  bindFilters();
  renderDates();

  const [eventsRes, metaRes] = await Promise.all([fetch(EVENTS_URL), fetch(META_URL)]);
  if (!eventsRes.ok) throw new Error(`events.json HTTP ${eventsRes.status}`);
  state.events = await eventsRes.json();
  if (metaRes.ok) state.metadata = await metaRes.json();

  renderFreshness();
  renderSourceHealth();
  renderDates();
  renderEvents();
  await loadCwa();
}

boot().catch(err => {
  console.error(err);
  document.getElementById("freshness").textContent = "Event data unavailable";
  document.getElementById("eventList").innerHTML = '<div class="empty-state"><strong>Could not load event data.</strong><span>Check the latest deployment or data refresh.</span></div>';
});
const TZ = "America/Chicago";
const EVENTS_URL = "data/events.json";
const META_URL = "data/build-metadata.json";
const CWA_URL = "https://mapservices.weather.noaa.gov/static/rest/services/nws_reference_maps/nws_reference_map/FeatureServer/1/query?where=cwa%3D%27LIX%27&outFields=cwa&returnGeometry=true&outSR=4326&f=geojson";

const state = {
  dayKey: null,
  category: "all",
  majorOnly: false,
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
    .filter(e => !state.majorOnly || e.importance === "major")
    .sort((a,b) => (a.start || "").localeCompare(b.start || "") || a.name.localeCompare(b.name));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;")
    .replaceAll('"',"&quot;").replaceAll("'","&#039;");
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

function eventIconSvg(event, className = "event-icon") {
  const type = eventSymbolType(event);
  const attrs = `class="${className}" viewBox="0 0 24 24" aria-hidden="true" focusable="false"`;
  const paths = {
    football: `<svg ${attrs}><path d="M5.2 18.8c-3.2-3.2-2.5-8.9 1.5-12.9s9.7-4.7 12.9-1.5 2.5 8.9-1.5 12.9-9.7 4.7-12.9 1.5Z"/><path d="m7.1 16.9 9.8-9.8M9.3 10.6l4.1 4.1M11 8.9l4.1 4.1M8.2 12.2l1.7 1.7M14.1 8.1l1.7 1.7"/></svg>`,
    parade: `<svg ${attrs}><path d="M12 2c.4 3 1.9 4.7 4.6 5.1-1.8 1.1-2.5 2.7-2.2 4.9 1.4-.8 2.8-.8 4.2 0-.7 2.6-2.4 4.2-5.1 4.8.6 1.8.1 3.5-1.5 5.2-1.6-1.7-2.1-3.4-1.5-5.2-2.7-.6-4.4-2.2-5.1-4.8 1.4-.8 2.8-.8 4.2 0 .3-2.2-.4-3.8-2.2-4.9C10.1 6.7 11.6 5 12 2Z"/></svg>`,
    race: `<svg ${attrs}><circle cx="14.5" cy="4.5" r="2"/><path d="m12.8 7.4-2.9 4.1 3.1 2.1 1.8 5.3M9.9 11.5l-4.5 1.1M13 13.6l-3.9 5.1M12.3 8.1l4.2 2.7 2.1-.7"/></svg>`,
    festival: `<svg ${attrs}><path d="M9 18V6l9-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="15.5" cy="16" r="2.5"/></svg>`,
    marine: `<svg ${attrs}><circle cx="12" cy="5" r="2"/><path d="M12 7v12M7 10h10M5 14c1.6 3.5 4 5 7 5s5.4-1.5 7-5M8 19l4 3 4-3"/></svg>`,
    sports: `<svg ${attrs}><circle cx="12" cy="12" r="8"/><path d="M12 4v16M4 12h16"/></svg>`,
    other: `<svg ${attrs}><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 9h16"/></svg>`
  };
  return paths[type] || paths.other;
}

function popupHtml(event) {
  const source = event.source_url
    ? `<div class="popup-source"><a href="${escapeHtml(event.source_url)}" target="_blank" rel="noopener">Open source ↗</a></div>`
    : "";
  return `
    <div class="popup-title"><span class="popup-title-icon">${eventIconSvg(event, "event-icon popup-icon")}</span><span>${escapeHtml(event.name)}</span></div>
    <div class="popup-line"><strong>${escapeHtml(event.importance.toUpperCase())}</strong> · ${escapeHtml(categoryLabel(event.category))}</div>
    <div class="popup-line">${escapeHtml(prettyDate(state.dayKey))} · ${escapeHtml(formatTime(event))}</div>
    <div class="popup-line">${escapeHtml(event.venue || "Location")}, ${escapeHtml(event.city || "")}</div>
    ${event.idss_area || event.parish_county ? `<div class="popup-line">${escapeHtml([event.idss_area, event.parish_county].filter(Boolean).join(" · "))}</div>` : ""}
    <div class="popup-line">${escapeHtml(event.outdoor_status === "partial" ? "Partly outdoors" : "Outdoors")} · location confidence ${Math.round((event.location_confidence || 0) * 100)}%</div>
    ${event.weather_exposure_notes ? `<div class="popup-notes">${escapeHtml(event.weather_exposure_notes)}</div>` : ""}
    ${source}
  `;
}

function markerIcon(event) {
  return L.divIcon({
    className: "",
    html: `<div class="marker-pin ${escapeHtml(event.importance)}"><span class="marker-symbol">${eventIconSvg(event, "event-icon marker-icon")}</span></div>`,
    iconSize: [26,26],
    iconAnchor: [13,24],
    popupAnchor: [0,-21]
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
      <h2><span class="event-title-icon">${eventIconSvg(event)}</span><span>${escapeHtml(event.name)}</span></h2>
      <div class="meta">${escapeHtml(formatTime(event))}<br>${escapeHtml(event.venue || "")}${event.city ? " · " + escapeHtml(event.city) : ""}${event.idss_area ? "<br>" + escapeHtml(event.idss_area) : ""}${event.parish_county ? " · " + escapeHtml(event.parish_county) : ""}<br>Source: ${escapeHtml(event.source_name || "Unknown")}</div>
      <div class="badges">
        <span class="badge ${escapeHtml(event.importance)}">${escapeHtml(event.importance)}</span>
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
  document.getElementById("majorOnly").addEventListener("change", e => {
    state.majorOnly = e.target.checked;
    renderEvents();
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
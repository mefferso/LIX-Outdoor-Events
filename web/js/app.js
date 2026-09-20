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
    football: `<svg ${attrs}><path fill="currentColor" d="M4.5 15.8c0-1.7.7-3.4 2-4.7L11.1 6.5c1.3-1.3 3-2 4.7-2 1.3 0 2.6.4 3.8 1.1l-2.1 2.1-1.6-.5-.5 1.6-3.7 3.7 1.6 1.6 3.7-3.7 1.6-.5-.5-1.6 2.1-2.1c.7 1.2 1.1 2.5 1.1 3.8 0 1.7-.7 3.4-2 4.7l-4.6 4.6c-1.3 1.3-3 2-4.7 2-1.3 0-2.6-.4-3.8-1.1l2.1-2.1 1.6.5.5-1.6 3.7-3.7-1.6-1.6-3.7 3.7-1.6.5.5 1.6-2.1 2.1c-.7-1.2-1.1-2.5-1.1-3.8Z"/></svg>`,
    parade: `<svg ${attrs}><path fill="currentColor" d="M12 2c1 2.8 2.8 4.5 5.5 5-2 1.3-2.9 3.2-2.6 5.6 1.5-.9 3.1-.9 4.8 0-.8 3-2.8 4.8-5.8 5.5.7 2.1.1 4.1-1.9 6-2-1.9-2.6-3.9-1.9-6-3-.7-5-2.5-5.8-5.5 1.7-.9 3.3-.9 4.8 0 .3-2.4-.6-4.3-2.6-5.6 2.7-.5 4.5-2.2 5.5-5Z"/></svg>`,
    race: `<svg ${attrs}><path fill="currentColor" d="M15.2 5.2a2.2 2.2 0 1 1 0-4.4 2.2 2.2 0 0 1 0 4.4ZM8.2 22l2.8-5.8-2.6-2.1-3.3 1 .6-2 3.5-1.1 2.2-3.2 2.8 1.1 2.9 2.1 2-.6-.5 1.8-2.6.8-2.8-1.8-1.4 2 1.1 3.2 1.3 3.6h-2.2l-1.5-4.1-1.8 2.4L10.4 22H8.2Z"/></svg>`,
    festival: `<svg ${attrs}><path fill="currentColor" d="M10 4v10.6A3.4 3.4 0 1 1 8 11.5V6.1l8-1.9v9.4a3.4 3.4 0 1 1-2-3.1V4.7L10 5.6V4Z"/></svg>`,
    marine: `<svg ${attrs}><path fill="currentColor" d="M11 3a2 2 0 1 1 2 0v7h4v2h-4v6.2l2.8-1.7 1 1.7-4.8 2.9-4.8-2.9 1-1.7 2.8 1.7V12H7v-2h4V3Z"/></svg>`,
    sports: `<svg ${attrs}><path fill="currentColor" d="M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20Zm-1 2.3A8 8 0 0 0 5 8l2.2.5L8.4 6l2.6-1.7Zm2 0 2.6 1.7 1.2 2.5L19 8a8 8 0 0 0-6-3.7ZM4.3 10a8 8 0 0 0 1.2 6l1.9-1.6-.3-2.4L4.3 10Zm15.4 0-2.8 2 .3 2.4 1.9 1.6a8 8 0 0 0 1.2-6ZM9.2 18.7a8 8 0 0 0 5.6 0l-2.8-2.1-2.8 2.1Z"/></svg>`,
    other: `<svg ${attrs}><path fill="currentColor" d="M7 2h2v2h6V2h2v2h2a2 2 0 0 1 2 2v13a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V6a2 2 0 0 1 2-2h2V2Zm12 8H5v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-9Z"/></svg>`
  };

  return paths[type] || paths.other;
}

function markerColorBySymbol(type) {
  return ({
    football: "#7c2d12",
    sports: "#14532d",
    parade: "#7c3aed",
    race: "#0f766e",
    festival: "#b45309",
    marine: "#1d4ed8",
    other: "#475569"
  })[type] || "#475569";
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
  const type = eventSymbolType(event);
  const color = markerColorBySymbol(type);

  return L.divIcon({
    className: "",
    html: `
      <div class="marker-badge" style="background:${color}">
        ${eventIconSvg(event, "event-icon marker-icon")}
      </div>
    `,
    iconSize: [30,30],
    iconAnchor: [15,15],
    popupAnchor: [0,-14]
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
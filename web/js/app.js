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
  markersById: new Map()
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

function popupHtml(event) {
  const source = event.source_url
    ? `<div class="popup-source"><a href="${escapeHtml(event.source_url)}" target="_blank" rel="noopener">Open source ↗</a></div>`
    : "";
  return `
    <div class="popup-title">${escapeHtml(event.name)}</div>
    <div class="popup-line"><strong>${escapeHtml(event.importance.toUpperCase())}</strong> · ${escapeHtml(categoryLabel(event.category))}</div>
    <div class="popup-line">${escapeHtml(prettyDate(state.dayKey))} · ${escapeHtml(formatTime(event))}</div>
    <div class="popup-line">${escapeHtml(event.venue || "Location")}, ${escapeHtml(event.city || "")}</div>
    <div class="popup-line">${escapeHtml(event.outdoor_status === "partial" ? "Partly outdoors" : "Outdoors")} · location confidence ${Math.round((event.location_confidence || 0) * 100)}%</div>
    ${event.weather_exposure_notes ? `<div class="popup-notes">${escapeHtml(event.weather_exposure_notes)}</div>` : ""}
    ${source}
  `;
}

function markerIcon(importance) {
  return L.divIcon({
    className: "",
    html: `<div class="marker-pin ${escapeHtml(importance)}"></div>`,
    iconSize: [22,22],
    iconAnchor: [11,20],
    popupAnchor: [0,-18]
  });
}

function renderDates() {
  const strip = document.getElementById("dateStrip");
  strip.innerHTML = "";
  const today = centralDateKey();
  for (let i = 0; i < 8; i++) {
    const key = addDays(today, i);
    const btn = document.createElement("button");
    btn.className = "day-button" + (state.dayKey === key ? " active" : "");
    btn.dataset.date = key;
    btn.innerHTML = `<span class="day-label">${shortDayLabel(i)}</span><span class="day-date">${prettyDate(key)}</span>`;
    btn.addEventListener("click", () => {
      state.dayKey = key;
      renderDates();
      renderEvents();
    });
    strip.appendChild(btn);
  }
}

function renderEvents() {
  const events = filteredEvents();
  clusters.clearLayers();
  state.markersById.clear();

  for (const event of events) {
    const marker = L.marker([event.latitude, event.longitude], { icon: markerIcon(event.importance) })
      .bindPopup(popupHtml(event), { maxWidth: 340 });
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
      <h2>${escapeHtml(event.name)}</h2>
      <div class="meta">${escapeHtml(formatTime(event))}<br>${escapeHtml(event.venue || "")}${event.city ? " · " + escapeHtml(event.city) : ""}</div>
      <div class="badges">
        <span class="badge ${escapeHtml(event.importance)}">${escapeHtml(event.importance)}</span>
        <span class="badge">${escapeHtml(categoryLabel(event.category))}</span>
        <span class="badge">${escapeHtml(event.outdoor_status)}</span>
      </div>
    `;
    card.addEventListener("click", () => {
      const marker = state.markersById.get(event.id);
      if (!marker) return;
      map.setView(marker.getLatLng(), Math.max(map.getZoom(), 13), { animate: true });
      marker.openPopup();
    });
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
  renderEvents();
  await loadCwa();
}

boot().catch(err => {
  console.error(err);
  document.getElementById("freshness").textContent = "Event data unavailable";
  document.getElementById("eventList").innerHTML = '<div class="empty-state"><strong>Could not load event data.</strong><span>Check the latest deployment or data refresh.</span></div>';
});
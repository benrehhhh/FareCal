/* =====================================================================
 * FareCal — Leaflet interactive map
 * Stages 1-3:
 *   - Stage 1: map init with OpenStreetMap tiles + attribution.
 *   - Stage 2: GPS starting point ("Use My Current Location") and manual
 *     start selection by tapping the map.
 *   - Stage 3: destination search via Nominatim geocoding.
 *
 * The map object is stored on window.FareCalMap so later stages
 * (routing, fare integration) can build on it.
 * ===================================================================== */

/* Default view for the demo region (Metro Cebu). */
const DEFAULT_CENTER = [10.3157, 123.8854];
const DEFAULT_ZOOM = 12;
const LOCATE_ZOOM = 15;
const DEST_ZOOM = 14;
const DEST_DEBOUNCE_MS = 800;
const DEST_MIN_CHARS = 3;
const GEOCODE_URL = "https://nominatim.openstreetmap.org/search";
const OSRM_URL = "https://router.project-osrm.org/route/v1/driving";

/* The map instance — declared at module scope and created once the page is
 * ready so every helper (GPS + geocoding) can reach it. */
let map = null;

/* "Start" marker icon — a green badge above a pin. */
const startIcon = L.divIcon({
    className: "fc-start-marker",
    html:
        `<div class="fc-marker-pin" title="Start"></div>` +
        `<span class="fc-marker-label">Start</span>`,
    iconSize: [32, 44],
    iconAnchor: [16, 44],
    popupAnchor: [0, -40],
});

/* "Destination" marker icon — a blue badge above a pin. */
const destIcon = L.divIcon({
    className: "fc-end-marker",
    html:
        `<div class="fc-marker-pin" title="Destination"></div>` +
        `<span class="fc-marker-label">Destination</span>`,
    iconSize: [32, 44],
    iconAnchor: [16, 44],
    popupAnchor: [0, -40],
});

/* Current starting point. */
let startLatLng = null;
let startName = null;
let startMarker = null;

/* Current destination. */
let destLatLng = null;
let destName = null;
let destMarker = null;

/* ---- Starting point (GPS / manual) ------------------------------- */

function setStartPoint(latlng, label) {
    if (!map) {
        return;
    }
    // Normalize to a real L.LatLng — GPS and map-click pass different shapes.
    startLatLng = L.latLng(latlng);
    startName = label || "Selected point";

    if (startMarker) {
        startMarker.setLatLng(latlng);
    } else {
        startMarker = L.marker(latlng, { icon: startIcon, zIndexOffset: 1000 }).addTo(map);
    }

    const input = document.getElementById("originInput");
    if (input) {
        input.value = label || `My current location (${startLatLng.lat.toFixed(4)}, ${startLatLng.lng.toFixed(4)})`;
    }

    requestRoute();
}

function setLocateLoading(isLoading) {
    const btn = document.getElementById("locateBtn");
    if (!btn) {
        return;
    }
    btn.disabled = isLoading;
    document.getElementById("locateSpinner").classList.toggle("d-none", !isLoading);
    document.getElementById("locateBtnText").textContent = isLoading
        ? "Locating…"
        : "Use My Current Location";
}

function useCurrentLocation() {
    clearAlert();

    if (!map) {
        showAlert("The map is not ready yet. Please reload the page and try again.", "warning");
        return;
    }

    // Geolocation only works on secure contexts (HTTPS or localhost).
    const onLocalhost = /^(localhost|127\.0\.0\.1)$/.test(window.location.hostname);
    if (!navigator.geolocation || (window.isSecureContext === false && !onLocalhost)) {
        showAlert(
            "Location access is unavailable in this browser. You can tap the map to select your starting point manually.",
            "warning"
        );
        return;
    }

    setLocateLoading(true);

    navigator.geolocation.getCurrentPosition(
        (position) => {
            // `finally` guarantees the button is re-enabled even if a helper throws.
            try {
                const latlng = [position.coords.latitude, position.coords.longitude];
                setStartPoint(latlng, "My current location");
                map.setView(latlng, LOCATE_ZOOM);
                showAlert("Your current location was set as the starting point.", "success");
            } finally {
                setLocateLoading(false);
            }
        },
        (error) => {
            const messages = {
                1: "Unable to access your location. You can tap the map to select your starting point manually.",
                2: "Your location is currently unavailable. Please try again or tap the map to select a starting point.",
                3: "We could not get your location in time. Please try again or tap the map to select a starting point.",
            };
            showAlert(
                messages[error.code] || "Unable to access your location. You can tap the map to select your starting point manually.",
                "warning"
            );
            setLocateLoading(false);
        },
        { enableHighAccuracy: false, timeout: 15000, maximumAge: 30000 }
    );
}

/* ---- Destination search (Nominatim) ------------------------------ */

let destSearchTimer = null;
let destAbort = null;

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value || "";
    return div.innerHTML;
}

function setDestinationPoint(latlng, name, shortLabel) {
    if (!map) {
        return;
    }
    // Normalize to a real L.LatLng so distanceTo() and URL building work.
    destLatLng = L.latLng(latlng);
    destName = name;

    if (destMarker) {
        destMarker.setLatLng(latlng);
    } else {
        destMarker = L.marker(latlng, { icon: destIcon, zIndexOffset: 1000 }).addTo(map);
    }

    const input = document.getElementById("destinationInput");
    if (input) {
        input.value = shortLabel || name;
    }
    document.getElementById("destinationStatus").textContent = "";
    closeDestinationResults();
    map.setView(latlng, DEST_ZOOM);
    requestRoute();
}

function closeDestinationResults() {
    if (destAbort) {
        destAbort.abort();
        destAbort = null;
    }
    const list = document.getElementById("destinationResults");
    if (list) {
        list.innerHTML = "";
        list.classList.add("d-none");
    }
}

async function searchDestination() {
    const input = document.getElementById("destinationInput");
    const status = document.getElementById("destinationStatus");
    const query = (input.value || "").trim();

    if (query.length < DEST_MIN_CHARS) {
        closeDestinationResults();
        status.textContent = "";
        return;
    }

    // Cancel any still-pending request so stale results never overwrite newer ones.
    if (destAbort) {
        destAbort.abort();
    }
    destAbort = new AbortController();

    const list = document.getElementById("destinationResults");
    list.innerHTML =
        `<div class="list-group-item text-muted">` +
        `<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>` +
        `Searching…</div>`;
    list.classList.remove("d-none");

    try {
        const url = new URL(GEOCODE_URL);
        url.searchParams.set("q", query);
        url.searchParams.set("format", "jsonv2");
        url.searchParams.set("limit", "5");
        url.searchParams.set("countrycodes", "ph");
        const response = await fetch(url, { signal: destAbort.signal });
        if (!response.ok) {
            throw new Error(`Geocoding request failed (${response.status})`);
        }
        const items = await response.json();

        list.innerHTML = "";
        if (items.length === 0) {
            list.innerHTML =
                `<div class="list-group-item text-muted">` +
                `No matching place found. Try a more specific name.</div>`;
            list.classList.remove("d-none");
            status.textContent = "";
            return;
        }

        items.forEach((item) => {
            const label = item.name || item.display_name.split(",")[0].trim();
            const button = document.createElement("button");
            button.type = "button";
            button.className = "list-group-item list-group-item-action";
            button.innerHTML =
                `<span class="fw-semibold d-block">${escapeHtml(label)}</span>` +
                `<span class="small text-muted">${escapeHtml(item.display_name)}</span>`;
            button.addEventListener("click", () => {
                setDestinationPoint(
                    [parseFloat(item.lat), parseFloat(item.lon)],
                    item.display_name,
                    label
                );
            });
            list.appendChild(button);
        });
        list.classList.remove("d-none");
    } catch (error) {
        // A newer search cancelled this one — just drop it quietly.
        if (error && error.name === "AbortError") {
            return;
        }
        closeDestinationResults();
        status.textContent = "";
        showAlert(
            "The destination search service is currently unavailable. Please try again later.",
            "danger"
        );
    }
}

function scheduleDestSearch() {
    clearTimeout(destSearchTimer);
    destSearchTimer = setTimeout(searchDestination, DEST_DEBOUNCE_MS);
}

/* ---- Starting-point search (manual origin) ------------------------ */

let originSearchTimer = null;
let originAbort = null;

function closeOriginResults() {
    if (originAbort) {
        originAbort.abort();
        originAbort = null;
    }
    const list = document.getElementById("originResults");
    if (list) {
        list.innerHTML = "";
        list.classList.add("d-none");
    }
}

async function searchOrigin() {
    const input = document.getElementById("originInput");
    const query = (input.value || "").trim();

    if (query.length < DEST_MIN_CHARS) {
        closeOriginResults();
        return;
    }

    if (originAbort) {
        originAbort.abort();
    }
    originAbort = new AbortController();

    const list = document.getElementById("originResults");
    list.innerHTML =
        `<div class="list-group-item text-muted">` +
        `<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>` +
        `Searching…</div>`;
    list.classList.remove("d-none");

    try {
        const url = new URL(GEOCODE_URL);
        url.searchParams.set("q", query);
        url.searchParams.set("format", "jsonv2");
        url.searchParams.set("limit", "5");
        url.searchParams.set("countrycodes", "ph");
        const response = await fetch(url, { signal: originAbort.signal });
        if (!response.ok) {
            throw new Error(`Geocoding request failed (${response.status})`);
        }
        const items = await response.json();

        list.innerHTML = "";
        if (items.length === 0) {
            list.innerHTML =
                `<div class="list-group-item text-muted">` +
                `No matching place found. Try a more specific name.</div>`;
            list.classList.remove("d-none");
            return;
        }

        items.forEach((item) => {
            const label = item.name || item.display_name.split(",")[0].trim();
            const button = document.createElement("button");
            button.type = "button";
            button.className = "list-group-item list-group-item-action";
            button.innerHTML =
                `<span class="fw-semibold d-block">${escapeHtml(label)}</span>` +
                `<span class="small text-muted">${escapeHtml(item.display_name)}</span>`;
            button.addEventListener("click", () => {
                setStartPoint(
                    [parseFloat(item.lat), parseFloat(item.lon)],
                    label
                );
                closeOriginResults();
            });
            list.appendChild(button);
        });
        list.classList.remove("d-none");
    } catch (error) {
        if (error && error.name === "AbortError") {
            return;
        }
        closeOriginResults();
        showAlert(
            "The starting-location search service is currently unavailable. Please try tapping the map instead.",
            "warning"
        );
    }
}

function scheduleOriginSearch() {
    clearTimeout(originSearchTimer);
    originSearchTimer = setTimeout(searchOrigin, DEST_DEBOUNCE_MS);
}

/* ---- Swap starting point and destination -------------------------- */

function swapLocations() {
    if (!map || !startLatLng || !destLatLng) {
        return null;
    }
    const oldStartLatLng = startLatLng;
    const oldStartName = startName;
    const oldDestLatLng = destLatLng;
    const oldDestName = destName;

    startLatLng = oldDestLatLng;
    startName = oldDestName;
    destLatLng = oldStartLatLng;
    destName = oldStartName;

    if (startMarker) {
        startMarker.setLatLng(startLatLng);
    }
    if (destMarker) {
        destMarker.setLatLng(destLatLng);
    }

    const originInput = document.getElementById("originInput");
    if (originInput) {
        originInput.value = startName;
    }
    const destInput = document.getElementById("destinationInput");
    if (destInput) {
        destInput.value = destName;
    }
    closeDestinationResults();
    closeOriginResults();
    requestRoute();
    return true;
}

/* ---- Route (OSRM) -------------------------------------------------- */

let routeLayer = null;      // the polyline currently drawn
let routeAbort = null;      // cancels a stale in-flight route request
let routeDistanceKm = null;
let routeDurationSec = null;

function updateRouteSummary(text) {
    const summary = document.getElementById("routeSummary");
    if (!summary) {
        return;
    }
    summary.innerHTML = text;
    summary.classList.remove("d-none");
}

function hideRouteSummary() {
    const summary = document.getElementById("routeSummary");
    if (summary) {
        summary.innerHTML = "";
        summary.classList.add("d-none");
    }
}

function setRouteLoading(isLoading) {
    updateRouteSummary(
        isLoading
            ? `<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Calculating route…`
            : ""
    );
}

function showResetRoute(visible) {
    const btn = document.getElementById("resetRouteBtn");
    if (btn) {
        btn.classList.toggle("d-none", !visible);
    }
}

function formatRouteSummary() {
    const minutes = Math.round(routeDurationSec / 60);
    const km = routeDistanceKm.toFixed(1);
    return (
        `<div class="route-stats">` +
        `<div class="route-stat"><span>Route Distance</span>` +
        `<strong>${km} km</strong></div>` +
        `<div class="route-stat"><span>Estimated Travel Time</span>` +
        `<strong>${minutes} min</strong></div>` +
        `</div>`
    );
}

function drawRoute(coords, distanceMeters, durationSeconds) {
    if (!map) {
        return;
    }
    if (routeLayer) {
        map.removeLayer(routeLayer);
    }
    routeLayer = L.polyline(coords, {
        color: "#1a5fb4",
        weight: 5,
        opacity: 0.85,
        lineCap: "round",
        lineJoin: "round",
    }).addTo(map);

    routeDistanceKm = distanceMeters / 1000;
    routeDurationSec = durationSeconds;
    updateRouteData();

    // Bridge to the fare engine: feed the road distance into the form.
    const distanceInput = document.getElementById("distance");
    if (distanceInput) {
        distanceInput.value = routeDistanceKm.toFixed(2);
        // Let the calculator's live preview react to the routed distance.
        distanceInput.dispatchEvent(new Event("input", { bubbles: true }));
    }

    updateRouteSummary(formatRouteSummary());
    showResetRoute(true);
    map.fitBounds(routeLayer.getBounds(), { padding: [40, 40], maxZoom: 16 });
}

/* Route metadata bridge to the fare engine. Exposed so calculator.js can
 * include it in the POST /api/calculate-fare payload. Only set once a real
 * route has been computed (duration present). */
function updateRouteData() {
    if (startLatLng && destLatLng && routeDurationSec != null) {
        window.FareCalRouteData = {
            origin_name: startName,
            destination_name: destName,
            origin_latitude: startLatLng.lat,
            origin_longitude: startLatLng.lng,
            destination_latitude: destLatLng.lat,
            destination_longitude: destLatLng.lng,
            estimated_duration: Math.round(routeDurationSec),
        };
    } else {
        window.FareCalRouteData = null;
    }
}

/* Drop a stale polyline and its distance value when a new route attempt fails,
 * so a manually-entered distance is never paired with outdated route data. */
function clearStaleRoute() {
    if (routeLayer) {
        map.removeLayer(routeLayer);
        routeLayer = null;
    }
    routeDistanceKm = null;
    routeDurationSec = null;
    const distanceInput = document.getElementById("distance");
    if (distanceInput) {
        distanceInput.value = "";
        distanceInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
    updateRouteData();
}

async function requestRoute() {
    if (!map) {
        return;
    }
    if (!startLatLng || !destLatLng) {
        showResetRoute(false);
        hideRouteSummary();
        return;
    }

    let gapMeters;
    try {
        gapMeters = startLatLng.distanceTo(destLatLng);
    } catch (error) {
        showResetRoute(true);
        updateRouteSummary("Unable to calculate the route. Please check your starting point and destination.");
        clearStaleRoute();
        return;
    }
    if (gapMeters < 50) {
        showResetRoute(true);
        updateRouteSummary("Starting point and destination are too close to calculate a route.");
        clearStaleRoute();
        return;
    }

    // Cancel any still-pending request so stale routes never win.
    if (routeAbort) {
        routeAbort.abort();
    }
    routeAbort = new AbortController();
    setRouteLoading(true);

    const url =
        `${OSRM_URL}/${startLatLng.lng},${startLatLng.lat};` +
        `${destLatLng.lng},${destLatLng.lat}` +
        `?overview=full&geometries=geojson&alternatives=false&steps=false`;

    try {
        const response = await fetch(url, { signal: routeAbort.signal });
        if (!response.ok) {
            throw new Error(`Routing request failed (${response.status})`);
        }
        const data = await response.json();

        if (data.code !== "Ok" || !data.routes || data.routes.length === 0) {
            showResetRoute(true);
            updateRouteSummary("No road route found between these points. Try moving the starting point or destination.");
            clearStaleRoute();
            return;
        }

        const route = data.routes[0];
        // OSRM returns GeoJSON [lon, lat]; Leaflet needs [lat, lng].
        const coords = route.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
        drawRoute(coords, route.distance, route.duration);
    } catch (error) {
        if (error && error.name === "AbortError") {
            return;
        }
        showResetRoute(true);
        updateRouteSummary("The routing service is currently unavailable. Please try again later.");
        clearStaleRoute();
    } finally {
        // If a real summary (distance or error) did not replace the loading text, clear it.
        const summary = document.getElementById("routeSummary");
        if (summary && summary.textContent.includes("Calculating route")) {
            hideRouteSummary();
        }
    }
}

function resetRoute() {
    if (routeAbort) {
        routeAbort.abort();
        routeAbort = null;
    }
    if (startMarker) {
        map.removeLayer(startMarker);
        startMarker = null;
    }
    if (destMarker) {
        map.removeLayer(destMarker);
        destMarker = null;
    }
    if (routeLayer) {
        map.removeLayer(routeLayer);
        routeLayer = null;
    }
    startLatLng = null;
    startName = null;
    destLatLng = null;
    destName = null;
    routeDistanceKm = null;
    routeDurationSec = null;
    window.FareCalRouteData = null;

    ["originInput", "destinationInput", "distance"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) {
            el.value = "";
        }
    });

    const distanceInput = document.getElementById("distance");
    if (distanceInput) {
        distanceInput.dispatchEvent(new Event("input", { bubbles: true }));
    }

    hideRouteSummary();
    showResetRoute(false);
    clearAlert();
}

/* Restore a saved route from the query string (?origin_latitude=…&destination_latitude=…).
 * Used by the History page's "View on map" link so the calculator reopens with
 * the road route drawn. Silently does nothing when the coordinates are missing
 * or invalid (plain page load). */
function restoreRouteFromParams() {
    if (!map) {
        return;
    }
    const params = new URLSearchParams(window.location.search);

    const toCoord = (name, min, max) => {
        const raw = params.get(name);
        if (raw === null || raw === "") {
            return null;
        }
        const value = Number(raw);
        if (!Number.isFinite(value) || value < min || value > max) {
            return null;
        }
        return value;
    };

    const originLat = toCoord("origin_latitude", -90, 90);
    const originLng = toCoord("origin_longitude", -180, 180);
    const destLat = toCoord("destination_latitude", -90, 90);
    const destLng = toCoord("destination_longitude", -180, 180);

    if (originLat === null || originLng === null || destLat === null || destLng === null) {
        return;
    }

    const originName = params.get("origin_name") || "Start";
    const destName = params.get("destination_name") || "Destination";

    setStartPoint(L.latLng(originLat, originLng), originName);
    // requestRoute() runs automatically once the destination is set.
    setDestinationPoint(L.latLng(destLat, destLng), destName, destName);
}

/* ---- Page setup --------------------------------------------------- */

document.addEventListener("DOMContentLoaded", () => {
    const container = document.getElementById("map");
    if (!container || typeof L === "undefined") {
        return;
    }

    map = L.map(container, {
        center: DEFAULT_CENTER,
        zoom: DEFAULT_ZOOM,
    });

    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);

    // Manual starting point: tap anywhere on the map.
    map.on("click", (event) => {
        setStartPoint(event.latlng, "Selected point");
        showAlert("Starting point set to the selected location.", "success");
    });

    // GPS starting point: only when the user clicks the button.
    const locateBtn = document.getElementById("locateBtn");
    if (locateBtn) {
        locateBtn.addEventListener("click", useCurrentLocation);
    }

    // Destination search: debounced while typing, immediate on Enter / Search button.
    const destInput = document.getElementById("destinationInput");
    if (destInput) {
        destInput.addEventListener("input", scheduleDestSearch);
        destInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                clearTimeout(destSearchTimer);
                searchDestination();
            } else if (event.key === "Escape") {
                closeDestinationResults();
            }
        });
    }

    const destSearchBtn = document.getElementById("destinationSearchBtn");
    if (destSearchBtn) {
        destSearchBtn.addEventListener("click", () => {
            clearTimeout(destSearchTimer);
            searchDestination();
        });
    }

    const resetRouteBtn = document.getElementById("resetRouteBtn");
    if (resetRouteBtn) {
        resetRouteBtn.addEventListener("click", resetRoute);
    }

    // Manual starting point search (geocoding).
    const originInput = document.getElementById("originInput");
    if (originInput) {
        originInput.addEventListener("input", scheduleOriginSearch);
        originInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                clearTimeout(originSearchTimer);
                searchOrigin();
            } else if (event.key === "Escape") {
                closeOriginResults();
            }
        });
    }

    // Swap locations button.
    const swapBtn = document.getElementById("swapLocationsBtn");
    if (swapBtn) {
        swapBtn.addEventListener("click", swapLocations);
    }

    // Dismiss search dropdowns when clicking outside.
    document.addEventListener("click", (event) => {
        const originWrap = document.getElementById("originWrap");
        if (originWrap && !originWrap.contains(event.target)) {
            closeOriginResults();
        }
        const destWrap = document.getElementById("destinationWrap");
        if (destWrap && !destWrap.contains(event.target)) {
            closeDestinationResults();
        }
    });

    // Restore a saved route when arriving from the History page.
    restoreRouteFromParams();

    window.FareCalMap = map;
    window.FareCalSwap = swapLocations;
});
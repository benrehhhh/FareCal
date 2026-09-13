/* =====================================================================
 * FareCal — public fare calculator
 * Loads transportation + passenger options from the API, then posts the
 * user's selection to POST /api/calculate-fare and renders the breakdown.
 * The calculation itself runs inside the "Calculate Your Fare" modal
 * (STEP 2); the main page stays focused on route planning.
 * ===================================================================== */

const API = {
    transportTypes: "/api/transport-types",
    passengerTypes: "/api/passenger-types",
    calculateFare: "/api/calculate-fare",
    farePreview: "/api/fare-preview",
    routes: "/api/routes",
    rate: (transportId) => `/api/transport-types/${transportId}/rate`,
};

const currency = new Intl.NumberFormat("en-PH", {
    style: "currency",
    currency: "PHP",
});

function setLoading(isLoading) {
    const btn = document.getElementById("calculateBtn");
    btn.disabled = isLoading;
    document.getElementById("calcSpinner").classList.toggle("d-none", !isLoading);
    document.getElementById("calcBtnText").textContent = isLoading ? "Calculating…" : "Calculate Fare";
}

function setResultText(id, text) {
    document.getElementById(id).textContent = text;
}

function showResult(calc) {
    setResultText("resultTransport", calc.transport_type);
    setResultText("resultDistance", `${Number(calc.distance_km).toFixed(2)} km`);
    setResultText("resultPassenger", calc.passenger_type);
    setResultText(
        "resultRoute",
        calc.origin_name && calc.destination_name
            ? `${calc.origin_name} → ${calc.destination_name}`
            : "—"
    );
    setResultText("resultRegularFare", currency.format(calc.regular_fare));
    setResultText("resultDiscountRate", `${Number(calc.discount_percentage).toFixed(0)}%`);
    setResultText("resultDiscountAmount", currency.format(calc.discount_amount));
    setResultText("resultFinalFare", currency.format(calc.final_fare));

    // The total-to-pay readout appears once a fare is calculated; clicking it
    // opens the full Fare Breakdown modal.
    const totalBox = document.getElementById("totalFareBox");
    if (totalBox) {
        document.getElementById("totalFareAmount").textContent = currency.format(calc.final_fare);
        totalBox.classList.remove("d-none");
    }

    // Notes: minimum / maximum fare applied.
    const notes = [];
    if (calc.minimum_fare_applied && calc.minimum_fare !== null) {
        notes.push(
            `<span class="badge text-bg-info">The minimum fare of ${currency.format(calc.minimum_fare)} was applied for this distance.</span>`
        );
    }
    if (calc.maximum_fare_applied && calc.maximum_fare !== null) {
        notes.push(
            `<span class="badge text-bg-warning">The fare was capped at the maximum of ${currency.format(calc.maximum_fare)}.</span>`
        );
    }
    document.getElementById("resultNotes").innerHTML = notes.join(" ");

    // Source / reference of the fare rule in use.
    const source = calc.source_reference
        ? `Fare rule reference: ${calc.source_reference}`
        : "";
    document.getElementById("resultSource").textContent = source;
}

let breakdownModalInstance = null;

function revealBreakdown() {
    if (breakdownModalInstance) {
        breakdownModalInstance.show();
    }
}

/* ---- Modal helper alerts (Bootstrap-dismissible) ------------------- */

function showModalAlert(message, type) {
    clearModalAlert();
    const box = document.getElementById("modalAlert");
    box.innerHTML =
        `<div class="alert alert-${type} alert-dismissible fade show" role="alert">` +
        `${message}` +
        `<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>` +
        `</div>`;
}

function clearModalAlert() {
    document.getElementById("modalAlert").innerHTML = "";
}

async function fetchJson(url) {
    const response = await fetch(url);
    const data = await response.json();
    if (!data.success) {
        throw new Error(data.message || "Request failed.");
    }
    return data.result;
}

function populateSelect(select, items, discountKey) {
    select.innerHTML = "";
    items.forEach((item) => {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = item.name;
        if (discountKey && item[discountKey] !== undefined) {
            option.dataset.discount = item[discountKey];
        }
        select.appendChild(option);
    });
}

function updateDiscountHint() {
    const select = document.getElementById("passengerType");
    const selected = select.options[select.selectedIndex];
    const hint = document.getElementById("discountHint");
    if (!selected) {
        hint.textContent = "";
        return;
    }
    const discount = Number(selected.dataset.discount || 0);
    hint.textContent =
        discount > 0
            ? `This passenger type qualifies for a ${discount}% discount.`
            : "No discount applies for this passenger type.";
}

/* =====================================================================
 * Distance gating
 * "Calculate Your Fare" stays disabled until a valid distance exists.
 * The distance comes from the OSRM route automatically; the field lives
 * inside the modal and may be edited as a fallback.
 * ===================================================================== */

function updateDistanceUi() {
    const input = document.getElementById("distance");
    const raw = input.value;
    const value = Number(raw);
    const hasDistance = raw !== "" && Number.isFinite(value) && value > 0;

    const calculateBtn = document.getElementById("calculateBtn");
    calculateBtn.disabled = !hasDistance;

    const openBtn = document.getElementById("openCalculateBtn");
    if (openBtn) {
        openBtn.disabled = !hasDistance;
    }

    const hint = document.getElementById("distanceHint");
    hint.textContent = hasDistance
        ? "Distance is auto-filled from your route. You can adjust it if needed."
        : "Please select a starting point and destination first to calculate a route.";
}

/* =====================================================================
 * Dynamic Rate Panel + live preview
 * Shows the current active fare structure for the selected transport and
 * an interactive distance-based estimate (computed server-side, unsaved).
 * ===================================================================== */

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value || "";
    return div.innerHTML;
}

const ROUNDING_LABELS = {
    round_up_025: "Rounded up to the next ₱0.25",
    round_up_1: "Rounded up to the next whole peso",
    round_2: "Standard two-decimal rounding",
};

function rateSentence(rate) {
    if (rate.fare_method === "base_succeeding") {
        let text =
            `${currency.format(rate.base_fare)} for the first ` +
            `${Number(rate.base_distance).toFixed(0)} km`;
        if (rate.succeeding_rate != null) {
            text += `, then ${currency.format(rate.succeeding_rate)} per succeeding km`;
        }
        return text;
    }
    let text = rate.per_km_rate != null ? `${currency.format(rate.per_km_rate)} per kilometer` : "";
    if (rate.minimum_fare != null) {
        text += ` (minimum ${currency.format(rate.minimum_fare)})`;
    }
    return text;
}

function formatRateDate(iso) {
    if (!iso) {
        return "—";
    }
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) {
        return iso;
    }
    return date.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
    });
}

function renderRatePanel(rate) {
    const body = document.getElementById("ratePanelBody");
    const rows = [`<p class="mb-1 fw-bold">${escapeHtml(rate.transport_name)}</p>`];
    if (rate.transport_description) {
        rows.push(
            `<p class="text-muted mb-2 small">${escapeHtml(rate.transport_description)}</p>`
        );
    }
    rows.push(`<p class="mb-2">${escapeHtml(rateSentence(rate))}</p>`);

    const defs = [];
    const addRow = (label, value) =>
        defs.push(`<dt class="col-5">${label}</dt><dd class="col-7">${value}</dd>`);

    if (rate.fare_method === "base_succeeding") {
        addRow("Base distance", `${Number(rate.base_distance).toFixed(0)} km`);
        addRow("Base fare", currency.format(rate.base_fare));
        if (rate.succeeding_rate != null) {
            addRow("Succeeding rate", `${currency.format(rate.succeeding_rate)}/km`);
        }
    } else if (rate.per_km_rate != null) {
        addRow("Per kilometer", currency.format(rate.per_km_rate));
    }
    if (rate.minimum_fare != null) {
        addRow("Minimum fare", currency.format(rate.minimum_fare));
    }
    if (rate.maximum_fare != null) {
        addRow("Maximum fare", currency.format(rate.maximum_fare));
    }
    addRow("Rounding", ROUNDING_LABELS[rate.rounding_rule] || rate.rounding_rule);
    addRow("Effective", formatRateDate(rate.effective_date));
    if (rate.source_reference) {
        addRow("Reference", escapeHtml(rate.source_reference));
    }

    rows.push(`<dl class="row small mb-0">${defs.join("")}</dl>`);
    body.innerHTML = rows.join("");
}

async function refreshRatePanel() {
    const body = document.getElementById("ratePanelBody");
    const transportId = document.getElementById("transportType").value;
    if (!transportId) {
        body.textContent =
            "Select a transportation type to see its current fare structure.";
        setPreview("");
        return;
    }
    body.innerHTML =
        `<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>` +
        `Loading rate…`;
    try {
        renderRatePanel(await fetchJson(API.rate(transportId)));
    } catch (error) {
        body.textContent =
            (error && error.message) ||
            "The current fare rate is temporarily unavailable.";
    }
}

/* ---- Live rate preview (debounced, unsaved) ------------------------ */

let previewTimer = null;
let previewAbort = null;

function setPreview(html) {
    const el = document.getElementById("ratePreview");
    if (!el) {
        return;
    }
    el.classList.toggle("d-none", !html);
    el.innerHTML = html || "";
}

function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(runPreview, 300);
}

async function runPreview() {
    const transportId = document.getElementById("transportType").value;
    const passengerId = document.getElementById("passengerType").value;
    const raw = document.getElementById("distance").value;
    const distance = Number(raw);

    if (!transportId || !passengerId || raw === "" || !Number.isFinite(distance) || distance <= 0) {
        setPreview("");
        return;
    }

    if (previewAbort) {
        previewAbort.abort();
    }
    previewAbort = new AbortController();
    try {
        const response = await fetch(API.farePreview, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                transport_type_id: Number(transportId),
                passenger_type_id: Number(passengerId),
                distance,
            }),
            signal: previewAbort.signal,
        });
        const data = await response.json();
        if (!data.success) {
            setPreview("");
            return;
        }
        const calc = data.result;
        let label = `Estimated fare for <strong>${Number(calc.distance_km).toFixed(2)} km</strong>: `;
        label += currency.format(calc.final_fare);
        if (calc.discount_percentage > 0) {
            label +=
                ` <span class="text-muted">(regular ${currency.format(calc.regular_fare)} ` +
                `with ${Number(calc.discount_percentage).toFixed(0)}% discount)</span>`;
        }
        setPreview(label);
    } catch (error) {
        if (error && error.name === "AbortError") {
            return;
        }
        setPreview("");
    } finally {
        previewAbort = null;
    }
}

const routeData = new Map();

function populateRoutes(select, routes) {
    select.innerHTML = "";
    if (routes.length === 0) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No saved routes yet.";
        option.disabled = true;
        option.selected = true;
        select.appendChild(option);
        select.disabled = true;
        return;
    }
    select.disabled = false;
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Choose a saved route to auto-fill…";
    placeholder.selected = true;
    select.appendChild(placeholder);

    routeData.clear();
    routes.forEach((route) => {
        const option = document.createElement("option");
        option.value = route.id;
        option.textContent =
            `${route.origin} → ${route.destination} ` +
            `(${Number(route.distance_km).toFixed(2)} km)`;
        select.appendChild(option);
        routeData.set(String(route.id), route);
    });
}

function applyRoute(routeId) {
    const route = routeData.get(routeId);
    if (!route) {
        return;
    }
    const transportSelect = document.getElementById("transportType");
    const transportOption = Array.from(transportSelect.options).find(
        (option) => option.value === String(route.transport_type_id)
    );
    if (!transportOption) {
        showModalAlert("The transportation type for this route is not available.", "warning");
        return;
    }
    transportSelect.value = String(route.transport_type_id);
    const distanceInput = document.getElementById("distance");
    distanceInput.value = Number(route.distance_km).toFixed(2);
    distanceInput.dispatchEvent(new Event("input", { bubbles: true }));
    refreshRatePanel();
    schedulePreview();
}

async function loadOptions() {
    try {
        const [transportTypes, passengerTypes, routes] = await Promise.all([
            fetchJson(API.transportTypes),
            fetchJson(API.passengerTypes),
            fetchJson(API.routes),
        ]);

        populateSelect(document.getElementById("transportType"), transportTypes);
        populateSelect(
            document.getElementById("passengerType"),
            passengerTypes,
            "discount_percentage"
        );
        populateRoutes(document.getElementById("routePreset"), routes);
        updateDiscountHint();
        applyUrlParams();
        updateDistanceUi();
        refreshRatePanel();
        schedulePreview();
    } catch (error) {
        showAlert(
            "Unable to load the fare options. Please refresh the page.",
            "danger"
        );
    }
}

function applyUrlParams() {
    // Prefill the form from ?transport_type_id=&passenger_type_id=&distance=
    // (used by the "Recalculate" links on History / Dashboard).
    const params = new URLSearchParams(window.location.search);
    const transportId = params.get("transport_type_id");
    const passengerId = params.get("passenger_type_id");
    const distance = params.get("distance");

    const transportSelect = document.getElementById("transportType");
    if (transportId && Array.from(transportSelect.options).some(
        (option) => option.value === transportId
    )) {
        transportSelect.value = transportId;
    }

    const passengerSelect = document.getElementById("passengerType");
    if (passengerId && Array.from(passengerSelect.options).some(
        (option) => option.value === passengerId
    )) {
        passengerSelect.value = passengerId;
        updateDiscountHint();
    }

    if (distance) {
        const parsed = Number(distance);
        if (Number.isFinite(parsed) && parsed > 0 && parsed <= 500) {
            document.getElementById("distance").value = parsed.toFixed(2);
        }
    }

    if (distance || transportId) {
        clearModalAlert();
    }
}

document.addEventListener("DOMContentLoaded", () => {
    loadOptions();

    const calculateModalEl = document.getElementById("calculateFareModal");
    const calculateModal = calculateModalEl ? new bootstrap.Modal(calculateModalEl) : null;
    const breakdownModalEl = document.getElementById("fareBreakdownModal");
    breakdownModalInstance = breakdownModalEl ? new bootstrap.Modal(breakdownModalEl) : null;

    // STEP 1: opening the modal requires a valid route distance first.
    document.getElementById("openCalculateBtn").addEventListener("click", () => {
        clearModalAlert();
        if (calculateModal) {
            calculateModal.show();
        }
    });

    const totalFareBox = document.getElementById("totalFareBox");
    if (totalFareBox) {
        totalFareBox.addEventListener("click", revealBreakdown);
    }

    document.getElementById("routePreset").addEventListener("change", (event) => {
        applyRoute(event.target.value);
        updateDistanceUi();
    });

    document.getElementById("transportType").addEventListener("change", () => {
        refreshRatePanel();
        schedulePreview();
    });

    document.getElementById("distance").addEventListener("input", () => {
        updateDistanceUi();
        schedulePreview();
    });

    document.getElementById("passengerType").addEventListener("change", () => {
        updateDiscountHint();
        schedulePreview();
    });

    document.getElementById("modalFareForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        clearModalAlert();

        const transportId = document.getElementById("transportType").value;
        const passengerId = document.getElementById("passengerType").value;
        const distance = Number(document.getElementById("distance").value);

        if (!transportId || !passengerId || !Number.isFinite(distance) || distance <= 0) {
            showModalAlert(
                "Please select a transportation type and a passenger type, and enter a valid distance.",
                "warning"
            );
            return;
        }

        setLoading(true);
        try {
            const body = {
                transport_type_id: Number(transportId),
                passenger_type_id: Number(passengerId),
                distance,
            };
            // Attach map route metadata when the fare comes from a road route.
            if (window.FareCalRouteData) {
                Object.assign(body, window.FareCalRouteData);
            }
            const response = await fetch(API.calculateFare, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            const data = await response.json();

            if (!data.success) {
                showModalAlert(
                    data.message ||
                    "No active fare rate is available for the selected transportation type.",
                    "danger"
                );
                return;
            }
            showResult(data.result);
            if (calculateModal) {
                calculateModal.hide();
            }
            showAlert(
                "Fare calculated. Scroll down and choose “View Fare Breakdown” to see the full estimate.",
                "success"
            );
        } catch (error) {
            showModalAlert(
                "An unexpected error occurred while calculating the fare. Please try again.",
                "danger"
            );
        } finally {
            setLoading(false);
        }
    });
});
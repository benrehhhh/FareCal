/* =====================================================================
 * FareCal — public fare calculator
 * Loads transportation + passenger options from the API, then posts the
 * user's selection to POST /api/calculate-fare and renders the breakdown.
 * ===================================================================== */

const API = {
    transportTypes: "/api/transport-types",
    passengerTypes: "/api/passenger-types",
    calculateFare: "/api/calculate-fare",
    routes: "/api/routes",
};

const currency = new Intl.NumberFormat("en-PH", {
    style: "currency",
    currency: "PHP",
});

function showAlert(message, type) {
    const box = document.getElementById("calculatorAlert");
    box.innerHTML =
        `<div class="alert alert-${type} alert-dismissible fade show" role="alert">` +
        `${message}` +
        `<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>` +
        `</div>`;
}

function clearAlert() {
    document.getElementById("calculatorAlert").innerHTML = "";
}

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
    document.getElementById("resultPlaceholder").classList.add("d-none");
    const panel = document.getElementById("resultPanel");
    panel.classList.remove("d-none");

    setResultText("resultTransport", calc.transport_type);
    setResultText("resultDistance", `${Number(calc.distance_km).toFixed(2)} km`);
    setResultText("resultPassenger", calc.passenger_type);
    setResultText("resultRegularFare", currency.format(calc.regular_fare));
    setResultText("resultDiscountRate", `${Number(calc.discount_percentage).toFixed(0)}%`);
    setResultText("resultDiscountAmount", currency.format(calc.discount_amount));
    setResultText("resultFinalFare", currency.format(calc.final_fare));

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
        showAlert("The transportation type for this route is not available.", "warning");
        return;
    }
    transportSelect.value = String(route.transport_type_id);
    document.getElementById("distance").value = Number(route.distance_km).toFixed(2);
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
    } catch (error) {
        showAlert(
            "Unable to load the fare options. Please refresh the page.",
            "danger"
        );
    }
}

document.addEventListener("DOMContentLoaded", () => {
    loadOptions();

    document.getElementById("routePreset").addEventListener("change", (event) => {
        applyRoute(event.target.value);
    });

    document.getElementById("passengerType").addEventListener("change", updateDiscountHint);

    document.getElementById("fareForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        clearAlert();

        const transportId = document.getElementById("transportType").value;
        const passengerId = document.getElementById("passengerType").value;
        const distance = Number(document.getElementById("distance").value);

        if (!transportId || !passengerId || !Number.isFinite(distance) || distance <= 0) {
            showAlert(
                "Please select a transportation type and a passenger type, and enter a distance greater than zero.",
                "warning"
            );
            return;
        }

        setLoading(true);
        try {
            const response = await fetch(API.calculateFare, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    transport_type_id: Number(transportId),
                    passenger_type_id: Number(passengerId),
                    distance,
                }),
            });
            const data = await response.json();

            if (!data.success) {
                showAlert(data.message || "Unable to calculate the fare. Please try again.", "danger");
                return;
            }
            showResult(data.result);
        } catch (error) {
            showAlert("An unexpected error occurred. Please try again.", "danger");
        } finally {
            setLoading(false);
        }
    });
});
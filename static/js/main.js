/* FareCal site-wide JS helpers */

/* Page-level alerts auto-close after a short delay. Alerts shown inside a
 * modal are exempt so they don't vanish mid-interaction. */
const ALERT_AUTO_DISMISS_MS = 6000;

function autoDismissAlert(alertEl, delay = ALERT_AUTO_DISMISS_MS) {
    if (!alertEl || alertEl.closest(".modal")) {
        return;
    }
    if (!window.bootstrap || !bootstrap.Alert) {
        return;
    }
    window.setTimeout(() => {
        if (alertEl.isConnected) {
            try {
                bootstrap.Alert.getOrCreateInstance(alertEl).close();
            } catch (_) {
                /* ignore: alert was already removed */
            }
        }
    }, delay);
}

/* Show a Bootstrap dismissible alert in the shared #calculatorAlert box. */
function showAlert(message, type = "danger") {
    const box = document.getElementById("calculatorAlert");
    if (!box) {
        return;
    }
    box.innerHTML =
        `<div class="alert alert-${type} alert-dismissible fade show" role="alert">` +
        `${message}` +
        `<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>` +
        `</div>`;
    autoDismissAlert(box.firstElementChild);
}

/* Remove any alert currently shown in the shared alert box. */
function clearAlert() {
    const box = document.getElementById("calculatorAlert");
    if (box) {
        box.innerHTML = "";
    }
}

document.addEventListener("DOMContentLoaded", () => {
    // Server-rendered flashes also auto-dismiss (see _flashes.html).
    document.querySelectorAll(".alert-dismissible").forEach(autoDismissAlert);

    // Confirm before submitting any form that carries a data-confirm message.
    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            const message = form.dataset.confirm || "Are you sure?";
            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });
});
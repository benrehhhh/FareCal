/* FareCal site-wide JS helpers */

document.addEventListener("DOMContentLoaded", () => {
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
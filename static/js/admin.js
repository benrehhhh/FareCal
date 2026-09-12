/* =====================================================================
 * FareCal admin helpers
 * - Confirms destructive/status-changing actions before submitting
 * - Provides a live client-side filter for the users table
 * ===================================================================== */

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

    // Live filter for the searchable users table.
    const userSearch = document.getElementById("userSearch");
    const usersTable = document.getElementById("usersTable");
    if (userSearch && usersTable) {
        userSearch.addEventListener("input", () => {
            const term = userSearch.value.toLowerCase();
            usersTable.querySelectorAll("tbody tr").forEach((row) => {
                row.style.display = row.textContent.toLowerCase().includes(term)
                    ? ""
                    : "none";
            });
        });
    }
});
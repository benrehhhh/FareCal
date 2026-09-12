/* =====================================================================
 * FareCal admin helpers
 * - Provides a live client-side filter for the users table
 * (data-confirm handling lives in static/js/main.js)
 * ===================================================================== */

document.addEventListener("DOMContentLoaded", () => {
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
/*jslint browser */
/**
 * Dark-mode tri-toggle: light → system → dark.
 * IIFE with document-level delegation so it survives HTMX body swaps.
 * Reads/writes localStorage key "co-color-scheme".
 */
(function () {
    "use strict";

    var STORAGE_KEY = "co-color-scheme";

    /**
     * Apply a theme value to <html>.
     * @param {string|null} value - "light", "dark", or null (system).
     */
    function applyTheme(value) {
        document.documentElement.classList.remove("light", "dark");
        if (value === "dark") {
            document.documentElement.classList.add("dark");
        } else if (value === "light") {
            document.documentElement.classList.add("light");
        }
        // null → system fallback via @media prefers-color-scheme (no class needed)
    }

    /**
     * Cycle the stored value: null → "light" → "dark" → null.
     * @param {string|null} current
     * @returns {string|null}
     */
    function nextTheme(current) {
        if (current === null) { return "light"; }
        if (current === "light") { return "dark"; }
        return null;
    }

    /**
     * Handle a click on any [data-theme-toggle] button.
     * @param {Event} ev
     */
    function handleToggleClick(ev) {
        /** @type {HTMLElement|null} */
        var btn = /** @type {HTMLElement} */ (ev.target).closest("[data-theme-toggle]");
        if (!btn) { return; }
        var current = localStorage.getItem(STORAGE_KEY);
        var next = nextTheme(current);
        if (next === null) {
            localStorage.removeItem(STORAGE_KEY);
        } else {
            localStorage.setItem(STORAGE_KEY, next);
        }
        applyTheme(next);
    }

    document.addEventListener("click", handleToggleClick);

    // Apply on first load (in case the FOUC inline script didn't run)
    applyTheme(localStorage.getItem(STORAGE_KEY));
}());

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
     * Map a theme value to its display icon.
     * @param {string|null} value - "light", "dark", or null (system).
     * @returns {string}
     */
    function themeIcon(value) {
        if (value === "light") { return "☀"; }
        if (value === "dark")  { return "☾"; }
        return "◐"; // system fallback
    }

    /**
     * Update textContent and aria-label on all [data-theme-toggle] buttons.
     * @param {string|null} value
     */
    function updateToggleButtons(value) {
        var icon = themeIcon(value);
        var label = value === null ? "Colour scheme: system" : "Colour scheme: " + value;
        var buttons = document.querySelectorAll("[data-theme-toggle]");
        var i;
        for (i = 0; i < buttons.length; i += 1) {
            buttons[i].textContent = icon;
            buttons[i].setAttribute("aria-label", label);
        }
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
        updateToggleButtons(next);
    }

    document.addEventListener("click", handleToggleClick);

    // Apply on first load (in case the FOUC inline script didn't run)
    var initial = localStorage.getItem(STORAGE_KEY);
    applyTheme(initial);
    updateToggleButtons(initial);
}());

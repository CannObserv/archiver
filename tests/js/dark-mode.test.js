/*jslint browser */
/**
 * Tests for dark-mode theme cycling logic.
 * Exercises the nextTheme and applyTheme behaviour in isolation.
 */
import { describe, it, expect, beforeEach } from "vitest";

// Re-implement the pure logic under test (extracted from dark-mode.js)
function nextTheme(current) {
    if (current === null) { return "light"; }
    if (current === "light") { return "dark"; }
    return null;
}

function applyTheme(htmlEl, value) {
    htmlEl.classList.remove("light", "dark");
    if (value === "dark") { htmlEl.classList.add("dark"); }
    else if (value === "light") { htmlEl.classList.add("light"); }
}

describe("nextTheme", function () {
    it("null → light", function () {
        expect(nextTheme(null)).toBe("light");
    });

    it("light → dark", function () {
        expect(nextTheme("light")).toBe("dark");
    });

    it("dark → null", function () {
        expect(nextTheme("dark")).toBeNull();
    });
});

describe("applyTheme", function () {
    let html;

    beforeEach(function () {
        html = { classList: { _classes: new Set(), add(c) { this._classes.add(c); }, remove(...cs) { cs.forEach(c => this._classes.delete(c)); }, contains(c) { return this._classes.has(c); } } };
    });

    it("sets dark class for 'dark'", function () {
        applyTheme(html, "dark");
        expect(html.classList.contains("dark")).toBe(true);
        expect(html.classList.contains("light")).toBe(false);
    });

    it("sets light class for 'light'", function () {
        applyTheme(html, "light");
        expect(html.classList.contains("light")).toBe(true);
        expect(html.classList.contains("dark")).toBe(false);
    });

    it("removes both classes for null (system)", function () {
        html.classList.add("dark");
        applyTheme(html, null);
        expect(html.classList.contains("dark")).toBe(false);
        expect(html.classList.contains("light")).toBe(false);
    });
});

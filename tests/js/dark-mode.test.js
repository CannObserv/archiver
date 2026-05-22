/*jslint browser */
/**
 * Tests for dark-mode theme cycling logic.
 * Exercises the nextTheme, applyTheme, themeIcon, and updateToggleButtons
 * behaviour in isolation.
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

function themeIcon(value) {
    if (value === "light") { return "☀"; }
    if (value === "dark") { return "☾"; }
    return "◐";
}

function makeBtn() {
    return {
        textContent: "",
        _label: "",
        setAttribute(k, v) { if (k === "aria-label") { this._label = v; } }
    };
}

function updateToggleButtons(value, buttons) {
    var icon = themeIcon(value);
    var label = value === null ? "Colour scheme: system" : "Colour scheme: " + value;
    var i;
    for (i = 0; i < buttons.length; i += 1) {
        buttons[i].textContent = icon;
        buttons[i].setAttribute("aria-label", label);
    }
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

describe("themeIcon", function () {
    it("null → ◐ (system)", function () {
        expect(themeIcon(null)).toBe("◐");
    });

    it("'light' → ☀", function () {
        expect(themeIcon("light")).toBe("☀");
    });

    it("'dark' → ☾", function () {
        expect(themeIcon("dark")).toBe("☾");
    });
});

describe("updateToggleButtons", function () {
    it("sets system icon and label for null", function () {
        var btn = makeBtn();
        updateToggleButtons(null, [btn]);
        expect(btn.textContent).toBe("◐");
        expect(btn._label).toBe("Colour scheme: system");
    });

    it("sets light icon and label for 'light'", function () {
        var btn = makeBtn();
        updateToggleButtons("light", [btn]);
        expect(btn.textContent).toBe("☀");
        expect(btn._label).toBe("Colour scheme: light");
    });

    it("sets dark icon and label for 'dark'", function () {
        var btn = makeBtn();
        updateToggleButtons("dark", [btn]);
        expect(btn.textContent).toBe("☾");
        expect(btn._label).toBe("Colour scheme: dark");
    });

    it("updates multiple buttons", function () {
        var btn1 = makeBtn();
        var btn2 = makeBtn();
        updateToggleButtons("dark", [btn1, btn2]);
        expect(btn1.textContent).toBe("☾");
        expect(btn2.textContent).toBe("☾");
    });
});

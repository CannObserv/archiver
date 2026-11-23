/*jslint browser */
/**
 * Tests for sidebar-drawer.js - the phone-width sidebar drawer (archiver#400).
 *
 * The CSS decides WHEN the sidebar is a drawer (under 640 px); this script only
 * keeps the toggle's `aria-expanded` and the drawer's `data-open` in step and
 * moves focus. So these tests run at happy-dom's default width: the behaviour
 * under test is width-independent, and the layout was measured in Chromium.
 */
import { describe, it, expect, beforeEach } from "vitest";

// Importing the module runs the IIFE once, attaching its document listeners.
import "../../src/dashboard/static/sidebar-drawer.js";

// The shape base.html renders: the toggle in the topbar, closed.
const CHROME = `
  <header class="topbar">
    <button type="button" data-sidebar-toggle aria-controls="sidebar"
            aria-expanded="false" aria-label="Menu">☰</button>
    <a href="/dashboard/" class="topbar__brand">Archiver</a>
  </header>
  <div class="admin-layout">
    <nav id="sidebar" class="sidebar" aria-label="Main navigation">
      <ul>
        <li class="sidebar__section-label">Registry</li>
        <li><a href="/dashboard/" class="sidebar__link">Home</a></li>
        <li><a href="/dashboard/domains/" class="sidebar__link">Domains</a></li>
      </ul>
    </nav>
    <main id="main-content"><input id="outside-input"><p id="outside">x</p></main>
  </div>`;

function el(sel) {
    return document.querySelector(sel);
}

function toggle() {
    return el("[data-sidebar-toggle]");
}

function drawer() {
    return el("#sidebar");
}

function isOpen() {
    return toggle().getAttribute("aria-expanded") === "true" && drawer().hasAttribute("data-open");
}

function isClosed() {
    return toggle().getAttribute("aria-expanded") === "false" && !drawer().hasAttribute("data-open");
}

function pressEscape(target) {
    const ev = new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    (target || document.activeElement || document.body).dispatchEvent(ev);
    return ev;
}

beforeEach(function () {
    document.body.innerHTML = CHROME;
});

describe("the toggle", function () {
    it("opens the drawer and moves focus to its first link", function () {
        toggle().click();

        expect(isOpen()).toBe(true);
        expect(document.activeElement).toBe(el(".sidebar__link"));
    });

    it("closes an open drawer", function () {
        toggle().click();
        toggle().click();

        expect(isClosed()).toBe(true);
    });

    it("answers a click on its own text, not only on the button box", function () {
        // The click target can be a descendant (an icon span); closest() covers it.
        toggle().innerHTML = "<span>☰</span>";
        toggle().firstChild.click();

        expect(isOpen()).toBe(true);
    });
});

describe("Escape", function () {
    it("closes the drawer and returns focus to the toggle", function () {
        toggle().click();
        const ev = pressEscape();

        expect(isClosed()).toBe(true);
        expect(document.activeElement).toBe(toggle());
        expect(ev.defaultPrevented).toBe(true);
    });

    it("leaves a closed drawer, and the focus elsewhere, alone", function () {
        const input = el("#outside-input");
        input.focus();
        const ev = pressEscape(input);

        expect(isClosed()).toBe(true);
        expect(document.activeElement).toBe(input);
        // Not consumed: other Escape handlers (a combobox, a modal) still see it.
        expect(ev.defaultPrevented).toBe(false);
    });
});

describe("leaving the drawer", function () {
    it("a click outside the drawer closes it", function () {
        toggle().click();
        el("#outside").click();

        expect(isClosed()).toBe(true);
    });

    it("the dismissing click is swallowed: the content under the tap never sees it", function () {
        // No scrim, so the tap that closes the drawer lands on whatever control
        // sits beside it - on a phone, a button or link the operator never aimed at.
        const outside = el("#outside");
        let reached = 0;
        outside.addEventListener("click", function () { reached += 1; });
        toggle().click();
        const ev = new window.MouseEvent("click", { bubbles: true, cancelable: true });
        outside.dispatchEvent(ev);

        expect(isClosed()).toBe(true);
        expect(reached).toBe(0);
        expect(ev.defaultPrevented).toBe(true);
    });

    it("a real tap - mousedown, focus, then click - is swallowed too", function () {
        // The order a browser fires: mousedown's default action moves focus,
        // which would close the drawer through focusin BEFORE the click, so the
        // click handler alone saw a closed drawer and let the tap through
        // (Chromium on 8001: New Item navigated).
        const target = el("#outside-input");
        let reached = 0;
        target.addEventListener("click", function () { reached += 1; });
        toggle().click();
        const down = new window.MouseEvent("mousedown", { bubbles: true, cancelable: true });
        target.dispatchEvent(down);
        if (!down.defaultPrevented) { target.focus(); }   // the browser's default action
        target.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));

        expect(down.defaultPrevented).toBe(true);
        expect(isClosed()).toBe(true);
        expect(reached).toBe(0);
    });

    it("a dismissing mousedown with no click (a drag) does not eat a later click", function () {
        const target = el("#outside");
        let reached = 0;
        target.addEventListener("click", function () { reached += 1; });
        toggle().click();
        target.dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true, cancelable: true }));
        // The pointer was released elsewhere: no click. The next interaction is new.
        target.dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true, cancelable: true }));
        target.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));

        expect(reached).toBe(1);
    });

    it("a click with the drawer closed reaches its target untouched", function () {
        const outside = el("#outside");
        let reached = 0;
        outside.addEventListener("click", function () { reached += 1; });
        const ev = new window.MouseEvent("click", { bubbles: true, cancelable: true });
        outside.dispatchEvent(ev);

        expect(reached).toBe(1);
        expect(ev.defaultPrevented).toBe(false);
    });

    it("a click on a drawer link is not swallowed", function () {
        const link = el(".sidebar__link");
        let reached = 0;
        link.addEventListener("click", function (e) { reached += 1; e.preventDefault(); });
        toggle().click();
        link.click();

        expect(reached).toBe(1);
    });

    it("a click inside the drawer, off a link, keeps it open", function () {
        toggle().click();
        el(".sidebar__section-label").click();

        expect(isOpen()).toBe(true);
    });

    it("focus moving past the drawer closes it, so Tab never lands under it", function () {
        toggle().click();
        el("#outside-input").focus();

        expect(isClosed()).toBe(true);
        expect(document.activeElement).toBe(el("#outside-input"));
    });

    it("focus moving within the drawer keeps it open", function () {
        toggle().click();
        document.querySelectorAll(".sidebar__link")[1].focus();

        expect(isOpen()).toBe(true);
    });
});

describe("a boosted navigation", function () {
    it("lands closed, and the new page's toggle still works", function () {
        // htmx 2 swaps a boosted response into the body's innerHTML, so the
        // chrome is replaced by the server's closed render; listeners on the
        // old toggle would be gone with it.
        toggle().click();
        document.body.innerHTML = CHROME;

        expect(isClosed()).toBe(true);
        toggle().click();
        expect(isOpen()).toBe(true);
    });

    it("leaves no state on <body> or <html>, which the swap keeps", function () {
        toggle().click();

        expect(document.body.getAttributeNames()).toEqual([]);
        expect(document.documentElement.className).toBe("");
    });
});

describe("a page without the chrome", function () {
    it("ignores clicks and Escape (the standalone error page has no sidebar)", function () {
        document.body.innerHTML = "<p id='x'>error</p>";

        expect(function () {
            el("#x").click();
            pressEscape(el("#x"));
        }).not.toThrow();
    });
});

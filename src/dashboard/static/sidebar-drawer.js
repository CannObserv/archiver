/*jslint browser */
/**
 * Sidebar drawer (archiver#400). Under 640 px `dashboard.css` turns `.sidebar`
 * into an off-canvas drawer behind the topbar's `[data-sidebar-toggle]`; this
 * keeps the toggle's `aria-expanded` and the drawer's `data-open` in step and
 * moves focus. At desktop width the toggle is `display: none` and the CSS
 * ignores `data-open`, so nothing here needs to know the viewport.
 *
 * IIFE with document-level delegation, so it survives boosted swaps. State
 * lives only on the toggle and the drawer, both inside `<body>`: htmx swaps a
 * boosted page into the body's innerHTML, so every navigation lands on the
 * server's closed render. Nothing is written to `<body>` or `<html>`, which the
 * swap would keep.
 */
(function () {
    "use strict";

    /**
     * The toggle and the drawer it controls, or null on a page without them.
     * @returns {{toggle: HTMLElement, drawer: HTMLElement}|null}
     */
    function parts() {
        var toggle = document.querySelector("[data-sidebar-toggle]");
        var drawer;
        if (!toggle) { return null; }
        drawer = document.getElementById(toggle.getAttribute("aria-controls"));
        if (!drawer) { return null; }
        return {toggle: toggle, drawer: drawer};
    }

    /**
     * @param {{toggle: HTMLElement}} p
     * @returns {boolean}
     */
    function isOpen(p) {
        return p.toggle.getAttribute("aria-expanded") === "true";
    }

    /**
     * Open the drawer and move focus to its first link, so the next Tab walks
     * the navigation rather than the rest of the topbar.
     * @param {{toggle: HTMLElement, drawer: HTMLElement}} p
     */
    function openDrawer(p) {
        var first;
        p.toggle.setAttribute("aria-expanded", "true");
        p.drawer.setAttribute("data-open", "");
        first = p.drawer.querySelector("a[href]");
        if (first) { first.focus(); }
    }

    /**
     * Close the drawer; with returnFocus, put focus back on the toggle.
     * @param {{toggle: HTMLElement, drawer: HTMLElement}} p
     * @param {boolean} returnFocus
     */
    function closeDrawer(p, returnFocus) {
        p.toggle.setAttribute("aria-expanded", "false");
        p.drawer.removeAttribute("data-open");
        if (returnFocus) { p.toggle.focus(); }
    }

    document.addEventListener("click", function (ev) {
        var p = parts();
        var target = /** @type {Node} */ (ev.target);
        if (!p) { return; }
        if (p.toggle.contains(target)) {
            if (isOpen(p)) {
                closeDrawer(p, false);
            } else {
                openDrawer(p);
            }
            return;
        }
        if (isOpen(p) && !p.drawer.contains(target)) { closeDrawer(p, false); }
    });

    document.addEventListener("keydown", function (ev) {
        var p;
        if (ev.key !== "Escape") { return; }
        p = parts();
        if (!p || !isOpen(p)) { return; }
        ev.preventDefault();
        closeDrawer(p, true);
    });

    // Focus leaving for anything but the drawer or its toggle closes it: the
    // drawer overlays the content, so Tab past its last link would otherwise
    // land on a control hidden underneath.
    document.addEventListener("focusin", function (ev) {
        var p = parts();
        var target = /** @type {Node} */ (ev.target);
        if (!p || !isOpen(p)) { return; }
        if (p.drawer.contains(target) || p.toggle.contains(target)) { return; }
        closeDrawer(p, false);
    });
}());
